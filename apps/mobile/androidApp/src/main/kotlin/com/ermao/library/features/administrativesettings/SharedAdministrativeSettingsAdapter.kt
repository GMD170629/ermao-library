package com.ermao.library.features.administrativesettings

import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsContent as SharedContent
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsContext as SharedContext
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsError as SharedError
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsErrorKind as SharedErrorKind
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsFailure as SharedFailure
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository as SharedRepository
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsResult as SharedResult
import com.ermao.library.shared.modules.administrativesettings.BackupRestoreConfirmation as SharedRestoreConfirmation
import com.ermao.library.shared.modules.administrativesettings.CategoryFilter as SharedCategoryFilter
import com.ermao.library.shared.modules.administrativesettings.CategoryKind as SharedCategoryKind
import com.ermao.library.shared.modules.administrativesettings.CreateManagedUser as SharedCreateUser
import com.ermao.library.shared.modules.administrativesettings.HealthCheckStatus as SharedHealthCheckStatus
import com.ermao.library.shared.modules.administrativesettings.HealthRun as SharedHealthRun
import com.ermao.library.shared.modules.administrativesettings.HealthRunStatus as SharedHealthRunStatus
import com.ermao.library.shared.modules.administrativesettings.ImportDeleteMode as SharedImportDeleteMode
import com.ermao.library.shared.modules.administrativesettings.ImportPreferences as SharedImportPreferences
import com.ermao.library.shared.modules.administrativesettings.ImportTaskFilter as SharedImportTaskFilter
import com.ermao.library.shared.modules.administrativesettings.ImportTaskStatus as SharedImportTaskStatus
import com.ermao.library.shared.modules.administrativesettings.ImportScanStatus as SharedImportScanStatus
import com.ermao.library.shared.modules.administrativesettings.KindleTaskFilter as SharedKindleTaskFilter
import com.ermao.library.shared.modules.administrativesettings.KindleTaskStatus as SharedKindleTaskStatus
import com.ermao.library.shared.modules.administrativesettings.LocalMetadataSource as SharedLocalMetadataSource
import com.ermao.library.shared.modules.administrativesettings.ManagedLocale as SharedLocale
import com.ermao.library.shared.modules.administrativesettings.ManagedUser as SharedUser
import com.ermao.library.shared.modules.administrativesettings.ManagedUserRole as SharedUserRole
import com.ermao.library.shared.modules.administrativesettings.ManagedUserStatus as SharedUserStatus
import com.ermao.library.shared.modules.administrativesettings.ManagementEventFilter as SharedEventFilter
import com.ermao.library.shared.modules.administrativesettings.MediaKind as SharedMediaKind
import com.ermao.library.shared.modules.administrativesettings.MediaKindPolicy as SharedMediaKindPolicy
import com.ermao.library.shared.modules.administrativesettings.MetadataPipelineEntry as SharedPipelineEntry
import com.ermao.library.shared.modules.administrativesettings.MetadataProvider as SharedProvider
import com.ermao.library.shared.modules.administrativesettings.MetadataProviderUpdate as SharedProviderUpdate
import com.ermao.library.shared.modules.administrativesettings.MonitorFolderDraft as SharedFolderDraft
import com.ermao.library.shared.modules.administrativesettings.OrganizeJobFilter as SharedOrganizeFilter
import com.ermao.library.shared.modules.administrativesettings.OrganizePolicy as SharedOrganizePolicy
import com.ermao.library.shared.modules.administrativesettings.OrganizeRules as SharedOrganizeRules
import com.ermao.library.shared.modules.administrativesettings.OrganizeScheduleMode as SharedScheduleMode
import com.ermao.library.shared.modules.administrativesettings.SmtpSecurity as SharedSmtpSecurity
import com.ermao.library.shared.modules.administrativesettings.SmtpSettingsUpdate as SharedSmtpUpdate
import com.ermao.library.shared.modules.administrativesettings.UpdateManagedUser as SharedUpdateUser
import com.ermao.library.shared.modules.administrativesettings.WorkDetailTab as SharedDetailTab
import com.ermao.library.shared.modules.administrativesettings.WorkDetailTabOrder as SharedDetailOrder
import com.ermao.library.shared.modules.administrativesettings.domain.ProviderSettingValue as SharedProviderValue
import kotlin.math.roundToInt

