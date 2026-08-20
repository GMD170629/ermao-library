package com.ermao.library.shared.modules.administrativesettings.application

import com.ermao.library.shared.modules.administrativesettings.domain.AdministrativeSettingsContext
import com.ermao.library.shared.modules.administrativesettings.domain.AdministrativeSettingsResult
import com.ermao.library.shared.modules.administrativesettings.domain.BackupArchive
import com.ermao.library.shared.modules.administrativesettings.domain.BackupDownload
import com.ermao.library.shared.modules.administrativesettings.domain.BackupRestoreResult
import com.ermao.library.shared.modules.administrativesettings.domain.BackupRestoreConfirmation
import com.ermao.library.shared.modules.administrativesettings.domain.CategoryFilter
import com.ermao.library.shared.modules.administrativesettings.domain.CategoryKind
import com.ermao.library.shared.modules.administrativesettings.domain.CategoryPage
import com.ermao.library.shared.modules.administrativesettings.domain.ClearedManagementEvents
import com.ermao.library.shared.modules.administrativesettings.domain.CreateManagedUser
import com.ermao.library.shared.modules.administrativesettings.domain.DeletedManagedUser
import com.ermao.library.shared.modules.administrativesettings.domain.DirectoryNode
import com.ermao.library.shared.modules.administrativesettings.domain.EmailSettings
import com.ermao.library.shared.modules.administrativesettings.domain.EventStorage
import com.ermao.library.shared.modules.administrativesettings.domain.HealthRun
import com.ermao.library.shared.modules.administrativesettings.domain.ImportDeleteMode
import com.ermao.library.shared.modules.administrativesettings.domain.ImportPreferences
import com.ermao.library.shared.modules.administrativesettings.domain.ImportRescanRequest
import com.ermao.library.shared.modules.administrativesettings.domain.ImportScanJob
import com.ermao.library.shared.modules.administrativesettings.domain.ImportScanStatus
import com.ermao.library.shared.modules.administrativesettings.domain.ImportTask
import com.ermao.library.shared.modules.administrativesettings.domain.ImportTaskDeletion
import com.ermao.library.shared.modules.administrativesettings.domain.ImportTaskFilter
import com.ermao.library.shared.modules.administrativesettings.domain.ImportTaskPage
import com.ermao.library.shared.modules.administrativesettings.domain.ImportTaskLogPage
import com.ermao.library.shared.modules.administrativesettings.domain.KindleSettings
import com.ermao.library.shared.modules.administrativesettings.domain.KindleTask
import com.ermao.library.shared.modules.administrativesettings.domain.KindleTaskFilter
import com.ermao.library.shared.modules.administrativesettings.domain.KindleTaskPage
import com.ermao.library.shared.modules.administrativesettings.domain.LibraryOperation
import com.ermao.library.shared.modules.administrativesettings.domain.LogSettings
import com.ermao.library.shared.modules.administrativesettings.domain.ManagedPasswordChange
import com.ermao.library.shared.modules.administrativesettings.domain.ManagedUser
import com.ermao.library.shared.modules.administrativesettings.domain.ManagementEventFilter
import com.ermao.library.shared.modules.administrativesettings.domain.ManagementEvent
import com.ermao.library.shared.modules.administrativesettings.domain.ManagementEventPage
import com.ermao.library.shared.modules.administrativesettings.domain.MediaKind
import com.ermao.library.shared.modules.administrativesettings.domain.MetadataPipelineEntry
import com.ermao.library.shared.modules.administrativesettings.domain.MetadataProvider
import com.ermao.library.shared.modules.administrativesettings.domain.MetadataProviderUpdate
import com.ermao.library.shared.modules.administrativesettings.domain.MetadataProviders
import com.ermao.library.shared.modules.administrativesettings.domain.Library
import com.ermao.library.shared.modules.administrativesettings.domain.LibraryDraft
import com.ermao.library.shared.modules.administrativesettings.domain.Libraries
import com.ermao.library.shared.modules.administrativesettings.domain.OpdsSettings
import com.ermao.library.shared.modules.administrativesettings.domain.OpfQueueStatus
import com.ermao.library.shared.modules.administrativesettings.domain.OrganizeCandidates
import com.ermao.library.shared.modules.administrativesettings.domain.OrganizeJob
import com.ermao.library.shared.modules.administrativesettings.domain.OrganizeJobFilter
import com.ermao.library.shared.modules.administrativesettings.domain.OrganizeJobPage
import com.ermao.library.shared.modules.administrativesettings.domain.OrganizeRun
import com.ermao.library.shared.modules.administrativesettings.domain.PendingOrganizeJobs
import com.ermao.library.shared.modules.administrativesettings.domain.OrganizePolicy
import com.ermao.library.shared.modules.administrativesettings.domain.ProviderTestResult
import com.ermao.library.shared.modules.administrativesettings.domain.QueueOperation
import com.ermao.library.shared.modules.administrativesettings.domain.SmtpSettingsUpdate
import com.ermao.library.shared.modules.administrativesettings.domain.SmtpTestResult
import com.ermao.library.shared.modules.administrativesettings.domain.UpdateManagedUser
import com.ermao.library.shared.modules.administrativesettings.domain.WorkDetailTabOrder

