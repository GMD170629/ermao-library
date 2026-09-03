package com.ermao.library.features.administrativesettings

interface AdministrativeSettingsRepository {
    suspend fun load(
        context: AdministrativeSettingsContext,
        route: AdministrativeSettingsRoute,
    ): AdministrativeResult<AdministrativePageSnapshot>

    suspend fun execute(
        context: AdministrativeSettingsContext,
        command: AdministrativeCommand,
    ): AdministrativeResult<AdministrativeCommandReceipt>
}

fun interface AdministrativeSettingsSideEffects {
    fun requireReauthentication()
}

data class AdministrativeCommandReceipt(
    val invalidatedRoutes: Set<AdministrativeSettingsRoute>,
    val exportFile: AdministrativeExportFile? = null,
)

sealed interface AdministrativeCommand {
    val operation: AdministrativeOperation
    val ownerRoute: AdministrativeSettingsRoute

    data class SaveKindle(val settings: KindleSettings) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveKindle
        override val ownerRoute = AdministrativeSettingsRoute.EmailKindle(EmailKindleTab.Kindle)
    }

    data class SaveSmtp(val settings: SmtpSettingsDraft) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveSmtp
        override val ownerRoute = AdministrativeSettingsRoute.EmailKindle(EmailKindleTab.Kindle)
    }

    data class TestSmtp(val settings: SmtpSettingsDraft) : AdministrativeCommand {
        override val operation = AdministrativeOperation.TestSmtp
        override val ownerRoute = AdministrativeSettingsRoute.EmailKindle(EmailKindleTab.Kindle)
    }

    data class CancelKindleTask(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.CancelKindleTask
        override val ownerRoute = AdministrativeSettingsRoute.KindleQueue
    }

    data class RetryKindleTask(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.RetryKindleTask
        override val ownerRoute = AdministrativeSettingsRoute.KindleQueue
    }

    data class DeleteKindleTask(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DeleteKindleTask
        override val ownerRoute = AdministrativeSettingsRoute.KindleQueue
    }

    data class SaveUser(val draft: UserDraft) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveUser
        override val ownerRoute = AdministrativeSettingsRoute.UserEdit(draft.id)
    }

    data class SaveUserAccess(val userId: String, val allLibraries: Boolean, val sourceIds: Set<String>) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveUserAccess
        override val ownerRoute = AdministrativeSettingsRoute.UserAccess(userId)
    }

    data class ResetUserPassword(val userId: String, val newPassword: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.ResetUserPassword
        override val ownerRoute = AdministrativeSettingsRoute.UserEdit(userId)
    }

    data class SetUserEnabled(val userId: String, val enabled: Boolean) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SetUserEnabled
        override val ownerRoute = AdministrativeSettingsRoute.UserEdit(userId)
    }

    data class DeleteUser(val userId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DeleteUser
        override val ownerRoute = AdministrativeSettingsRoute.UserEdit(userId)
    }

    data class SaveLibrarySource(val draft: LibrarySourceDraft) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveLibrarySource
        override val ownerRoute = AdministrativeSettingsRoute.LibrarySourceEdit(draft.id)
    }

    data class DeleteLibrarySource(val sourceId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DeleteLibrarySource
        override val ownerRoute = AdministrativeSettingsRoute.LibrarySourceEdit(sourceId)
    }

    data class RescanLibrarySource(val sourceId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.RescanLibrarySource
        override val ownerRoute = AdministrativeSettingsRoute.LibrarySourceEdit(sourceId)
    }

    data class ScanDirectory(val directory: NativeDirectorySelection) : AdministrativeCommand {
        override val operation = AdministrativeOperation.ScanDirectory
        override val ownerRoute = AdministrativeSettingsRoute.LibrarySources
    }

    data class RetryImportTask(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.RetryImportTask
        override val ownerRoute = AdministrativeSettingsRoute.ImportTasks
    }

    data class DeleteImportTask(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DeleteImportTask
        override val ownerRoute = AdministrativeSettingsRoute.ImportTasks
    }

    data object RescanAllSources : AdministrativeCommand {
        override val operation = AdministrativeOperation.RescanAllSources
        override val ownerRoute = AdministrativeSettingsRoute.ImportTasks
    }

    data object ClearCompletedImports : AdministrativeCommand {
        override val operation = AdministrativeOperation.ClearCompletedImports
        override val ownerRoute = AdministrativeSettingsRoute.ImportTasks
    }

    data class CancelImportScan(val jobId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.CancelImportScan
        override val ownerRoute = AdministrativeSettingsRoute.ImportScanJob(jobId)
    }

    data class SaveImportPreferences(val preferences: ImportPreferencesSnapshot) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveImportPreferences
        override val ownerRoute = AdministrativeSettingsRoute.ImportPreferences
    }

    data class StartRecognition(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.StartRecognition
        override val ownerRoute = AdministrativeSettingsRoute.OrganizeQueue
    }

    data class DeleteOrganizeTask(val taskId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.CancelOrganizeTask
        override val ownerRoute = AdministrativeSettingsRoute.OrganizeQueue
    }

    data class SaveRecognitionPolicy(val policy: RecognitionPolicyDraft) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveRecognitionPolicy
        override val ownerRoute = AdministrativeSettingsRoute.RecognitionPolicy
    }

    data class MergeCategories(val kind: CategoryKind, val targetId: String, val sourceIds: Set<String>) : AdministrativeCommand {
        override val operation = AdministrativeOperation.MergeCategories
        override val ownerRoute = AdministrativeSettingsRoute.CategoryGovernance(kind)
    }

    data class RenameCategory(val kind: CategoryKind, val categoryId: String, val name: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.RenameCategory
        override val ownerRoute = AdministrativeSettingsRoute.CategoryGovernance(kind)
    }

    data class DeleteCategory(val kind: CategoryKind, val categoryId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DeleteCategory
        override val ownerRoute = AdministrativeSettingsRoute.CategoryGovernance(kind)
    }

    data class UndoLibraryOperation(val operationId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.UndoLibraryOperation
        override val ownerRoute = AdministrativeSettingsRoute.LibraryOperations
    }

    data class SaveMetadataProviders(val providers: List<MetadataProvider>) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveMetadataProviders
        override val ownerRoute = AdministrativeSettingsRoute.MetadataProviders
    }

    data class SaveMetadataProvider(val draft: MetadataProviderDraft) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveMetadataProvider
        override val ownerRoute = AdministrativeSettingsRoute.MetadataProviderEdit(draft.id)
    }

    data class TestMetadataProvider(val providerId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.TestMetadataProvider
        override val ownerRoute = AdministrativeSettingsRoute.MetadataProviderEdit(providerId)
    }

    data class SaveOpds(val enabled: Boolean, val publicBaseUrl: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveOpds
        override val ownerRoute = AdministrativeSettingsRoute.Opds
    }

    data object CreateBackup : AdministrativeCommand {
        override val operation = AdministrativeOperation.CreateBackup
        override val ownerRoute = AdministrativeSettingsRoute.Backups
    }

    data class DownloadBackup(val backupId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DownloadBackup
        override val ownerRoute = AdministrativeSettingsRoute.Backups
    }

    data class RestoreBackup(val backupId: String, val confirmation: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.RestoreBackup
        override val ownerRoute = AdministrativeSettingsRoute.Backups
    }

    data class DeleteBackup(val backupId: String) : AdministrativeCommand {
        override val operation = AdministrativeOperation.DeleteBackup
        override val ownerRoute = AdministrativeSettingsRoute.Backups
    }

    data class SaveDetailOrder(val sectionIds: List<String>) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveDetailOrder
        override val ownerRoute = AdministrativeSettingsRoute.DetailOrder
    }

    data object RunHealthCheck : AdministrativeCommand {
        override val operation = AdministrativeOperation.RunHealthCheck
        override val ownerRoute = AdministrativeSettingsRoute.Health()
    }

    data class SaveLogCapacity(val megabytes: Int) : AdministrativeCommand {
        override val operation = AdministrativeOperation.SaveLogCapacity
        override val ownerRoute = AdministrativeSettingsRoute.Logs
    }

    data class ExportLogs(val query: LogQuery) : AdministrativeCommand {
        override val operation = AdministrativeOperation.ExportLogs
        override val ownerRoute = AdministrativeSettingsRoute.Logs
    }

    data object ClearInformationalLogs : AdministrativeCommand {
        override val operation = AdministrativeOperation.ClearInformationalLogs
        override val ownerRoute = AdministrativeSettingsRoute.Logs
    }
}

