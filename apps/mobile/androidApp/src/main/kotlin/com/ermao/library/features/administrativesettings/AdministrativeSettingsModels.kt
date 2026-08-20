package com.ermao.library.features.administrativesettings

import androidx.navigation3.runtime.NavKey
import kotlinx.serialization.Serializable

@Serializable
sealed interface AdministrativeSettingsRoute : NavKey {
    @Serializable
    data object Root : AdministrativeSettingsRoute

    @Serializable
    data class EmailKindle(val tab: EmailKindleTab = EmailKindleTab.Kindle) : AdministrativeSettingsRoute

    @Serializable
    data object KindleQueue : AdministrativeSettingsRoute

    @Serializable
    data object Users : AdministrativeSettingsRoute

    @Serializable
    data class UserEdit(val userId: String? = null) : AdministrativeSettingsRoute

    @Serializable
    data class UserAccess(val userId: String) : AdministrativeSettingsRoute

    @Serializable
    data object LibrarySources : AdministrativeSettingsRoute

    @Serializable
    data class LibrarySourceEdit(val sourceId: String? = null, val selectedPath: String? = null) : AdministrativeSettingsRoute

    @Serializable
    data class ServerDirectory(val path: String? = null, val purpose: ServerDirectoryPurpose) : AdministrativeSettingsRoute

    @Serializable
    data object ImportTasks : AdministrativeSettingsRoute

    @Serializable
    data class ImportTaskDetail(val taskId: String) : AdministrativeSettingsRoute

    @Serializable
    data object ImportScanJobs : AdministrativeSettingsRoute

    @Serializable
    data class ImportScanJob(val jobId: String) : AdministrativeSettingsRoute

    @Serializable
    data object ImportPreferences : AdministrativeSettingsRoute

    @Serializable
    data object OrganizeQueue : AdministrativeSettingsRoute

    @Serializable
    data object OrganizeCandidates : AdministrativeSettingsRoute

    @Serializable
    data object OrganizeRuns : AdministrativeSettingsRoute

    @Serializable
    data object RecognitionPolicy : AdministrativeSettingsRoute

    @Serializable
    data object LibraryOperations : AdministrativeSettingsRoute

    @Serializable
    data class CategoryGovernance(val kind: CategoryKind = CategoryKind.Author) : AdministrativeSettingsRoute

    @Serializable
    data object MetadataProviders : AdministrativeSettingsRoute

    @Serializable
    data class MetadataProviderEdit(val providerId: String) : AdministrativeSettingsRoute

    @Serializable
    data class MetadataPipeline(val mediaKind: MediaKind = MediaKind.Ebook) : AdministrativeSettingsRoute

    @Serializable
    data object Opds : AdministrativeSettingsRoute

    @Serializable
    data object Backups : AdministrativeSettingsRoute

    @Serializable
    data object DetailOrder : AdministrativeSettingsRoute

    @Serializable
    data class Health(val runId: String? = null) : AdministrativeSettingsRoute

    @Serializable
    data object Logs : AdministrativeSettingsRoute

}

@Serializable
enum class EmailKindleTab { Kindle, Smtp }

@Serializable
enum class CategoryKind { Author, Tag, Series }

@Serializable
sealed interface ServerDirectoryPurpose {
    @Serializable
    data object CreateLibrarySource : ServerDirectoryPurpose

    @Serializable
    data class EditLibrarySource(val sourceId: String) : ServerDirectoryPurpose

    @Serializable
    data object ScanDirectory : ServerDirectoryPurpose
}

enum class AdministrativeLocale { ZhCn, EnUs }

enum class AdministrativeCapability {
    ViewAdministration,
    ManageEmail,
    ManageKindleQueue,
    ManageUsers,
    ManageLibrarySources,
    ManageImports,
    ManageOrganization,
    ManageMetadata,
    ManageOpds,
    ManageBackups,
    ManageSystem,
    ViewLogs,
    ManageLogs,
}

data class AdministrativeSettingsContext(
    val profileId: String,
    val serverIdentity: String,
    val actorId: String,
    val locale: AdministrativeLocale,
    val capabilities: Set<AdministrativeCapability>,
)

enum class AdministrativeErrorKind {
    Unauthorized,
    Forbidden,
    Validation,
    Conflict,
    RateLimited,
    Unavailable,
    NotFound,
    Cancelled,
    Unknown,
}

data class AdministrativeFailure(
    val kind: AdministrativeErrorKind,
    val code: String,
    val fieldCodes: Map<String, String> = emptyMap(),
    val retryable: Boolean = false,
)

sealed interface AdministrativeResult<out T> {
    data class Content<T>(val value: T) : AdministrativeResult<T>
    data class Failure(val error: AdministrativeFailure) : AdministrativeResult<Nothing>
}