interface AdministrativeSettingsRepository {
    /** Rejects every result started before this call. Cancellation still propagates normally. */
    suspend fun invalidatePendingResponses()

    suspend fun loadKindleSettings(context: AdministrativeSettingsContext): AdministrativeSettingsResult<KindleSettings>
    suspend fun updateKindleEmail(context: AdministrativeSettingsContext, email: String): AdministrativeSettingsResult<KindleSettings>
    suspend fun listKindleTasks(context: AdministrativeSettingsContext, filter: KindleTaskFilter): AdministrativeSettingsResult<KindleTaskPage>
    suspend fun createKindleTask(context: AdministrativeSettingsContext, fileId: String, workId: String?): AdministrativeSettingsResult<KindleTask>
    suspend fun cancelKindleTask(context: AdministrativeSettingsContext, taskId: String): AdministrativeSettingsResult<KindleTask>
    suspend fun retryKindleTask(context: AdministrativeSettingsContext, taskId: String): AdministrativeSettingsResult<KindleTask>
    suspend fun deleteKindleTask(context: AdministrativeSettingsContext, taskId: String): AdministrativeSettingsResult<Boolean>

    suspend fun loadEmailSettings(context: AdministrativeSettingsContext): AdministrativeSettingsResult<EmailSettings>
    suspend fun updateEmailSettings(context: AdministrativeSettingsContext, update: SmtpSettingsUpdate): AdministrativeSettingsResult<EmailSettings>
    suspend fun testSmtp(context: AdministrativeSettingsContext, update: SmtpSettingsUpdate): AdministrativeSettingsResult<SmtpTestResult>

    suspend fun listUsers(context: AdministrativeSettingsContext): AdministrativeSettingsResult<List<ManagedUser>>
    suspend fun loadUser(context: AdministrativeSettingsContext, userId: String): AdministrativeSettingsResult<ManagedUser>
    suspend fun createUser(context: AdministrativeSettingsContext, user: CreateManagedUser): AdministrativeSettingsResult<ManagedUser>
    suspend fun updateUser(context: AdministrativeSettingsContext, userId: String, user: UpdateManagedUser): AdministrativeSettingsResult<ManagedUser>
    suspend fun resetUserPassword(context: AdministrativeSettingsContext, userId: String, password: String): AdministrativeSettingsResult<ManagedPasswordChange>
    suspend fun deleteUser(context: AdministrativeSettingsContext, userId: String, confirmation: String): AdministrativeSettingsResult<DeletedManagedUser>

    suspend fun loadLibraries(context: AdministrativeSettingsContext): AdministrativeSettingsResult<Libraries>
    suspend fun createLibrary(context: AdministrativeSettingsContext, folder: LibraryDraft): AdministrativeSettingsResult<Library>
    suspend fun updateLibrary(context: AdministrativeSettingsContext, folderId: String, folder: LibraryDraft): AdministrativeSettingsResult<Library>
    suspend fun deleteLibrary(context: AdministrativeSettingsContext, folderId: String): AdministrativeSettingsResult<Boolean>
    suspend fun loadDirectory(context: AdministrativeSettingsContext, path: String?): AdministrativeSettingsResult<DirectoryNode>