data class SmtpSettingsDraft(
    val host: String,
    val port: Int,
    val encryption: SmtpEncryption,
    val senderEmail: String,
    val username: String,
    val newPassword: String?,
    val senderName: String,
    val maximumAttachmentMegabytes: Double?,
)

data class UserDraft(
    val id: String?,
    val displayName: String,
    val email: String,
    val role: UserRole,
    val enabled: Boolean,
    val initialPassword: String?,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val sourceIds: Set<String>,
    val locale: AdministrativeLocale,
)

data class NativeDirectorySelection(
    val uri: String,
    val displayName: String,
)

data class LibrarySourceDraft(
    val id: String?,
    val displayName: String,
    val directory: NativeDirectorySelection,
    val enabled: Boolean,
    val organizationMode: LibraryOrganizationMode,
    val ignorePatterns: String,
    val ignoreHidden: Boolean,
    val minimumFileSizeBytes: Long,
    val description: String?,
)

data class RecognitionPolicyDraft(
    val scheduled: Boolean,
    val intervalHours: Int,
    val runAfterImport: Boolean,
    val saveMetadataToOpf: Boolean,
    val localMetadataFirst: Boolean,
    val sourcePriority: List<MetadataSource>,
    val includeUnrecognized: Boolean,
    val includeMissingAuthorOrCover: Boolean,
)