enum class AdministrativePagePhase { Idle, Loading, Content, Failure, PermissionDenied }

data class AdministrativeScreenState(
    val phase: AdministrativePagePhase = AdministrativePagePhase.Idle,
    val snapshot: AdministrativePageSnapshot? = null,
    val failure: AdministrativeFailure? = null,
    val mutationInFlight: Boolean = false,
)

data class AdministrativePageState<out T : AdministrativePageSnapshot>(
    val phase: AdministrativePagePhase,
    val snapshot: T?,
    val failure: AdministrativeFailure?,
    val mutationInFlight: Boolean,
)

sealed interface AdministrativePageSnapshot

data class ManagementSnapshot(
    val entries: List<ManagementEntry>,
) : AdministrativePageSnapshot

data class ManagementEntry(
    val route: AdministrativeSettingsRoute,
    val status: String? = null,
    val attention: Boolean = false,
)

data class EmailKindleSnapshot(
    val kindle: KindleSettings,
    val smtp: SmtpSettings?,
    val canManageSmtp: Boolean,
) : AdministrativePageSnapshot

data class KindleSettings(
    val recipient: String,
    val smtpConfigured: Boolean,
    val senderEmail: String,
)

data class SmtpSettings(
    val host: String,
    val port: Int,
    val encryption: SmtpEncryption,
    val senderEmail: String,
    val username: String,
    val passwordConfigured: Boolean,
    val senderName: String,
    val maximumAttachmentMegabytes: Double?,
    val lastTest: ConnectionTest? = null,
)

enum class SmtpEncryption { None, StartTls, Tls }

data class ConnectionTest(
    val successful: Boolean,
    val latencyMilliseconds: Long? = null,
    val code: String? = null,
)

data class KindleQueueSnapshot(
    val tasks: List<KindleTask>,
) : AdministrativePageSnapshot

data class KindleTask(
    val id: String,
    val title: String,
    val maskedRecipient: String,
    val status: QueueStatus,
    val progress: Float? = null,
    val statusCode: String? = null,
    val createdAtLabel: String,
)

enum class QueueStatus { Queued, Running, Completed, Failed, Cancelled }

data class UsersSnapshot(
    val users: List<AdministrativeUser>,
    val page: Int,
    val pageCount: Int,
    val totalCount: Int,
) : AdministrativePageSnapshot

data class AdministrativeUser(
    val id: String,
    val displayName: String,
    val email: String,
    val role: UserRole,
    val enabled: Boolean,
    val locale: AdministrativeLocale,
)

enum class UserRole { Administrator, Member }

data class UserEditorSnapshot(
    val user: AdministrativeUser?,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val selectedSourceIds: Set<String>,
) : AdministrativePageSnapshot

data class UserAccessSnapshot(
    val user: AdministrativeUser,
    val allLibraries: Boolean,
    val canViewManualImports: Boolean,
    val sources: List<AccessSource>,
) : AdministrativePageSnapshot

data class AccessSource(
    val id: String,
    val name: String,
    val path: String,
    val workCount: Int?,
    val selected: Boolean,
)

data class LibrarySourcesSnapshot(
    val sources: List<LibrarySource>,
) : AdministrativePageSnapshot

data class LibrarySource(
    val id: String,
    val name: String,
    val path: String,
    val enabled: Boolean,
    val organizationMode: LibraryOrganizationMode,
    val description: String?,
)

enum class LibraryOrganizationMode { Flat, Volumes, Audiobook }

data class LibrarySourceEditorSnapshot(
    val source: LibrarySource?,
    val ignorePatterns: String,
    val ignoreHidden: Boolean,
    val minimumFileSizeBytes: Long,
) : AdministrativePageSnapshot

data class ServerDirectorySnapshot(
    val purpose: ServerDirectoryPurpose,
    val name: String,
    val path: String,
    val readable: Boolean,
    val errorCode: String?,
    val children: List<ServerDirectoryEntry>,
) : AdministrativePageSnapshot

data class ServerDirectoryEntry(
    val name: String,
    val path: String,
    val readable: Boolean,
)

enum class MediaKind { Ebook, Comic, Audiobook }

data class ImportTasksSnapshot(
    val queueHealthy: Boolean,
    val runningCount: Int,
    val tasks: List<ImportTask>,
) : AdministrativePageSnapshot

data class ImportTask(
    val id: String,
    val fileName: String,
    val sourcePath: String,
    val createdAtLabel: String,
    val status: QueueStatus,
    val progress: Float? = null,
    val statusCode: String? = null,
)