    suspend fun listImportTasks(context: AdministrativeSettingsContext, filter: ImportTaskFilter): AdministrativeSettingsResult<ImportTaskPage>
    suspend fun loadImportTask(context: AdministrativeSettingsContext, taskId: String): AdministrativeSettingsResult<ImportTask>
    suspend fun listImportTaskLogs(context: AdministrativeSettingsContext, taskId: String, page: Int = 1, pageSize: Int = 50): AdministrativeSettingsResult<ImportTaskLogPage>
    suspend fun retryImportTask(context: AdministrativeSettingsContext, taskId: String): AdministrativeSettingsResult<ImportTask>
    suspend fun deleteImportTask(context: AdministrativeSettingsContext, taskId: String, mode: ImportDeleteMode, deleteLibraryRecord: Boolean): AdministrativeSettingsResult<ImportTaskDeletion>
    suspend fun clearCompletedImportTasks(context: AdministrativeSettingsContext): AdministrativeSettingsResult<Int>
    suspend fun clearImportQueue(context: AdministrativeSettingsContext): AdministrativeSettingsResult<QueueOperation>
    suspend fun rescanImportFolders(context: AdministrativeSettingsContext): AdministrativeSettingsResult<ImportRescanRequest>
    suspend fun scanDirectory(context: AdministrativeSettingsContext, path: String): AdministrativeSettingsResult<ImportScanJob>
    suspend fun listImportScanJobs(context: AdministrativeSettingsContext, status: ImportScanStatus?): AdministrativeSettingsResult<List<ImportScanJob>>
    suspend fun loadImportScanJob(context: AdministrativeSettingsContext, jobId: String): AdministrativeSettingsResult<ImportScanJob>
    suspend fun cancelImportScanJob(context: AdministrativeSettingsContext, jobId: String): AdministrativeSettingsResult<ImportScanJob>
    suspend fun loadImportPreferences(context: AdministrativeSettingsContext): AdministrativeSettingsResult<ImportPreferences>
    suspend fun updateImportPreferences(context: AdministrativeSettingsContext, preferences: ImportPreferences): AdministrativeSettingsResult<ImportPreferences>

    suspend fun listOrganizeJobs(context: AdministrativeSettingsContext, filter: OrganizeJobFilter): AdministrativeSettingsResult<OrganizeJobPage>
    suspend fun loadPendingOrganizeJobs(context: AdministrativeSettingsContext): AdministrativeSettingsResult<PendingOrganizeJobs>
    suspend fun listOrganizeRuns(context: AdministrativeSettingsContext): AdministrativeSettingsResult<List<OrganizeRun>>
    suspend fun loadOrganizeJob(context: AdministrativeSettingsContext, jobId: String): AdministrativeSettingsResult<OrganizeJob>
    suspend fun recognizeOrganizeJob(context: AdministrativeSettingsContext, jobId: String): AdministrativeSettingsResult<OrganizeJob>
    suspend fun deleteOrganizeJob(context: AdministrativeSettingsContext, jobId: String): AdministrativeSettingsResult<Boolean>
    suspend fun loadOrganizeCandidates(context: AdministrativeSettingsContext): AdministrativeSettingsResult<OrganizeCandidates>
    suspend fun loadOrganizePolicy(context: AdministrativeSettingsContext): AdministrativeSettingsResult<OrganizePolicy>
    suspend fun updateOrganizePolicy(context: AdministrativeSettingsContext, policy: OrganizePolicy): AdministrativeSettingsResult<OrganizePolicy>
    suspend fun loadOpfQueueStatus(context: AdministrativeSettingsContext): AdministrativeSettingsResult<OpfQueueStatus>