data class MetadataProviderDraft(
    val id: String,
    val enabled: Boolean,
    val priority: Int,
    val fields: Map<String, ProviderFieldValue>,
    val clearSecrets: Set<String>,
)

internal fun AdministrativeSettingsRoute.requiredCapability(): AdministrativeCapability = when (this) {
    AdministrativeSettingsRoute.Root -> AdministrativeCapability.ViewAdministration
    is AdministrativeSettingsRoute.EmailKindle -> when (tab) {
        EmailKindleTab.Kindle -> AdministrativeCapability.ManageEmail
        EmailKindleTab.Smtp -> AdministrativeCapability.ManageSystem
    }
    AdministrativeSettingsRoute.KindleQueue -> AdministrativeCapability.ManageKindleQueue
    AdministrativeSettingsRoute.Users,
    is AdministrativeSettingsRoute.UserEdit,
    is AdministrativeSettingsRoute.UserAccess,
    -> AdministrativeCapability.ManageUsers
    AdministrativeSettingsRoute.LibrarySources,
    is AdministrativeSettingsRoute.LibrarySourceEdit,
    is AdministrativeSettingsRoute.ServerDirectory,
    -> AdministrativeCapability.ManageLibrarySources
    AdministrativeSettingsRoute.ImportTasks,
    is AdministrativeSettingsRoute.ImportTaskDetail,
    AdministrativeSettingsRoute.ImportScanJobs,
    is AdministrativeSettingsRoute.ImportScanJob,
    AdministrativeSettingsRoute.ImportPreferences,
    -> AdministrativeCapability.ManageImports
    AdministrativeSettingsRoute.OrganizeQueue,
    AdministrativeSettingsRoute.OrganizeCandidates,
    AdministrativeSettingsRoute.OrganizeRuns,
    AdministrativeSettingsRoute.RecognitionPolicy,
    AdministrativeSettingsRoute.LibraryOperations,
    is AdministrativeSettingsRoute.CategoryGovernance,
    -> AdministrativeCapability.ManageOrganization
    AdministrativeSettingsRoute.MetadataProviders,
    is AdministrativeSettingsRoute.MetadataProviderEdit,
    -> AdministrativeCapability.ManageMetadata
    AdministrativeSettingsRoute.Opds -> AdministrativeCapability.ManageOpds
    AdministrativeSettingsRoute.Backups -> AdministrativeCapability.ManageBackups
    AdministrativeSettingsRoute.DetailOrder,
    is AdministrativeSettingsRoute.Health,
    -> AdministrativeCapability.ManageSystem
    AdministrativeSettingsRoute.Logs -> AdministrativeCapability.ViewLogs
}