class SharedAdministrativeSettingsAdapter(
    private val sharedRepository: SharedRepository,
    private val sharedContext: SharedContext,
    private val maximumBackupBytes: Int = 512 * 1024 * 1024,
) : AdministrativeSettingsRepository {
    private var currentHealthRun: SharedHealthRun? = null
    private var currentQueueOperationId: String? = null

    override suspend fun load(
        context: AdministrativeSettingsContext,
        route: AdministrativeSettingsRoute,
    ): AdministrativeResult<AdministrativePageSnapshot> = when (route) {
        AdministrativeSettingsRoute.Root -> AdministrativeResult.Content(managementSnapshot(context.capabilities))
        is AdministrativeSettingsRoute.EmailKindle -> loadEmailKindle(context, route)
        AdministrativeSettingsRoute.KindleQueue -> sharedRepository.listKindleTasks(sharedContext, SharedKindleTaskFilter()).map { page ->
            KindleQueueSnapshot(page.tasks.map { task ->
                KindleTask(task.id, task.bookTitle, maskEmail(task.recipientEmail), task.status.toLocal(), null, task.errorMessage, task.createdAt)
            })
        }
        AdministrativeSettingsRoute.Users -> sharedRepository.listUsers(sharedContext).map { users ->
            UsersSnapshot(users.map(SharedUser::toLocal), 1, 1, users.size)
        }
        is AdministrativeSettingsRoute.UserEdit -> loadUserEditor(route)
        is AdministrativeSettingsRoute.UserAccess -> loadUserAccess(route.userId)
        AdministrativeSettingsRoute.LibrarySources -> sharedRepository.loadMonitorFolders(sharedContext).map { result ->
            LibrarySourcesSnapshot(result.monitorRoot, result.folders.map { it.toLocal() })
        }
        is AdministrativeSettingsRoute.LibrarySourceEdit -> loadLibrarySourceEditor(route.sourceId)
        is AdministrativeSettingsRoute.ServerDirectory -> sharedRepository.loadDirectory(sharedContext, route.path).map { node ->
            ServerDirectorySnapshot(route.purpose, node.name, node.path, node.readable, node.error, node.children.map { ServerDirectoryEntry(it.name, it.path, it.readable) })
        }
        AdministrativeSettingsRoute.ImportTasks -> sharedRepository.listImportTasks(sharedContext, SharedImportTaskFilter(pageSize = 100)).map { page ->
            ImportTasksSnapshot(
                queueHealthy = page.summary.failed == 0,
                runningCount = page.tasks.count { it.status in setOf(SharedImportTaskStatus.Pending, SharedImportTaskStatus.Parsing) },
                tasks = page.tasks.map { task ->
                    ImportTask(
                        task.id, task.originalName ?: task.requestedTitle ?: task.sourcePath.substringAfterLast('/'), task.sourcePath,
                        task.createdAt, task.status.toLocal(), task.progress.coerceIn(0, 100) / 100f, task.errorCode,
                    )
                },
            )
        }
        is AdministrativeSettingsRoute.ImportTaskDetail -> loadImportTaskDetail(route.taskId)
        AdministrativeSettingsRoute.ImportScanJobs -> sharedRepository.listImportScanJobs(sharedContext, null).map { jobs ->
            ImportScanJobsSnapshot(jobs.map { it.toLocal() })
        }
        is AdministrativeSettingsRoute.ImportScanJob -> sharedRepository.loadImportScanJob(sharedContext, route.jobId).map { job ->
            ImportScanJobSnapshot(job.toLocal())
        }
        AdministrativeSettingsRoute.ImportPreferences -> sharedRepository.loadImportPreferences(sharedContext).map { it.toLocal() }
        AdministrativeSettingsRoute.OrganizeQueue -> sharedRepository.loadPendingOrganizeJobs(sharedContext).map { pending ->
            OrganizeQueueSnapshot(pending.total, pending.jobs.map { it.toLocal() })
        }
        AdministrativeSettingsRoute.OrganizeCandidates -> sharedRepository.loadOrganizeCandidates(sharedContext).map { candidates ->
            OrganizeCandidatesSnapshot(candidates.works.map {
                RecognitionCandidate(it.id, it.title.orEmpty(), it.author.orEmpty(), it.metadataQuality.coerceIn(0, 100))
            })
        }
        AdministrativeSettingsRoute.OrganizeRuns -> sharedRepository.listOrganizeRuns(sharedContext).map { runs ->
            OrganizeRunsSnapshot(runs.map { run ->
                OrganizeRunSummary(
                    run.id, run.trigger, run.status, run.queuedCount, run.completedCount, run.reviewCount,
                    run.failedCount, run.startedAt, run.finishedAt,
                )
            })
        }
        AdministrativeSettingsRoute.RecognitionPolicy -> loadRecognitionPolicy()
        AdministrativeSettingsRoute.Duplicates -> sharedRepository.listDuplicateGroups(sharedContext, 1, 100).map { page ->
            DuplicatesSnapshot(page.groups.map { group ->
                val first = group.works.firstOrNull()
                DuplicateGroup(
                    group.id, first?.title.orEmpty(), first?.author.orEmpty(), (group.confidence * 100).roundToInt(),
                    group.works.map { DuplicateVersion(it.id, it.title, it.author) },
                )
            })
        }
        AdministrativeSettingsRoute.LibraryOperations -> sharedRepository.listLibraryOperations(sharedContext).map { operations ->
            LibraryOperationsSnapshot(operations.map { it.toLocal() })
        }
        is AdministrativeSettingsRoute.CategoryGovernance -> sharedRepository.listCategories(
            sharedContext,
            SharedCategoryFilter(route.kind.toShared(), pageSize = 100),
        ).map { page ->
            CategoryGovernanceSnapshot(route.kind, page.categories.map { CategoryEntry(it.id, it.name, it.aliases, it.bookCount, false) })
        }
        AdministrativeSettingsRoute.MetadataProviders -> sharedRepository.loadMetadataProviders(sharedContext).map { result ->
            MetadataProvidersSnapshot(result.providers.map(SharedProvider::toLocal), result.pipelines.joinToString(" · ") { it.mediaKind.wireValue })
        }
        is AdministrativeSettingsRoute.MetadataProviderEdit -> sharedRepository.loadMetadataProvider(sharedContext, route.providerId).map { it.toEditor() }
        is AdministrativeSettingsRoute.MetadataPipeline -> sharedRepository.loadMetadataProviders(sharedContext).map { result ->
            val pipeline = result.pipelines.firstOrNull { it.mediaKind == route.mediaKind.toShared() }
            MetadataPipelineSnapshot(pipeline?.providers.orEmpty().sortedBy { it.position }.map { MetadataPipelineStep(it.providerId, it.name, it.enabled) })
        }
        AdministrativeSettingsRoute.Opds -> sharedRepository.loadOpdsSettings(sharedContext).map {
            OpdsSnapshot(it.enabled, it.configured, it.publicBaseUrl.orEmpty(), it.catalogUrl.orEmpty())
        }
        AdministrativeSettingsRoute.Backups -> sharedRepository.listBackups(sharedContext).map { archives ->
            BackupsSnapshot(archives.map { archive ->
                BackupRecord(
                    archive.id, archive.fileName ?: archive.name, archive.kind.equals("automatic", true), bytesLabel(archive.sizeBytes),
                    archive.createdAt, archive.counts["works"] ?: 0, archive.counts["progress"] ?: 0,
                    archive.counts["monitor_folders"] ?: archive.counts["sources"] ?: 0,
                )
            })
        }
        AdministrativeSettingsRoute.DetailOrder -> sharedRepository.loadWorkDetailTabOrder(sharedContext).map { order ->
            DetailOrderSnapshot(order.tabs.map { DetailSection(it.wireValue, it.wireValue) })
        }
        is AdministrativeSettingsRoute.Health -> loadHealth(route.runId)
        AdministrativeSettingsRoute.Logs -> loadLogs()
    }

    override suspend fun execute(
        context: AdministrativeSettingsContext,
        command: AdministrativeCommand,
    ): AdministrativeResult<AdministrativeCommandReceipt> = when (command) {
        is AdministrativeCommand.SaveKindle -> sharedRepository.updateKindleEmail(sharedContext, command.settings.recipient).receipt(command)
        is AdministrativeCommand.SaveSmtp -> sharedRepository.updateEmailSettings(sharedContext, command.settings.toShared()).receipt(command)
        is AdministrativeCommand.TestSmtp -> sharedRepository.testSmtp(sharedContext, command.settings.toShared()).receipt(command)
        is AdministrativeCommand.CancelKindleTask -> sharedRepository.cancelKindleTask(sharedContext, command.taskId).receipt(command)
        is AdministrativeCommand.RetryKindleTask -> sharedRepository.retryKindleTask(sharedContext, command.taskId).receipt(command)
        is AdministrativeCommand.DeleteKindleTask -> sharedRepository.deleteKindleTask(sharedContext, command.taskId).receipt(command)
        is AdministrativeCommand.SaveUser -> saveUser(command)
        is AdministrativeCommand.SaveUserAccess -> updateUserAccess(command)
        is AdministrativeCommand.ResetUserPassword -> sharedRepository.resetUserPassword(sharedContext, command.userId, command.newPassword).receipt(command)
        is AdministrativeCommand.SetUserEnabled -> updateUserEnabled(command)
        is AdministrativeCommand.DeleteUser -> deleteUser(command)
        is AdministrativeCommand.SaveLibrarySource -> saveLibrarySource(command)
        is AdministrativeCommand.DeleteLibrarySource -> sharedRepository.deleteMonitorFolder(sharedContext, command.sourceId).receipt(command)
        is AdministrativeCommand.RescanLibrarySource -> rescanLibrarySource(command)
        is AdministrativeCommand.ScanDirectory -> sharedRepository.scanDirectory(sharedContext, command.directory.uri).receipt(command)
        is AdministrativeCommand.RetryImportTask -> sharedRepository.retryImportTask(sharedContext, command.taskId).receipt(command)
        is AdministrativeCommand.DeleteImportTask -> sharedRepository.deleteImportTask(sharedContext, command.taskId, SharedImportDeleteMode.Record, false).receipt(command)
        is AdministrativeCommand.CancelImportScan -> sharedRepository.cancelImportScanJob(sharedContext, command.jobId).receipt(command)
        AdministrativeCommand.RescanAllSources -> sharedRepository.rescanImportFolders(sharedContext).receipt(command)
        AdministrativeCommand.ClearCompletedImports -> sharedRepository.clearCompletedImportTasks(sharedContext).receipt(command)
        is AdministrativeCommand.SaveImportPreferences -> sharedRepository.updateImportPreferences(sharedContext, command.preferences.toShared()).receipt(command)
        is AdministrativeCommand.StartRecognition -> sharedRepository.recognizeOrganizeJob(sharedContext, command.taskId).receipt(command)
        is AdministrativeCommand.DeleteOrganizeTask -> sharedRepository.deleteOrganizeJob(sharedContext, command.taskId).receipt(command)
        is AdministrativeCommand.SaveRecognitionPolicy -> saveRecognitionPolicy(command)
        is AdministrativeCommand.MergeDuplicates -> mergeDuplicates(command)
        is AdministrativeCommand.MergeCategories -> sharedRepository.mergeCategories(
            sharedContext, command.kind.toShared(), command.targetId, command.sourceIds.toList(),
        ).receipt(command)
        is AdministrativeCommand.RenameCategory -> sharedRepository.renameCategory(sharedContext, command.categoryId, command.name).receipt(command)
        is AdministrativeCommand.DeleteCategory -> sharedRepository.deleteCategory(sharedContext, command.categoryId).receipt(command)
        is AdministrativeCommand.UndoLibraryOperation -> sharedRepository.undoLibraryOperation(sharedContext, command.operationId).receipt(command)
        is AdministrativeCommand.SaveMetadataProviders -> saveMetadataProviders(command)
        is AdministrativeCommand.SaveMetadataProvider -> sharedRepository.updateMetadataProvider(
            sharedContext, command.draft.id, command.draft.toShared(),
        ).receipt(command)
        is AdministrativeCommand.TestMetadataProvider -> sharedRepository.testMetadataProvider(sharedContext, command.providerId).receipt(command)
        is AdministrativeCommand.SaveMetadataPipeline -> sharedRepository.updateMetadataPipeline(
            sharedContext, command.mediaKind.toShared(), command.steps.map { SharedPipelineEntry(it.id, it.enabled) },
        ).receipt(command)
        is AdministrativeCommand.SaveOpds -> sharedRepository.updateOpdsSettings(sharedContext, command.enabled, command.publicBaseUrl.ifBlank { null }).receipt(command)
        AdministrativeCommand.CreateBackup -> sharedRepository.createBackup(sharedContext).receipt(command)
        is AdministrativeCommand.DownloadBackup -> sharedRepository.downloadBackup(sharedContext, command.backupId, maximumBackupBytes).map { file ->
            AdministrativeCommandReceipt(setOf(command.ownerRoute), AdministrativeExportFile(file.fileName, file.contentType, file.bytes))
        }
        is AdministrativeCommand.RestoreBackup -> {
            if (command.confirmation != SharedRestoreConfirmation.Restore.wireValue) validationFailure("INVALID_RESTORE_CONFIRMATION")
            else sharedRepository.restoreBackup(sharedContext, command.backupId, SharedRestoreConfirmation.Restore).receipt(command)
        }
        is AdministrativeCommand.DeleteBackup -> sharedRepository.deleteBackup(sharedContext, command.backupId).receipt(command)
        is AdministrativeCommand.SaveDetailOrder -> {
            val tabs = command.sectionIds.mapNotNull { id -> SharedDetailTab.entries.firstOrNull { it.wireValue == id } }
            if (tabs.size != command.sectionIds.size || tabs.toSet().size != SharedDetailTab.entries.size) validationFailure("INVALID_DETAIL_ORDER")
            else sharedRepository.updateWorkDetailTabOrder(sharedContext, SharedDetailOrder(tabs)).receipt(command)
        }
        AdministrativeCommand.RunHealthCheck -> sharedRepository.startHealthRun(sharedContext).map { run ->
            currentHealthRun = run
            AdministrativeCommandReceipt(setOf(AdministrativeSettingsRoute.Health(run.runId)))
        }
        AdministrativeCommand.RestartImportQueue -> sharedRepository.restartImportQueue(sharedContext).map { operation ->
            currentQueueOperationId = operation.id
            AdministrativeCommandReceipt(setOf(command.ownerRoute))
        }
        is AdministrativeCommand.SaveLogCapacity -> sharedRepository.updateLogCapacity(sharedContext, command.megabytes.toLong() * 1024L * 1024L).receipt(command)
        is AdministrativeCommand.ExportLogs -> exportLogs(command)
        AdministrativeCommand.ClearInformationalLogs -> sharedRepository.clearManagementEvents(sharedContext).receipt(command)
    }

    private suspend fun loadEmailKindle(
        context: AdministrativeSettingsContext,
        route: AdministrativeSettingsRoute.EmailKindle,
    ): AdministrativeResult<AdministrativePageSnapshot> {
        val kindle = when (val result = sharedRepository.loadKindleSettings(sharedContext)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        val canManageSmtp = AdministrativeCapability.ManageSystem in context.capabilities
        val smtp = if (canManageSmtp) {
            when (val result = sharedRepository.loadEmailSettings(sharedContext)) {
                is SharedContent -> result.value.smtp.toLocal()
                is SharedFailure -> return result.toLocalFailure()
            }
        } else null
        if (route.tab == EmailKindleTab.Smtp && smtp == null) return forbidden("SMTP_ADMIN_REQUIRED")
        return AdministrativeResult.Content(
            EmailKindleSnapshot(KindleSettings(kindle.recipientEmail, kindle.smtpConfigured, kindle.senderEmail), smtp, canManageSmtp),
        )
    }

    private suspend fun loadUserEditor(route: AdministrativeSettingsRoute.UserEdit): AdministrativeResult<AdministrativePageSnapshot> {
        if (route.userId == null) return AdministrativeResult.Content(UserEditorSnapshot(null, false, false, emptySet()))
        return sharedRepository.loadUser(sharedContext, route.userId).map { user ->
            UserEditorSnapshot(user.toLocal(), user.canManageSystem, user.canViewManualImports, user.monitorFolderIds.toSet())
        }
    }

    private suspend fun loadUserAccess(userId: String): AdministrativeResult<AdministrativePageSnapshot> {
        val user = when (val result = sharedRepository.loadUser(sharedContext, userId)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        return sharedRepository.loadMonitorFolders(sharedContext).map { folders ->
            UserAccessSnapshot(
                user.toLocal(), user.role == SharedUserRole.Admin, user.canViewManualImports,
                folders.folders.map { AccessSource(it.id, it.name, it.rootPath, null, it.id in user.monitorFolderIds) },
            )
        }
    }

    private suspend fun loadLibrarySourceEditor(sourceId: String?): AdministrativeResult<AdministrativePageSnapshot> =
        sharedRepository.loadMonitorFolders(sharedContext).map { result ->
            val source = sourceId?.let { id -> result.folders.firstOrNull { it.id == id } }
            LibrarySourceEditorSnapshot(source?.toLocal(), source?.ignorePatterns.orEmpty(), source?.ignoreHidden ?: true, source?.minimumFileSizeBytes ?: 0L)
        }

    private suspend fun loadRecognitionPolicy(): AdministrativeResult<AdministrativePageSnapshot> {
        val policy = when (val result = sharedRepository.loadOrganizePolicy(sharedContext)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        return sharedRepository.loadOpfQueueStatus(sharedContext).map { opf ->
            RecognitionPolicySnapshot(
                policy.scheduleMode == SharedScheduleMode.Interval, (policy.intervalMinutes / 60).coerceAtLeast(1), policy.autoRunOnNew,
                policy.writeMetadataToFiles, opf.capacity - opf.pendingTargets, opf.capacity, policy.preferLocalMetadata,
                policy.localMetadataPriority.map { it.toLocal() }, policy.rules.unrecognized, policy.rules.missingMetadata,
            )
        }
    }

    private suspend fun loadImportTaskDetail(taskId: String): AdministrativeResult<AdministrativePageSnapshot> {
        val task = when (val result = sharedRepository.loadImportTask(sharedContext, taskId)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        return sharedRepository.listImportTaskLogs(sharedContext, taskId).map { page ->
            ImportTaskDetailSnapshot(
                task = task.toLocal(),
                requestedTitle = task.requestedTitle,
                requestedAuthor = task.requestedAuthor,
                processedAssetCount = task.processedAssetCount,
                assetCount = task.assetCount,
                attempts = task.attempts,
                retryable = task.retryable,
                errorSummary = task.errorSummary,
                logs = page.logs.map { ImportTaskLogEntry(it.id, it.level, it.message, it.createdAt) },
            )
        }
    }

    private suspend fun loadHealth(runId: String?): AdministrativeResult<AdministrativePageSnapshot> {
        val run = when {
            runId != null -> when (val result = sharedRepository.loadHealthRun(sharedContext, runId)) {
                is SharedContent -> result.value.also { currentHealthRun = it }
                is SharedFailure -> return result.toLocalFailure()
            }
            else -> currentHealthRun
        }
        val operation = currentQueueOperationId?.let { operationId ->
            when (val result = sharedRepository.loadQueueOperation(sharedContext, operationId)) {
                is SharedContent -> result.value
                is SharedFailure -> return result.toLocalFailure()
            }
        }
        if (run == null) {
            return AdministrativeResult.Content(
                HealthSnapshot(
                    null, null, null, 0, 0, emptyList(), operation?.status.isActiveQueueStatus(),
                    operation?.id, operation?.status, operation?.messageCode,
                ),
            )
        }
        return AdministrativeResult.Content(run.toLocal(operation?.id, operation?.status, operation?.messageCode))
    }

    private suspend fun loadLogs(): AdministrativeResult<AdministrativePageSnapshot> {
        val page = when (val result = sharedRepository.listManagementEvents(sharedContext, SharedEventFilter(pageSize = 100))) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        return AdministrativeResult.Content(
            LogsSnapshot(
                LogQuery(), (page.storage.sizeBytes / 1_048_576L).toInt(), (page.storage.maximumBytes / 1_048_576L).toInt(),
                page.events.map { event ->
                    LogRecord(event.id, event.createdAt.orEmpty(), event.level.toLogLevel(), event.source, event.message, event.metadata["correlation_id"], event.targetId)
                },
            ),
        )
    }

    private suspend fun saveUser(command: AdministrativeCommand.SaveUser): AdministrativeResult<AdministrativeCommandReceipt> {
        val draft = command.draft
        return if (draft.id == null) {
            val password = draft.initialPassword ?: return validationFailure("PASSWORD_REQUIRED")
            sharedRepository.createUser(
                sharedContext,
                SharedCreateUser(
                    draft.displayName, draft.email, password, draft.role.toShared(), draft.canManageSystem,
                    draft.canViewManualImports, draft.sourceIds.toList(), draft.locale.toShared(),
                ),
            ).receipt(command)
        } else {
            sharedRepository.updateUser(sharedContext, draft.id, draft.toSharedUpdate()).receipt(command)
        }
    }

    private suspend fun updateUserAccess(command: AdministrativeCommand.SaveUserAccess): AdministrativeResult<AdministrativeCommandReceipt> {
        val user = when (val result = sharedRepository.loadUser(sharedContext, command.userId)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        val folderIds = if (command.allLibraries && user.role != SharedUserRole.Admin) return validationFailure("MEMBER_REQUIRES_EXPLICIT_SCOPE") else command.sourceIds.toList()
        return sharedRepository.updateUser(sharedContext, user.id, user.toUpdate(monitorFolderIds = folderIds)).receipt(command)
    }

    private suspend fun updateUserEnabled(command: AdministrativeCommand.SetUserEnabled): AdministrativeResult<AdministrativeCommandReceipt> {
        val user = when (val result = sharedRepository.loadUser(sharedContext, command.userId)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        return sharedRepository.updateUser(sharedContext, user.id, user.toUpdate(status = if (command.enabled) SharedUserStatus.Active else SharedUserStatus.Disabled)).receipt(command)
    }

    private suspend fun deleteUser(command: AdministrativeCommand.DeleteUser): AdministrativeResult<AdministrativeCommandReceipt> {
        val user = when (val result = sharedRepository.loadUser(sharedContext, command.userId)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        return sharedRepository.deleteUser(sharedContext, user.id, user.email).receipt(command)
    }

    private suspend fun saveLibrarySource(command: AdministrativeCommand.SaveLibrarySource): AdministrativeResult<AdministrativeCommandReceipt> {
        val draft = command.draft.toShared()
        return if (command.draft.id == null) sharedRepository.createMonitorFolder(sharedContext, draft).receipt(command)
        else sharedRepository.updateMonitorFolder(sharedContext, command.draft.id, draft).receipt(command)
    }

    private suspend fun rescanLibrarySource(command: AdministrativeCommand.RescanLibrarySource): AdministrativeResult<AdministrativeCommandReceipt> {
        val folders = when (val result = sharedRepository.loadMonitorFolders(sharedContext)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        val path = folders.folders.firstOrNull { it.id == command.sourceId }?.rootPath ?: return notFound("MONITOR_FOLDER_NOT_FOUND")
        return sharedRepository.scanDirectory(sharedContext, path).receipt(command)
    }

    private suspend fun saveRecognitionPolicy(command: AdministrativeCommand.SaveRecognitionPolicy): AdministrativeResult<AdministrativeCommandReceipt> {
        val current = when (val result = sharedRepository.loadOrganizePolicy(sharedContext)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        val draft = command.policy
        val updated = current.copy(
            enabled = draft.scheduled || draft.runAfterImport,
            scheduleMode = if (draft.scheduled) SharedScheduleMode.Interval else SharedScheduleMode.Manual,
            intervalMinutes = draft.intervalHours * 60,
            autoRunOnNew = draft.runAfterImport,
            rules = SharedOrganizeRules(draft.includeUnrecognized, draft.includeMissingAuthorOrCover),
            writeMetadataToFiles = draft.saveMetadataToOpf,
            preferLocalMetadata = draft.localMetadataFirst,
            localMetadataPriority = draft.sourcePriority.mapNotNull { it.toSharedLocal() },
        )
        return sharedRepository.updateOrganizePolicy(sharedContext, updated).receipt(command)
    }

    private suspend fun mergeDuplicates(command: AdministrativeCommand.MergeDuplicates): AdministrativeResult<AdministrativeCommandReceipt> {
        val page = when (val result = sharedRepository.listDuplicateGroups(sharedContext, 1, 100)) {
            is SharedContent -> result.value
            is SharedFailure -> return result.toLocalFailure()
        }
        val group = page.groups.firstOrNull { it.id == command.groupId } ?: return notFound("DUPLICATE_GROUP_NOT_FOUND")
        if (group.works.none { it.id == command.canonicalWorkId }) return validationFailure("CANONICAL_WORK_NOT_IN_GROUP")
        return sharedRepository.mergeDuplicateWorks(sharedContext, command.canonicalWorkId, group.works.map { it.id }.filter { it != command.canonicalWorkId }).receipt(command)
    }

    private suspend fun saveMetadataProviders(command: AdministrativeCommand.SaveMetadataProviders): AdministrativeResult<AdministrativeCommandReceipt> {
        for (provider in command.providers) {
            val existing = when (val result = sharedRepository.loadMetadataProvider(sharedContext, provider.id)) {
                is SharedContent -> result.value
                is SharedFailure -> return result.toLocalFailure()
            }
            when (val result = sharedRepository.updateMetadataProvider(
                sharedContext, provider.id, SharedProviderUpdate(provider.enabled, provider.priority, existing.config, emptyList()),
            )) {
                is SharedContent -> Unit
                is SharedFailure -> return result.toLocalFailure()
            }
        }
        return AdministrativeResult.Content(AdministrativeCommandReceipt(setOf(command.ownerRoute)))
    }

    private suspend fun exportLogs(command: AdministrativeCommand.ExportLogs): AdministrativeResult<AdministrativeCommandReceipt> {
        val filter = command.query.toShared()
        return sharedRepository.loadAllManagementEventsForExport(sharedContext, filter).map { events ->
            val csv = buildString {
                appendLine("id,timestamp,level,source,action,target_type,target_id,message")
                events.forEach { event ->
                    appendLine(listOf(event.id, event.createdAt.orEmpty(), event.level, event.source, event.action, event.targetType.orEmpty(), event.targetId.orEmpty(), event.message).joinToString(",", transform = ::csv))
                }
            }
            AdministrativeCommandReceipt(setOf(command.ownerRoute), AdministrativeExportFile("ermao-management-events.csv", "text/csv", csv.encodeToByteArray()))
        }
    }
}

private fun managementSnapshot(capabilities: Set<AdministrativeCapability>): ManagementSnapshot {
    val routes = listOf(
        AdministrativeSettingsRoute.LibrarySources, AdministrativeSettingsRoute.ImportTasks, AdministrativeSettingsRoute.ImportPreferences,
        AdministrativeSettingsRoute.OrganizeQueue, AdministrativeSettingsRoute.RecognitionPolicy, AdministrativeSettingsRoute.Duplicates,
        AdministrativeSettingsRoute.CategoryGovernance(), AdministrativeSettingsRoute.MetadataProviders, AdministrativeSettingsRoute.Users,
        AdministrativeSettingsRoute.EmailKindle(), AdministrativeSettingsRoute.KindleQueue, AdministrativeSettingsRoute.Opds,
        AdministrativeSettingsRoute.Backups, AdministrativeSettingsRoute.DetailOrder, AdministrativeSettingsRoute.Health(), AdministrativeSettingsRoute.Logs,
    )
    return ManagementSnapshot(routes.filter { it.requiredCapability() in capabilities }.map(::ManagementEntry))
}

private inline fun <T, R> SharedResult<T>.map(transform: (T) -> R): AdministrativeResult<R> = when (this) {
    is SharedContent -> AdministrativeResult.Content(transform(value))
    is SharedFailure -> toLocalFailure()
}

private fun <T> SharedResult<T>.receipt(command: AdministrativeCommand): AdministrativeResult<AdministrativeCommandReceipt> =
    map { AdministrativeCommandReceipt(setOf(command.ownerRoute)) }

private fun SharedFailure.toLocalFailure(): AdministrativeResult.Failure = AdministrativeResult.Failure(error.toLocal())

private fun SharedError.toLocal() = AdministrativeFailure(
    kind = when (kind) {
        SharedErrorKind.Validation -> AdministrativeErrorKind.Validation
        SharedErrorKind.Unauthorized -> AdministrativeErrorKind.Unauthorized
        SharedErrorKind.Forbidden -> AdministrativeErrorKind.Forbidden
        SharedErrorKind.NotFound -> AdministrativeErrorKind.NotFound
        SharedErrorKind.Conflict -> AdministrativeErrorKind.Conflict
        SharedErrorKind.RateLimited -> AdministrativeErrorKind.RateLimited
        SharedErrorKind.Server, SharedErrorKind.Transport -> AdministrativeErrorKind.Unavailable
        SharedErrorKind.Protocol -> AdministrativeErrorKind.Unknown
        SharedErrorKind.Stale -> AdministrativeErrorKind.Cancelled
    },
    code = code,
    fieldCodes = fieldViolations.associate { it.field to it.code },
    retryable = kind in setOf(SharedErrorKind.Server, SharedErrorKind.Transport, SharedErrorKind.RateLimited),
)

private fun validationFailure(code: String): AdministrativeResult.Failure = AdministrativeResult.Failure(AdministrativeFailure(AdministrativeErrorKind.Validation, code))
private fun forbidden(code: String): AdministrativeResult.Failure = AdministrativeResult.Failure(AdministrativeFailure(AdministrativeErrorKind.Forbidden, code))
private fun notFound(code: String): AdministrativeResult.Failure = AdministrativeResult.Failure(AdministrativeFailure(AdministrativeErrorKind.NotFound, code))

private fun com.ermao.library.shared.modules.administrativesettings.KindleTaskStatus.toLocal(): QueueStatus = when (this) {
    SharedKindleTaskStatus.Queued -> QueueStatus.Queued
    SharedKindleTaskStatus.Sending -> QueueStatus.Running
    SharedKindleTaskStatus.Sent -> QueueStatus.Completed
    SharedKindleTaskStatus.Failed, SharedKindleTaskStatus.Unknown -> QueueStatus.Failed
    SharedKindleTaskStatus.Cancelled -> QueueStatus.Cancelled
}

private fun SharedImportTaskStatus.toLocal(): QueueStatus = when (this) {
    SharedImportTaskStatus.Pending -> QueueStatus.Queued
    SharedImportTaskStatus.Parsing -> QueueStatus.Running
    SharedImportTaskStatus.Completed -> QueueStatus.Completed
    SharedImportTaskStatus.Failed -> QueueStatus.Failed
}

private fun com.ermao.library.shared.modules.administrativesettings.ImportTask.toLocal() = ImportTask(
    id = id,
    fileName = originalName ?: requestedTitle ?: sourcePath.substringAfterLast('/'),
    sourcePath = sourcePath,
    createdAtLabel = createdAt,
    status = status.toLocal(),
    progress = progress.coerceIn(0, 100) / 100f,
    statusCode = errorCode,
)

private fun com.ermao.library.shared.modules.administrativesettings.ImportScanJob.toLocal() = ImportScanJobSummary(
    id = id,
    rootPath = rootPath,
    status = when (status) {
        SharedImportScanStatus.Pending -> QueueStatus.Queued
        SharedImportScanStatus.Running -> QueueStatus.Running
        SharedImportScanStatus.Completed -> QueueStatus.Completed
        SharedImportScanStatus.Failed -> QueueStatus.Failed
        SharedImportScanStatus.Cancelled -> QueueStatus.Cancelled
    },
    directoriesScanned = directoriesScanned,
    filesScanned = filesScanned,
    candidatesFound = candidatesFound,
    queuedCount = queuedCount,
    skippedCount = skippedCount,
    errorCount = errorCount,
    startedAtLabel = startedAt,
    updatedAtLabel = updatedAt,
)

private fun com.ermao.library.shared.modules.administrativesettings.LibraryOperation.toLocal() = LibraryOperationSummary(
    id, action, status, summary, createdAt, expiresAt, undoAvailable,
)

private fun com.ermao.library.shared.modules.administrativesettings.OrganizeJob.toLocal() = OrganizeTask(
    id, work.title, work.author,
    when (statusCategory) {
        com.ermao.library.shared.modules.administrativesettings.OrganizeStatusCategory.Waiting -> OrganizeStatus.AwaitingRecognition
        com.ermao.library.shared.modules.administrativesettings.OrganizeStatusCategory.Recognizing -> OrganizeStatus.NeedsConfirmation
        com.ermao.library.shared.modules.administrativesettings.OrganizeStatusCategory.Success -> OrganizeStatus.Organized
        com.ermao.library.shared.modules.administrativesettings.OrganizeStatusCategory.Failed -> OrganizeStatus.Failed
    },
)

private fun SharedUser.toLocal() = AdministrativeUser(id, name, email, role.toLocal(), status == SharedUserStatus.Active, locale.toLocal())
private fun SharedUserRole.toLocal() = if (this == SharedUserRole.Admin) UserRole.Administrator else UserRole.Member
private fun UserRole.toShared() = if (this == UserRole.Administrator) SharedUserRole.Admin else SharedUserRole.Member
private fun SharedLocale.toLocal() = if (this == SharedLocale.ZhCn) AdministrativeLocale.ZhCn else AdministrativeLocale.EnUs
private fun AdministrativeLocale.toShared() = if (this == AdministrativeLocale.ZhCn) SharedLocale.ZhCn else SharedLocale.EnUs

private fun SharedUser.toUpdate(
    status: SharedUserStatus = this.status,
    monitorFolderIds: List<String> = this.monitorFolderIds,
) = SharedUpdateUser(name, email, role, status, canManageSystem, canViewManualImports, monitorFolderIds, locale)

private fun UserDraft.toSharedUpdate() = SharedUpdateUser(
    displayName, email, role.toShared(), if (enabled) SharedUserStatus.Active else SharedUserStatus.Disabled,
    canManageSystem, canViewManualImports, sourceIds.toList(), locale.toShared(),
)

private fun com.ermao.library.shared.modules.administrativesettings.MonitorFolder.toLocal() = LibrarySource(
    id, name, rootPath, enabled, mediaKindPolicy.toLocal(), description,
)

private fun SharedMediaKindPolicy.toLocal() = when (this) {
    SharedMediaKindPolicy.Mixed -> MediaKindPolicy.Mixed
    SharedMediaKindPolicy.Ebook -> MediaKindPolicy.Ebook
    SharedMediaKindPolicy.Comic -> MediaKindPolicy.Comic
    SharedMediaKindPolicy.Audiobook -> MediaKindPolicy.Audiobook
}

private fun MediaKindPolicy.toShared() = when (this) {
    MediaKindPolicy.Mixed -> SharedMediaKindPolicy.Mixed
    MediaKindPolicy.Ebook -> SharedMediaKindPolicy.Ebook
    MediaKindPolicy.Comic -> SharedMediaKindPolicy.Comic
    MediaKindPolicy.Audiobook -> SharedMediaKindPolicy.Audiobook
}

private fun LibrarySourceDraft.toShared() = SharedFolderDraft(
    directory.uri, displayName.ifBlank { null }, null, monitoring, mediaKindPolicy.toShared(), ignorePatterns.ifBlank { null },
    ignoreHidden, minimumFileSizeBytes, description,
)

private fun SharedImportPreferences.toLocal() = ImportPreferencesSnapshot(stabilityCheckEnabled, stabilitySeconds, allowedExtensions, ignorePatterns)
private fun ImportPreferencesSnapshot.toShared() = SharedImportPreferences(stabilityCheckEnabled, stabilitySeconds, allowedExtensions, ignorePatterns)

private fun SharedLocalMetadataSource.toLocal() = when (this) {
    SharedLocalMetadataSource.SidecarOpf -> MetadataSource.Opf
    SharedLocalMetadataSource.Embedded -> MetadataSource.Embedded
    SharedLocalMetadataSource.Path -> MetadataSource.PathAndFileName
}

private fun MetadataSource.toSharedLocal(): SharedLocalMetadataSource? = when (this) {
    MetadataSource.Opf -> SharedLocalMetadataSource.SidecarOpf
    MetadataSource.Embedded -> SharedLocalMetadataSource.Embedded
    MetadataSource.PathAndFileName -> SharedLocalMetadataSource.Path
    MetadataSource.Provider -> null
}

private fun CategoryKind.toShared() = when (this) {
    CategoryKind.Author -> SharedCategoryKind.Author
    CategoryKind.Tag -> SharedCategoryKind.Tag
    CategoryKind.Series -> SharedCategoryKind.Series
}

private fun SharedProvider.toLocal() = MetadataProvider(
    id, name, enabled, lastTestStatus != "failed", priority, latencyMilliseconds = null,
)

private fun SharedProvider.toEditor() = MetadataProviderEditorSnapshot(
    toLocal(),
    configFields.map { field ->
        MetadataProviderField(
            field.key, field.label, field.kind.toFieldKind(), field.required, field.secret,
            config[field.key]?.toLocal() ?: field.defaultValue.toLocal(), configuredSecrets[field.key] == true,
        )
    },
    lastTestStatus?.let { ConnectionTest(it.equals("ok", true), code = lastError) },
)

private fun String.toFieldKind() = when (lowercase()) {
    "boolean", "toggle" -> MetadataProviderFieldKind.Toggle
    "integer", "int" -> MetadataProviderFieldKind.Integer
    "decimal", "number", "float" -> MetadataProviderFieldKind.Decimal
    "list", "text_list" -> MetadataProviderFieldKind.TextList
    else -> MetadataProviderFieldKind.Text
}

private fun SharedProviderValue.toLocal(): ProviderFieldValue = when (this) {
    is SharedProviderValue.Text -> ProviderFieldValue.Text(value)
    is SharedProviderValue.Toggle -> ProviderFieldValue.Toggle(value)
    is SharedProviderValue.Integer -> ProviderFieldValue.Integer(value)
    is SharedProviderValue.Decimal -> ProviderFieldValue.Decimal(value)
    is SharedProviderValue.TextList -> ProviderFieldValue.TextList(value)
    SharedProviderValue.Empty -> ProviderFieldValue.Empty
}

private fun ProviderFieldValue.toShared(): SharedProviderValue = when (this) {
    is ProviderFieldValue.Text -> SharedProviderValue.Text(value)
    is ProviderFieldValue.Toggle -> SharedProviderValue.Toggle(value)
    is ProviderFieldValue.Integer -> SharedProviderValue.Integer(value)
    is ProviderFieldValue.Decimal -> SharedProviderValue.Decimal(value)
    is ProviderFieldValue.TextList -> SharedProviderValue.TextList(value)
    ProviderFieldValue.Empty -> SharedProviderValue.Empty
}

private fun MetadataProviderDraft.toShared() = SharedProviderUpdate(enabled, priority, fields.mapValues { it.value.toShared() }, clearSecrets.toList())

private fun MediaKind.toShared() = when (this) {
    MediaKind.Ebook -> SharedMediaKind.Ebook
    MediaKind.Comic -> SharedMediaKind.Comic
    MediaKind.Audiobook -> SharedMediaKind.Audiobook
}

private fun SmtpEncryption.toShared() = when (this) {
    SmtpEncryption.None -> SharedSmtpSecurity.None
    SmtpEncryption.StartTls -> SharedSmtpSecurity.StartTls
    SmtpEncryption.Tls -> SharedSmtpSecurity.Ssl
}

private fun SharedSmtpSecurity.toLocal() = when (this) {
    SharedSmtpSecurity.None -> SmtpEncryption.None
    SharedSmtpSecurity.StartTls -> SmtpEncryption.StartTls
    SharedSmtpSecurity.Ssl -> SmtpEncryption.Tls
}

private fun com.ermao.library.shared.modules.administrativesettings.SmtpSettings.toLocal() = SmtpSettings(
    host, port, security.toLocal(), fromEmail, username, passwordConfigured, fromName, maximumAttachmentMegabytes,
)

private fun SmtpSettingsDraft.toShared() = SharedSmtpUpdate(
    host, port, encryption.toShared(), username, newPassword, senderEmail, senderName, maximumAttachmentMegabytes, false,
)

private fun SharedHealthRun.toLocal(
    queueOperationId: String?,
    queueOperationStatus: String?,
    queueOperationMessageCode: String?,
) = HealthSnapshot(
    runId, startedAt.toString(), status.toLocal(), summary.ok, summary.total,
    items.map { item ->
        HealthCheck(item.id, item.labelCode, item.group.toHealthGroup(), item.status.toLocal(), item.messageCode)
    }, queueOperationStatus.isActiveQueueStatus(), queueOperationId, queueOperationStatus, queueOperationMessageCode,
)

private fun String?.isActiveQueueStatus(): Boolean = this?.lowercase() in setOf("pending", "queued", "running", "processing")

private fun SharedHealthRunStatus.toLocal() = when (this) {
    SharedHealthRunStatus.Running -> HealthStatus.Checking
    SharedHealthRunStatus.Completed -> HealthStatus.Healthy
    SharedHealthRunStatus.Warning -> HealthStatus.Warning
    SharedHealthRunStatus.Error, SharedHealthRunStatus.Failed -> HealthStatus.Failed
}

private fun SharedHealthCheckStatus.toLocal() = when (this) {
    SharedHealthCheckStatus.Pending, SharedHealthCheckStatus.Running -> HealthStatus.Checking
    SharedHealthCheckStatus.Ok, SharedHealthCheckStatus.Skipped -> HealthStatus.Healthy
    SharedHealthCheckStatus.Warning -> HealthStatus.Warning
    SharedHealthCheckStatus.Error -> HealthStatus.Failed
}

private fun String.toHealthGroup() = when {
    contains("queue", true) || contains("worker", true) -> HealthGroup.BackgroundQueues
    contains("database", true) || contains("storage", true) || contains("directory", true) -> HealthGroup.StorageAndDatabase
    else -> HealthGroup.FeatureConfiguration
}

private fun String.toLogLevel() = when (lowercase()) {
    "error", "critical" -> LogLevel.Error
    "warning", "warn" -> LogLevel.Warning
    else -> LogLevel.Information
}

private fun LogQuery.toShared() = SharedEventFilter(
    pageSize = 100, level = level?.name?.lowercase(), source = source, search = search.ifBlank { null },
)

private fun maskEmail(email: String): String {
    val at = email.indexOf('@')
    if (at <= 1) return email
    return email.take(1) + "***" + email.drop(at)
}

private fun bytesLabel(bytes: Long): String = when {
    bytes >= 1_073_741_824L -> "%.1f GB".format(bytes / 1_073_741_824.0)
    bytes >= 1_048_576L -> "%.1f MB".format(bytes / 1_048_576.0)
    else -> "$bytes B"
}

private fun csv(value: String): String = "\"${value.replace("\"", "\"\"")}\""
