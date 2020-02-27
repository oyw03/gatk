import logging
import numpy as np
import pyro
import pyro.distributions as dist
from pyro import poutine
from pyro.ops.indexing import Vindex
from pyro.infer import config_enumerate, Predictive, infer_discrete
from pyro.infer.autoguide import AutoDiagonalNormal
import torch

from .constants import SVTypes


class SVGenotyperData(object):
    def __init__(self,
                 pe_t: torch.Tensor,
                 sr1_t: torch.Tensor,
                 sr2_t: torch.Tensor,
                 depth_t: torch.Tensor,
                 rd_gt_prob_t: torch.Tensor):
        self.pe_t = pe_t
        self.sr1_t = sr1_t
        self.sr2_t = sr2_t
        self.depth_t = depth_t
        self.rd_gt_prob_t = rd_gt_prob_t


class SVGenotyperPyroModel(object):
    def __init__(self,
                 svtype: SVTypes,
                 k: int = None,
                 mu_eps_pe: float = 0.1,
                 mu_eps_sr1: float = 0.1,
                 mu_eps_sr2: float = 0.1,
                 mu_lambda_pe: float = 0.1,
                 mu_lambda_sr1: float = 0.1,
                 mu_lambda_sr2: float = 0.1,
                 var_phi_pe: float = 0.1,
                 var_phi_sr1: float = 0.1,
                 var_phi_sr2: float = 0.1,
                 mu_eta_q: float = 0.1,
                 mu_eta_r: float = 0.01,
                 device: str = 'cpu',
                 loss: dict = None):
        self.mu_eps_pe = mu_eps_pe
        self.mu_eps_sr1 = mu_eps_sr1
        self.mu_eps_sr2 = mu_eps_sr2
        self.mu_lambda_pe = mu_lambda_pe
        self.mu_lambda_sr1 = mu_lambda_sr1
        self.mu_lambda_sr2 = mu_lambda_sr2
        self.var_phi_pe = var_phi_pe
        self.var_phi_sr1 = var_phi_sr1
        self.var_phi_sr2 = var_phi_sr2
        self.mu_eta_q = mu_eta_q
        self.mu_eta_r = mu_eta_r
        self.svtype = svtype
        self.device = device
        if loss is None:
            self.loss = {'epoch': [], 'elbo': []}
        else:
            self.loss = loss

        if k is not None:
            self.k = k
        elif svtype in [SVTypes.DEL, SVTypes.INS, SVTypes.INV]:
            self.k = 3
        elif svtype == SVTypes.DUP:
            self.k = 5
        else:
            raise ValueError('SV type {:s} not supported for genotyping.'.format(str(svtype.name)))

        if svtype == SVTypes.DEL:
            self.latent_sites = ['pi_sr1', 'pi_sr2', 'pi_pe', 'pi_rd', 'eps_pe', 'eps_sr1', 'eps_sr2',
                                 'lambda_pe', 'lambda_sr1', 'lambda_sr2', 'phi_pe', 'phi_sr1', 'phi_sr2']
        elif svtype == SVTypes.DUP:
            self.latent_sites = ['pi_sr1', 'pi_sr2', 'pi_pe', 'pi_rd', 'eps_pe', 'eps_sr1', 'eps_sr2',
                                 'lambda_pe', 'lambda_sr1', 'lambda_sr2', 'phi_pe', 'phi_sr1', 'phi_sr2']
        elif svtype == SVTypes.INS:
            self.latent_sites = ['pi_sr1', 'pi_sr2', 'eps_sr1', 'eps_sr2',
                                 'lambda_sr1', 'lambda_sr2', 'phi_sr1', 'phi_sr2']
        elif svtype == SVTypes.INV:
            self.latent_sites = ['pi_sr1', 'pi_sr2', 'pi_pe', 'eps_pe', 'eps_sr1', 'eps_sr2',
                                 'lambda_pe', 'lambda_sr1', 'lambda_sr2', 'phi_pe', 'phi_sr1', 'phi_sr2']
        else:
            raise ValueError('SV type {:s} not supported for genotyping.'.format(str(svtype.name)))

        if self.k == 3:
            self.latent_sites.append('eta_q')
        elif self.k == 5:
            self.latent_sites.append('eta_q')
            self.latent_sites.append('eta_r')
        else:
            raise ValueError('Unsupported number of states: {:d}'.format(self.k))

        self.guide = AutoDiagonalNormal(poutine.block(self.model, expose=self.latent_sites))

    @config_enumerate(default="parallel")
    def model(self,
              data_pe: torch.Tensor,
              data_sr1: torch.Tensor,
              data_sr2: torch.Tensor,
              depth_t: torch.Tensor,
              rd_gt_prob_t: torch.Tensor):

        n_variants = data_pe.shape[0]
        n_samples = data_pe.shape[1]
        zero_t = torch.zeros(1, device=self.device)
        one_t = torch.ones(1, device=self.device)
        k_range_t = torch.arange(0, self.k).to(dtype=torch.get_default_dtype(), device=self.device)

        pi_sr1 = pyro.sample('pi_sr1', dist.Beta(one_t, one_t))
        pi_sr2 = pyro.sample('pi_sr2', dist.Beta(one_t, one_t))

        lambda_sr1 = pyro.sample('lambda_sr1', dist.Exponential(one_t)) * self.mu_lambda_sr1
        lambda_sr2 = pyro.sample('lambda_sr2', dist.Exponential(one_t)) * self.mu_lambda_sr2

        if self.svtype == SVTypes.DEL or self.svtype == SVTypes.DUP:
            pi_rd = pyro.sample('pi_rd', dist.Beta(one_t, one_t))

        if self.svtype != SVTypes.INS:
            pi_pe = pyro.sample('pi_pe', dist.Beta(one_t, one_t))
            lambda_pe = pyro.sample('lambda_pe', dist.Exponential(one_t)) * self.mu_lambda_pe

        with pyro.plate('variant', n_variants, dim=-2, device=self.device):
            if self.svtype == SVTypes.DEL or self.svtype == SVTypes.DUP:
                m_rd = pyro.sample('m_rd', dist.Bernoulli(pi_rd))
            else:
                m_rd = zero_t.expand(n_variants).expand(n_variants).unsqueeze(-1)

            if self.svtype != SVTypes.INS:
                phi_pe = pyro.sample('phi_pe', dist.LogNormal(zero_t, self.var_phi_pe))
                eps_pe = pyro.sample('eps_pe', dist.Exponential(one_t)) * self.mu_eps_pe
                m_pe = pyro.sample('m_pe', dist.Bernoulli(pi_pe))
            else:
                m_pe = zero_t.expand(n_variants).unsqueeze(-1)

            phi_sr1 = pyro.sample('phi_sr1', dist.LogNormal(zero_t, self.var_phi_sr1))
            phi_sr2 = pyro.sample('phi_sr2', dist.LogNormal(zero_t, self.var_phi_sr2))
            eps_sr1 = pyro.sample('eps_sr1', dist.Exponential(one_t)) * self.mu_eps_sr1
            eps_sr2 = pyro.sample('eps_sr2', dist.Exponential(one_t)) * self.mu_eps_sr2
            m_sr1 = pyro.sample('m_sr1', dist.Bernoulli(pi_sr1))
            m_sr2 = pyro.sample('m_sr2', dist.Bernoulli(pi_sr2))

            eta_q = pyro.sample('eta_q', dist.Exponential(one_t)) * self.mu_eta_q
            if self.k == 3:
                q = 1. - torch.exp(-eta_q)
                p = 1. - q
                z0 = p * p
                z1 = 2 * p * q
                z2 = q * q
                z_prior = torch.stack([z0, z1, z2], dim=-1)
            elif self.k == 5:
                eta_r = pyro.sample('eta_r', dist.Exponential(one_t)) * self.mu_eta_r
                q = 1 - torch.exp(-eta_q)
                r = (1 - q) * (1 - torch.exp(-eta_r))
                p = 1 - q - r
                z0 = p * p
                z1 = 2 * q * p
                z2 = 2 * p * r + q * q
                z3 = 2 * q * r
                z4 = r * r
                z_prior = torch.stack([z0, z1, z2, z3, z4], dim=-1)
            else:
                raise ValueError("Unsupported number of states K = {:d}".format(self.k))

            with pyro.plate('sample', n_samples, dim=-1, device=self.device):

                if self.svtype != SVTypes.INS:
                    # V x 1 x K
                    m1_locs_pe = phi_pe.unsqueeze(-1) * k_range_t.unsqueeze(0).unsqueeze(0) + eps_pe.unsqueeze(-1)
                    # V x S x K
                    m0_locs_pe = eps_pe.unsqueeze(-1).expand(n_variants, n_samples, self.k)
                    # V x S x K
                    locs_pe = (1. - m_pe.unsqueeze(-1)) * m0_locs_pe + m_pe.unsqueeze(-1) * m1_locs_pe

                # V x 1 x K
                m1_locs_sr1 = phi_sr1.unsqueeze(-1) * k_range_t.unsqueeze(0).unsqueeze(0) + eps_sr1.unsqueeze(-1)
                m1_locs_sr2 = phi_sr2.unsqueeze(-1) * k_range_t.unsqueeze(0).unsqueeze(0) + eps_sr2.unsqueeze(-1)
                # V x S x K
                m0_locs_sr1 = eps_sr1.unsqueeze(-1).expand(n_variants, n_samples, self.k)
                m0_locs_sr2 = eps_sr2.unsqueeze(-1).expand(n_variants, n_samples, self.k)
                # V x S x K
                locs_sr1 = (1. - m_sr1.unsqueeze(-1)) * m0_locs_sr1 + m_sr1.unsqueeze(-1) * m1_locs_sr1
                locs_sr2 = (1. - m_sr2.unsqueeze(-1)) * m0_locs_sr2 + m_sr2.unsqueeze(-1) * m1_locs_sr2

                z_weights = m_rd.unsqueeze(-1) * rd_gt_prob_t + (1. - m_rd.unsqueeze(-1)) * z_prior
                z = pyro.sample('z', dist.Categorical(z_weights))

                if self.svtype != SVTypes.INS:
                    # V x 1 x K
                    mu_obs_pe = depth_t * Vindex(locs_pe)[..., z]
                    var_pe = mu_obs_pe * (1. + lambda_pe)
                    r_pe = mu_obs_pe * mu_obs_pe / (var_pe - mu_obs_pe)
                    p_pe = (var_pe - mu_obs_pe) / var_pe
                    pyro.sample('pe_obs', dist.NegativeBinomial(total_count=r_pe, probs=p_pe), obs=data_pe)

                # V x 1 x K
                mu_obs_sr1 = depth_t * Vindex(locs_sr1)[..., z]
                mu_obs_sr2 = depth_t * Vindex(locs_sr2)[..., z]

                var_sr1 = mu_obs_sr1 * (1. + lambda_sr1)
                var_sr2 = mu_obs_sr2 * (1. + lambda_sr2)
                r_sr1 = mu_obs_sr1 * mu_obs_sr1 / (var_sr1 - mu_obs_sr1)
                r_sr2 = mu_obs_sr2 * mu_obs_sr2 / (var_sr2 - mu_obs_sr2)
                p_sr1 = (var_sr1 - mu_obs_sr1) / var_sr1
                p_sr2 = (var_sr2 - mu_obs_sr2) / var_sr2
                pyro.sample('sr1_obs', dist.NegativeBinomial(total_count=r_sr1, probs=p_sr1), obs=data_sr1)
                pyro.sample('sr2_obs', dist.NegativeBinomial(total_count=r_sr2, probs=p_sr2), obs=data_sr2)

    def infer_predictive(self, data: SVGenotyperData, n_samples: int = 1000):
        logging.info("Running predictive distribution inference...")
        predictive = Predictive(self.model, guide=self.guide, num_samples=n_samples, return_sites=self.latent_sites)
        sample = predictive(data_pe=data.pe_t, data_sr1=data.sr1_t, data_sr2=data.sr2_t, depth_t=data.depth_t, rd_gt_prob_t=data.rd_gt_prob_t)
        logging.info("Inference complete.")
        return {key: sample[key].detach().cpu().numpy() for key in sample}

    def infer_discrete(self, data: SVGenotyperData, svtype: SVTypes, log_freq: int = 100, n_samples: int = 1000):
        logging.info("Running discrete inference...")
        sites = ['z', 'm_sr1', 'm_sr2']
        if svtype == SVTypes.DEL or svtype == SVTypes.DUP or svtype == SVTypes.INV:
            sites.append('m_pe')
        if svtype == SVTypes.DEL or svtype == SVTypes.DUP:
            sites.append('m_rd')
        posterior_samples = []
        guide_trace = poutine.trace(self.guide).get_trace(data_pe=data.pe_t, data_sr1=data.sr1_t,
                                                          data_sr2=data.sr2_t, depth_t=data.depth_t,
                                                          rd_gt_prob_t=data.rd_gt_prob_t)
        trained_model = poutine.replay(self.model, trace=guide_trace)
        with torch.no_grad():
            for i in range(n_samples):
                inferred_model = infer_discrete(trained_model, temperature=1, first_available_dim=-3)
                trace = poutine.trace(inferred_model).get_trace(data_pe=data.pe_t, data_sr1=data.sr1_t,
                                                                data_sr2=data.sr2_t, depth_t=data.depth_t,
                                                                rd_gt_prob_t=data.rd_gt_prob_t)
                posterior_samples.append({site: trace.nodes[site]["value"].detach().cpu() for site in sites})
                if (i + 1) % log_freq == 0:
                    logging.info("[sample {:d}] discrete latent".format(i + 1))
        posterior_samples = {site: torch.stack([posterior_samples[i][site] for i in range(n_samples)], dim=0).numpy() for site in sites}
        logging.info("Inference complete.")

        z = posterior_samples['z']
        m_sr1 = posterior_samples['m_sr1']
        m_sr2 = posterior_samples['m_sr2']
        if 'm_pe' in posterior_samples:
            m_pe = posterior_samples['m_pe']
        else:
            m_pe = np.zeros(m_sr1.shape)
        if 'm_rd' in posterior_samples:
            m_rd = posterior_samples['m_rd']
        else:
            m_rd = np.zeros(m_sr1.shape)
        return {
            "z": z,
            "m_pe": m_pe,
            "m_sr1": m_sr1,
            "m_sr2": m_sr2,
            "m_rd": m_rd
        }

    def infer_discrete_full(self, data: SVGenotyperData, svtype: SVTypes, log_freq: int = 100, n_samples: int = 1000):
        logging.info("Running discrete inference...")
        posterior_samples = []
        guide_trace = poutine.trace(self.guide).get_trace(data_pe=data.pe_t, data_sr1=data.sr1_t,
                                                          data_sr2=data.sr2_t, depth_t=data.depth_t,
                                                          rd_gt_prob_t=data.rd_gt_prob_t)
        trained_model = poutine.replay(self.model, trace=guide_trace)
        for i in range(n_samples):
            inferred_model = infer_discrete(trained_model, temperature=1, first_available_dim=-3)
            trace = poutine.trace(inferred_model).get_trace(data_pe=data.pe_t, data_sr1=data.sr1_t,
                                                            data_sr2=data.sr2_t, depth_t=data.depth_t,
                                                            rd_gt_prob_t=data.rd_gt_prob_t)
            posterior_samples.append([trace.nodes["_RETURN"]["value"]["z"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["r_pe"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["r_sr1"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["r_sr2"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["p_pe"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["p_sr1"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["p_sr2"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["m_pe"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["m_sr1"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["m_sr2"].detach().cpu(),
                                      trace.nodes["_RETURN"]["value"]["m_rd"].detach().cpu()])
            if (i + 1) % log_freq == 0:
                logging.info("[sample {:d}] discrete latent".format(i + 1))
        posterior_samples = [torch.stack([posterior_samples[j][i] for j in range(n_samples)], dim=0) for i in range(11)]

        z = posterior_samples[0]
        r_pe = posterior_samples[1]
        r_sr1 = posterior_samples[2]
        r_sr2 = posterior_samples[3]
        p_pe = posterior_samples[4]
        p_sr1 = posterior_samples[5]
        p_sr2 = posterior_samples[6]
        m_pe = posterior_samples[7]
        m_sr1 = posterior_samples[8]
        m_sr2 = posterior_samples[9]
        m_rd = posterior_samples[10]

        samples_pe = []
        samples_sr1 = []
        samples_sr2 = []
        for i in range(n_samples):
            if svtype == SVTypes.INS:
                samples_pe.append(torch.zeros(1, device='cpu').unsqueeze(-1).expand(r_pe.shape[0], r_pe.shape[1]))
            else:
                samples_pe.append(dist.NegativeBinomial(total_count=r_pe[i, ...], probs=p_pe[i, ...]).sample().detach())
            samples_sr1.append(dist.NegativeBinomial(total_count=r_sr1[i, ...], probs=p_sr1[i, ...]).sample().detach())
            samples_sr2.append(dist.NegativeBinomial(total_count=r_sr2[i, ...], probs=p_sr2[i, ...]).sample().detach())
            if (i + 1) % log_freq == 0:
                logging.info("[sample {:d}] discrete observed".format(i + 1))

        pe = torch.stack(samples_pe, dim=0)
        sr1 = torch.stack(samples_sr1, dim=0)
        sr2 = torch.stack(samples_sr2, dim=0)
        logging.info("Inference complete.")
        return {
            "z": z.numpy(),
            "pe": pe.numpy(),
            "sr1": sr1.numpy(),
            "sr2": sr2.numpy(),
            "m_pe": m_pe.numpy(),
            "m_sr1": m_sr1.numpy(),
            "m_sr2": m_sr2.numpy(),
            "m_rd": m_rd.numpy()
        }