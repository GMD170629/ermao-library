package com.ermao.library.shared.modules.administrativesettings.domain

enum class OrganizeStatusCategory(val wireValue: String) {
    Success("SUCCESS"),
    Failed("FAILED"),
    Recognizing("RECOGNIZING"),
    Waiting("WAITING"),
}

data class OrganizeJobFilter(
    val search: String? = null,
    val status: OrganizeStatusCategory? = null,
    val page: Int = 1,
    val pageSize: Int = 20,
)

data class OrganizeBookSummary(
    val id: String,
    val title: String,
    val author: String?,
    val availableMediaKinds: List<MediaKind>,
)

data class OrganizeJob(
    val id: String,
    val trigger: String,
    val statusCategory: OrganizeStatusCategory,
    val issueCodes: List<String>,
    val reasonCodes: List<String>,
    val metadataSources: List<String>,
    val createdAt: String?,
    val updatedAt: String?,
    val resourceId: String? = null,
    val book: OrganizeBookSummary,
)

data class OrganizeJobPage(
    val jobs: List<OrganizeJob>,
    val pageInfo: PageInfo,
    val statusCounts: Map<OrganizeStatusCategory, Int>,
    val providerNames: Map<String, String>,
)

data class PendingOrganizeJobs(
    val jobs: List<OrganizeJob>,
    val books: List<OrganizeBookSummary>,
    val total: Int,
)

data class OrganizeRunScope(
    val bookIds: List<String>,
    val rules: OrganizeRules,
)

data class OrganizeRun(
    val id: String,
    val trigger: String,
    /** OpenAPI intentionally leaves run status extensible; UI may display it but must not infer actions from unknown values. */
    val status: String,
    val scope: OrganizeRunScope,
    val queuedCount: Int,
    val completedCount: Int,
    val reviewCount: Int,
    val failedCount: Int,
    val startedAt: String?,
    val finishedAt: String?,
    val createdAt: String?,
    val updatedAt: String?,
)

data class OrganizeCandidate(
    val id: String,
    val title: String?,
    val author: String?,
    val availableMediaKinds: List<MediaKind>,
    val coverPath: String?,
    val metadataQuality: Int,
    val reasonCodes: List<String>,
    val createdAt: String?,
)

data class OrganizeCandidates(
    val total: Int,
    val reasonCounts: Map<String, Int>,
    val books: List<OrganizeCandidate>,
)

enum class OrganizeScheduleMode(val wireValue: String) {
    Manual("MANUAL"),
    Interval("INTERVAL"),
}

enum class LocalMetadataSource(val wireValue: String) {
    SidecarOpf("SIDECAR_OPF"),
    Embedded("EMBEDDED"),
    Path("PATH"),
}

data class OrganizeRules(
    val unrecognized: Boolean,
    val missingMetadata: Boolean,
)

data class OrganizePolicy(
    val id: String,
    val enabled: Boolean,
    val scheduleMode: OrganizeScheduleMode,
    val intervalMinutes: Int,
    val autoRunOnNew: Boolean,
    val autoRunOnNewSince: String?,
    val rules: OrganizeRules,
    val writeMetadataToFiles: Boolean,
    val preferLocalMetadata: Boolean,
    val localMetadataPriority: List<LocalMetadataSource>,
    val lastScheduledAt: String?,
    val nextRunAt: String?,
    val updatedAt: String,
)

data class OpfQueueStatus(
    val pendingTargets: Int,
    val pendingPreparations: Int,
    val capacity: Int,
    val utilization: Double,
)

data class LibraryOperation(
    val id: String,
    val action: String,
    val status: String,
    val summary: String,
    val targetType: String? = null,
    val targetId: String? = null,
    val expiresAt: String? = null,
    val undoneAt: String? = null,
    val createdAt: String? = null,
    val updatedAt: String? = null,
    val undoAvailable: Boolean,
)

enum class CategoryKind(val wireValue: String) {
    Author("AUTHOR"),
    Tag("TAG"),
    Series("SERIES"),
}

data class CategoryFilter(
    val kind: CategoryKind,
    val search: String? = null,
    val page: Int = 1,
    val pageSize: Int = 20,
)

data class LibraryCategory(
    val id: String,
    val kind: CategoryKind,
    val name: String,
    val normalizedName: String,
    val aliases: List<String>,
    val bookCount: Int,
    val createdAt: String?,
    val updatedAt: String?,
)

data class CategoryPage(
    val categories: List<LibraryCategory>,
    val pageInfo: PageInfo,
)

sealed interface ProviderSettingValue {
    data class Text(val value: String) : ProviderSettingValue

    data class Toggle(val value: Boolean) : ProviderSettingValue

    data class Integer(val value: Long) : ProviderSettingValue

    data class Decimal(val value: Double) : ProviderSettingValue

    data class TextList(val value: List<String>) : ProviderSettingValue

    data object Empty : ProviderSettingValue
}

data class ProviderAutomaticRateLimit(
    val requests: Int,
    val periodSeconds: Double,
)

data class ProviderConfigField(
    val key: String,
    val label: String,
    val kind: String,
    val required: Boolean,
    val secret: Boolean,
    val placeholder: String?,
    val help: String?,
    val defaultValue: ProviderSettingValue,
)

data class MetadataProvider(
    val id: String,
    val sourceId: String?,
    val name: String,
    val version: String,
    val description: String,
    val mode: String,
    val mediaKinds: List<MediaKind>,
    val fields: List<String>,
    val capabilities: List<String>,
    val automaticRateLimit: ProviderAutomaticRateLimit?,
    val configFields: List<ProviderConfigField>,
    val config: Map<String, ProviderSettingValue>,
    val configuredSecrets: Map<String, Boolean>,
    val enabled: Boolean,
    val priority: Int,
    val lastTestAt: String?,
    val lastTestStatus: String?,
    val lastError: String?,
)

data class PipelineProvider(
    val providerId: String,
    val name: String,
    val description: String,
    val enabled: Boolean,
    val position: Int,
    val lastTestStatus: String?,
    val lastError: String?,
)

data class MetadataPipeline(
    val mediaKind: MediaKind,
    val providers: List<PipelineProvider>,
)

data class MetadataProviders(
    val providers: List<MetadataProvider>,
    val pipelines: List<MetadataPipeline>,
)

data class MetadataProviderUpdate(
    val enabled: Boolean,
    val priority: Int,
    val config: Map<String, ProviderSettingValue>,
    val clearSecrets: List<String>,
)

data class MetadataPipelineEntry(
    val providerId: String,
    val enabled: Boolean,
)

data class ProviderTestResult(
    val ok: Boolean,
    val provider: MetadataProvider,
)