data class ImportTaskDetailSnapshot(
    val task: ImportTask,
    val requestedTitle: String?,
    val requestedAuthor: String?,
    val processedAssetCount: Int,
    val assetCount: Int,
    val attempts: Int,
    val retryable: Boolean,
    val errorSummary: String?,
    val logs: List<ImportTaskLogEntry>,
) : AdministrativePageSnapshot

data class ImportTaskLogEntry(
    val id: String,
    val level: String,
    val message: String,
    val createdAtLabel: String?,
)

data class ImportScanJobsSnapshot(
    val jobs: List<ImportScanJobSummary>,
) : AdministrativePageSnapshot

data class ImportScanJobSnapshot(
    val job: ImportScanJobSummary,
) : AdministrativePageSnapshot

data class ImportScanJobSummary(
    val id: String,
    val rootPath: String,
    val status: QueueStatus,
    val directoriesScanned: Int,
    val filesScanned: Int,
    val candidatesFound: Int,
    val queuedCount: Int,
    val skippedCount: Int,
    val errorCount: Int,
    val startedAtLabel: String?,
    val updatedAtLabel: String,
) {
    val active: Boolean get() = status == QueueStatus.Queued || status == QueueStatus.Running
}

data class ImportPreferencesSnapshot(
    val allowedExtensions: List<String>,
    val ignorePatterns: String,
) : AdministrativePageSnapshot

data class OrganizeQueueSnapshot(
    val pendingCount: Int,
    val tasks: List<OrganizeTask>,
) : AdministrativePageSnapshot

data class OrganizeRunsSnapshot(
    val runs: List<OrganizeRunSummary>,
) : AdministrativePageSnapshot

data class OrganizeRunSummary(
    val id: String,
    val trigger: String,
    val status: String,
    val queuedCount: Int,
    val completedCount: Int,
    val reviewCount: Int,
    val failedCount: Int,
    val startedAtLabel: String?,
    val finishedAtLabel: String?,
)

data class OrganizeTask(
    val id: String,
    val title: String,
    val subtitle: String,
    val status: OrganizeStatus,
)

enum class OrganizeStatus { AwaitingRecognition, NeedsConfirmation, Organized, Failed }

data class OrganizeCandidatesSnapshot(
    val candidates: List<RecognitionCandidate>,
) : AdministrativePageSnapshot

data class RecognitionCandidate(
    val id: String,
    val title: String,
    val author: String,
    val confidencePercent: Int,
)

data class RecognitionPolicySnapshot(
    val scheduled: Boolean,
    val intervalHours: Int,
    val runAfterImport: Boolean,
    val saveMetadataToOpf: Boolean,
    val opfQueueCompleted: Int,
    val opfQueueTotal: Int,
    val localMetadataFirst: Boolean,
    val sourcePriority: List<MetadataSource>,
    val includeUnrecognized: Boolean,
    val includeMissingAuthorOrCover: Boolean,
) : AdministrativePageSnapshot

enum class MetadataSource { Opf, Embedded, PathAndFileName, Provider }

data class LibraryOperationsSnapshot(
    val operations: List<LibraryOperationSummary>,
) : AdministrativePageSnapshot

data class LibraryOperationSummary(
    val id: String,
    val action: String,
    val status: String,
    val summary: String,
    val createdAtLabel: String?,
    val expiresAtLabel: String?,
    val undoAvailable: Boolean,
)

data class CategoryGovernanceSnapshot(
    val kind: CategoryKind,
    val entries: List<CategoryEntry>,
) : AdministrativePageSnapshot

data class CategoryEntry(
    val id: String,
    val canonicalName: String,
    val aliases: List<String>,
    val workCount: Int,
    val selected: Boolean,
)

data class MetadataProvidersSnapshot(
    val providers: List<MetadataProvider>,
    val pipelineSummary: String,
) : AdministrativePageSnapshot

data class MetadataProvider(
    val id: String,
    val name: String,
    val enabled: Boolean,
    val available: Boolean,
    val priority: Int,
    val latencyMilliseconds: Long? = null,
)

data class MetadataProviderEditorSnapshot(
    val provider: MetadataProvider,
    val fields: List<MetadataProviderField>,
    val lastTest: ConnectionTest? = null,
) : AdministrativePageSnapshot

data class MetadataProviderField(
    val key: String,
    val label: String,
    val kind: MetadataProviderFieldKind,
    val required: Boolean,
    val secret: Boolean,
    val value: ProviderFieldValue,
    val configuredSecret: Boolean,
)

enum class MetadataProviderFieldKind { Text, Toggle, Integer, Decimal, TextList }