    suspend fun listLibraryOperations(context: AdministrativeSettingsContext): AdministrativeSettingsResult<List<LibraryOperation>>
    suspend fun undoLibraryOperation(context: AdministrativeSettingsContext, operationId: String): AdministrativeSettingsResult<LibraryOperation>
    suspend fun listCategories(context: AdministrativeSettingsContext, filter: CategoryFilter): AdministrativeSettingsResult<CategoryPage>
    suspend fun renameCategory(context: AdministrativeSettingsContext, categoryId: String, name: String): AdministrativeSettingsResult<LibraryOperation>
    suspend fun mergeCategories(context: AdministrativeSettingsContext, kind: CategoryKind, targetId: String, sourceIds: List<String>): AdministrativeSettingsResult<LibraryOperation>
    suspend fun deleteCategory(context: AdministrativeSettingsContext, categoryId: String): AdministrativeSettingsResult<LibraryOperation>

    suspend fun loadMetadataProviders(context: AdministrativeSettingsContext): AdministrativeSettingsResult<MetadataProviders>
    suspend fun loadMetadataProvider(context: AdministrativeSettingsContext, providerId: String): AdministrativeSettingsResult<MetadataProvider>
    suspend fun updateMetadataProvider(context: AdministrativeSettingsContext, providerId: String, update: MetadataProviderUpdate): AdministrativeSettingsResult<MetadataProvider>
    suspend fun testMetadataProvider(context: AdministrativeSettingsContext, providerId: String): AdministrativeSettingsResult<ProviderTestResult>
    suspend fun updateMetadataPipeline(context: AdministrativeSettingsContext, mediaKind: MediaKind, entries: List<MetadataPipelineEntry>): AdministrativeSettingsResult<MetadataProviders>

    suspend fun loadOpdsSettings(context: AdministrativeSettingsContext): AdministrativeSettingsResult<OpdsSettings>
    suspend fun updateOpdsSettings(context: AdministrativeSettingsContext, enabled: Boolean, publicBaseUrl: String?): AdministrativeSettingsResult<OpdsSettings>
    suspend fun listBackups(context: AdministrativeSettingsContext): AdministrativeSettingsResult<List<BackupArchive>>
    suspend fun loadBackup(context: AdministrativeSettingsContext, backupId: String): AdministrativeSettingsResult<BackupArchive>
    suspend fun createBackup(context: AdministrativeSettingsContext): AdministrativeSettingsResult<BackupArchive>
    suspend fun downloadBackup(context: AdministrativeSettingsContext, backupId: String, maximumBytes: Int): AdministrativeSettingsResult<BackupDownload>
    suspend fun restoreBackup(context: AdministrativeSettingsContext, backupId: String, confirmation: BackupRestoreConfirmation): AdministrativeSettingsResult<BackupRestoreResult>
    suspend fun deleteBackup(context: AdministrativeSettingsContext, backupId: String): AdministrativeSettingsResult<Boolean>
    suspend fun loadWorkDetailTabOrder(context: AdministrativeSettingsContext): AdministrativeSettingsResult<WorkDetailTabOrder>
    suspend fun updateWorkDetailTabOrder(context: AdministrativeSettingsContext, order: WorkDetailTabOrder): AdministrativeSettingsResult<WorkDetailTabOrder>

    suspend fun startHealthRun(context: AdministrativeSettingsContext): AdministrativeSettingsResult<HealthRun>
    suspend fun loadHealthRun(context: AdministrativeSettingsContext, runId: String): AdministrativeSettingsResult<HealthRun>
    suspend fun restartImportQueue(context: AdministrativeSettingsContext): AdministrativeSettingsResult<QueueOperation>
    suspend fun loadQueueOperation(context: AdministrativeSettingsContext, operationId: String): AdministrativeSettingsResult<QueueOperation>

    suspend fun listManagementEvents(context: AdministrativeSettingsContext, filter: ManagementEventFilter): AdministrativeSettingsResult<ManagementEventPage>
    suspend fun loadAllManagementEventsForExport(context: AdministrativeSettingsContext, filter: ManagementEventFilter): AdministrativeSettingsResult<List<ManagementEvent>>
    suspend fun clearManagementEvents(context: AdministrativeSettingsContext): AdministrativeSettingsResult<ClearedManagementEvents>
    suspend fun loadLogSettings(context: AdministrativeSettingsContext): AdministrativeSettingsResult<LogSettings>
    suspend fun updateLogCapacity(context: AdministrativeSettingsContext, maximumBytes: Long): AdministrativeSettingsResult<EventStorage>
}