internal fun AdministrativeCommand.requiredCapability(): AdministrativeCapability = when (this) {
    is AdministrativeCommand.SaveKindle -> AdministrativeCapability.ManageEmail
    is AdministrativeCommand.SaveSmtp,
    is AdministrativeCommand.TestSmtp,
    -> AdministrativeCapability.ManageSystem
    is AdministrativeCommand.CancelKindleTask,
    is AdministrativeCommand.RetryKindleTask,
    is AdministrativeCommand.DeleteKindleTask,
    -> AdministrativeCapability.ManageKindleQueue
    is AdministrativeCommand.SaveUser,
    is AdministrativeCommand.SaveUserAccess,
    is AdministrativeCommand.ResetUserPassword,
    is AdministrativeCommand.SetUserEnabled,
    is AdministrativeCommand.DeleteUser,
    -> AdministrativeCapability.ManageUsers
    is AdministrativeCommand.SaveLibrarySource,
    is AdministrativeCommand.DeleteLibrarySource,
    is AdministrativeCommand.RescanLibrarySource,
    is AdministrativeCommand.ScanDirectory,
    -> AdministrativeCapability.ManageLibrarySources
    is AdministrativeCommand.RetryImportTask,
    is AdministrativeCommand.DeleteImportTask,
    AdministrativeCommand.RescanAllSources,
    AdministrativeCommand.ClearCompletedImports,
    is AdministrativeCommand.CancelImportScan,
    is AdministrativeCommand.SaveImportPreferences,
    -> AdministrativeCapability.ManageImports
    is AdministrativeCommand.StartRecognition,
    is AdministrativeCommand.DeleteOrganizeTask,
    is AdministrativeCommand.SaveRecognitionPolicy,
    is AdministrativeCommand.MergeCategories,
    is AdministrativeCommand.RenameCategory,
    is AdministrativeCommand.DeleteCategory,
    is AdministrativeCommand.UndoLibraryOperation,
    -> AdministrativeCapability.ManageOrganization
    is AdministrativeCommand.SaveMetadataProviders,
    is AdministrativeCommand.SaveMetadataProvider,
    is AdministrativeCommand.TestMetadataProvider,
    -> AdministrativeCapability.ManageMetadata
    is AdministrativeCommand.SaveOpds -> AdministrativeCapability.ManageOpds
    AdministrativeCommand.CreateBackup,
    is AdministrativeCommand.DownloadBackup,
    is AdministrativeCommand.RestoreBackup,
    is AdministrativeCommand.DeleteBackup,
    -> AdministrativeCapability.ManageBackups
    is AdministrativeCommand.SaveDetailOrder,
    AdministrativeCommand.RunHealthCheck,
    -> AdministrativeCapability.ManageSystem
    is AdministrativeCommand.SaveLogCapacity,
    is AdministrativeCommand.ExportLogs,
    AdministrativeCommand.ClearInformationalLogs,
    -> AdministrativeCapability.ManageLogs
}
