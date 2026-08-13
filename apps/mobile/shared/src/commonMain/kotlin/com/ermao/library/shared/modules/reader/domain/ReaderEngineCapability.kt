package com.ermao.library.shared.modules.reader.domain

/**
 * A platform advertises a format only after its parser, navigator and exact-location bridge are
 * all present. This prevents a successful download from being mistaken for reader support.
 */
data class ReaderEngineCapability(
    val sourceFormat: ReaderSourceFormat,
    val localArtifactRequired: Boolean = true,
    val parserAvailable: Boolean,
    val navigatorAvailable: Boolean,
    val exactLocationAvailable: Boolean,
) {
    val canOpen: Boolean
        get() = parserAvailable && navigatorAvailable && exactLocationAvailable
}

class ReaderEngineCapabilityRegistry(capabilities: Iterable<ReaderEngineCapability>) {
    private val capabilityList = capabilities.toList()
    private val byFormat = capabilityList.associateBy(ReaderEngineCapability::sourceFormat).also {
        require(it.size == capabilityList.size) { "Reader engine capability is duplicated" }
    }

    fun capability(sourceFormat: ReaderSourceFormat): ReaderEngineCapability? = byFormat[sourceFormat]

    fun requireOpenable(sourceFormat: ReaderSourceFormat): ReaderEngineCapability =
        requireNotNull(byFormat[sourceFormat]?.takeIf(ReaderEngineCapability::canOpen)) {
            "Reader engine is unavailable for ${sourceFormat.wireValue}"
        }
}
