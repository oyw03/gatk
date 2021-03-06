{
<#--- This template is used only by tests, to generate test input data--->

<#--- Store positional args in a WDL arg called "positionalArgs"--->
<#assign positionalArgs="positionalArgs"/>
    "${name}.dockerImage": "broadinstitute/gatk:${version}",
    "${name}.gatk": "java -cp /home/travis/build/broadinstitute/gatk/build/libs/gatk.jar org.broadinstitute.hellbender.CommandLineArgumentValidatorMain",
<#if runtimeProperties?? && runtimeProperties?size != 0 && runtimeProperties.memoryRequirements != "">
    "${name}.memoryRequirements": "${runtimeProperties.memoryRequirements}",
<#else>
    "${name}.memoryRequirements": "String",
</#if>
<#if runtimeProperties?? && runtimeProperties?size != 0 && runtimeProperties.diskRequirements != "">
    "${name}.diskRequirements": "${runtimeProperties.diskRequirements}",
<#else>
    "${name}.diskRequirements": "String",
</#if>
<#if runtimeProperties?? && runtimeProperties?size != 0 && runtimeProperties.cpuRequirements != "">
    "${name}.cpuRequirements": "${runtimeProperties.cpuRequirements}",
<#else>
    "${name}.cpuRequirements": "String",
</#if>
<#if runtimeProperties?? && runtimeProperties?size != 0 && runtimeProperties.preemptibleRequirements != "">
    "${name}.preemptibleRequirements": "${runtimeProperties.preemptibleRequirements}",
<#else>
    "${name}.preemptibleRequirements": "String",
</#if>
<#if runtimeProperties?? && runtimeProperties?size != 0 && runtimeProperties.bootdisksizegbRequirements != "">
    "${name}.bootdisksizegbRequirements": "${runtimeProperties.bootdisksizegbRequirements}",
<#else>
    "${name}.bootdisksizegbRequirements": "String",
</#if>

<#assign remainingArgCount=arguments.required?size + arguments.optional?size + arguments.common?size/>
<@taskinput heading="Positional Arguments" argsToUse=arguments.positional remainingCount=remainingArgCount/>
<#assign remainingArgCount=arguments.optional?size + arguments.common?size/>
<@taskinput heading="Required Arguments" argsToUse=arguments.required remainingCount=remainingArgCount/>
<#assign remainingArgCount=arguments.common?size/>
<@taskinput heading="Optional Tool Arguments" argsToUse=arguments.optional remainingCount=remainingArgCount/>
<#assign remainingArgCount=0/>
<@taskinput heading="Optional Common Arguments" argsToUse=arguments.common remainingCount=0/>

}
<#macro taskinput heading argsToUse remainingCount>
    <#if argsToUse?size != 0>
        <#list argsToUse as arg>
            <#if companionResources?? && companionResources[arg.name]??>
                <#list companionResources[arg.name] as companion>
    <#noparse>  "</#noparse>${name}.${companion.name?substring(2)}<#noparse>"</#noparse>: ${arg.testValue},
                </#list>
            </#if>
            <#if heading?starts_with("Positional")>
    <#noparse>  "</#noparse>${name}.${positionalArgs}<#noparse>"</#noparse>: <#rt/>
            <#else>
    <#noparse>  "</#noparse>${name}.${arg.name?substring(2)}<#noparse>"</#noparse>: <#rt/>
            </#if>
            <#if arg.testValue == "[]" || arg.testValue == "\"\"" || arg.testValue == "null">
null<#if !arg?is_last || remainingCount != 0>,</#if>
            <#else>
${arg.testValue}<#if !arg?is_last || remainingCount != 0>,</#if>
            </#if>
            <#if arg?is_last && remainingCount != 0>

            </#if>
        </#list>
    </#if>
</#macro>