sealed interface ProviderFieldValue {
    data class Text(val value: String) : ProviderFieldValue
    data class Toggle(val value: Boolean) : ProviderFieldValue
    data class Integer(val value: Long) : ProviderFieldValue
    data class Decimal(val value: Double) : ProviderFieldValue
    data class TextList(val value: List<String>) : ProviderFieldValue
    data object Empty : ProviderFieldValue
}

data class MetadataPipelineSnapshot(
    val steps: List<MetadataPipelineStep>,
) : AdministrativePageSnapshot

data class MetadataPipelineStep(
    val id: String,
    val label: String,
    val enabled: Boolean,
)

data class OpdsSnapshot(
    val enabled: Boolean,
    val running: Boolean,
    val publicBaseUrl: String,
    val catalogUrl: String,
) : AdministrativePageSnapshot

data class BackupsSnapshot(
    val backups: List<BackupRecord>,
) : AdministrativePageSnapshot

data class BackupRecord(
    val id: String,
    val fileName: String,
    val automatic: Boolean,
    val sizeLabel: String,
    val createdAtLabel: String,
    val workCount: Int,
    val progressCount: Int,
    val sourceCount: Int,
)

data class DetailOrderSnapshot(
    val items: List<DetailSection>,
) : AdministrativePageSnapshot

data class DetailSection(
    val id: String,
    val label: String,
)

data class HealthSnapshot(
    val runId: String?,
    val startedAtLabel: String?,
    val status: HealthStatus?,
    val healthyCount: Int,
    val totalCount: Int,
    val checks: List<HealthCheck>,
    val importQueueRestarting: Boolean,
    val queueOperationId: String? = null,
    val queueOperationStatus: String? = null,
    val queueOperationMessageCode: String? = null,
) : AdministrativePageSnapshot

data class HealthCheck(
    val id: String,
    val label: String,
    val group: HealthGroup,
    val status: HealthStatus,
    val detail: String? = null,
)

enum class HealthGroup { StorageAndDatabase, BackgroundQueues, FeatureConfiguration }
enum class HealthStatus { Healthy, Warning, Checking, Failed }

data class LogsSnapshot(
    val query: LogQuery,
    val usedMegabytes: Int,
    val capacityMegabytes: Int,
    val records: List<LogRecord>,
) : AdministrativePageSnapshot

data class LogQuery(
    val search: String = "",
    val level: LogLevel? = null,
    val source: String? = null,
    val days: Int = 7,
)

enum class LogLevel { Information, Warning, Error }

data class LogRecord(
    val id: String,
    val timestampLabel: String,
    val level: LogLevel,
    val source: String,
    val summary: String,
    val correlationId: String?,
    val target: String?,
)

data class AdministrativeExportFile(
    val suggestedFileName: String,
    val mimeType: String,
    val bytes: ByteArray,
) {
    override fun equals(other: Any?): Boolean =
        this === other || other is AdministrativeExportFile && suggestedFileName == other.suggestedFileName &&
            mimeType == other.mimeType && bytes.contentEquals(other.bytes)

    override fun hashCode(): Int = 31 * (31 * suggestedFileName.hashCode() + mimeType.hashCode()) + bytes.contentHashCode()
}

sealed interface AdministrativeSettingsEffect {
    data class OperationSucceeded(val operation: AdministrativeOperation) : AdministrativeSettingsEffect
    data class OperationFailed(val operation: AdministrativeOperation, val error: AdministrativeFailure) : AdministrativeSettingsEffect
    data class ExportReady(val file: AdministrativeExportFile) : AdministrativeSettingsEffect
}

enum class AdministrativeOperation {
    SaveKindle,
    SaveSmtp,
    TestSmtp,
    CancelKindleTask,
    RetryKindleTask,
    DeleteKindleTask,
    SaveUser,
    SaveUserAccess,
    ResetUserPassword,
    SetUserEnabled,
    DeleteUser,
    SaveLibrarySource,
    DeleteLibrarySource,
    RescanLibrarySource,
    ScanDirectory,
    RetryImportTask,
    DeleteImportTask,
    RescanAllSources,
    ClearCompletedImports,
    CancelImportScan,
    SaveImportPreferences,
    StartRecognition,
    CancelOrganizeTask,
    SaveRecognitionPolicy,
    MergeCategories,
    RenameCategory,
    DeleteCategory,
    UndoLibraryOperation,
    SaveMetadataProviders,
    SaveMetadataProvider,
    TestMetadataProvider,
    SaveMetadataPipeline,
    SaveOpds,
    CreateBackup,
    DownloadBackup,
    RestoreBackup,
    DeleteBackup,
    SaveDetailOrder,
    RunHealthCheck,
    RestartImportQueue,
    SaveLogCapacity,
    ExportLogs,
    ClearInformationalLogs,
}
