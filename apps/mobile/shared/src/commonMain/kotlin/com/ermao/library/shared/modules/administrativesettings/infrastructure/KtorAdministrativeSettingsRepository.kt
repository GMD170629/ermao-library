package com.ermao.library.shared.modules.administrativesettings.infrastructure

import com.ermao.library.shared.core.network.*
import com.ermao.library.shared.modules.administrativesettings.application.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.domain.*
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.http.encodeURLPathPart
import io.ktor.http.decodeURLPart
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal class KtorAdministrativeSettingsRepository(
    private val clientProvider: (ServerProfile) -> ApiClient,
) : AdministrativeSettingsRepository {
    constructor(clients: ApiClientFactory) : this(clients::create)

    private val freshnessMutex = Mutex()
    private var responseGeneration = 0L

    override suspend fun invalidatePendingResponses() {
        freshnessMutex.withLock { responseGeneration += 1L }
    }

    override suspend fun loadKindleSettings(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/kindle-settings", transform = JsonElement::toKindleSettings)

    override suspend fun updateKindleEmail(context: AdministrativeSettingsContext, email: String): AdministrativeSettingsResult<KindleSettings> {
        val normalized = email.trim()
        if (normalized.isNotEmpty() && !normalized.looksLikeEmail()) return invalid("INVALID_KINDLE_EMAIL", "email")
        return call(
            context,
            ApiMethod.Put,
            "/api/kindle-settings",
            body = buildJsonObject { put("email", normalized) },
            transform = JsonElement::toKindleSettings,
        )
    }

    override suspend fun listKindleTasks(context: AdministrativeSettingsContext, filter: KindleTaskFilter): AdministrativeSettingsResult<KindleTaskPage> {
        validatePage(filter.page, filter.pageSize, 200)?.let { return it }
        return call(
            context,
            ApiMethod.Get,
            "/api/kindle-send-tasks",
            query = queryOf(
                "status" to filter.status?.wireValue,
                "page" to filter.page.toString(),
                "pageSize" to filter.pageSize.toString(),
            ),
            transform = JsonElement::toKindleTaskPage,
        )
    }

    override suspend fun createKindleTask(context: AdministrativeSettingsContext, fileId: String, workId: String?): AdministrativeSettingsResult<KindleTask> {
        if (fileId.isBlank()) return invalid("INVALID_FILE_ID", "fileId")
        return call(
            context,
            ApiMethod.Post,
            "/api/kindle-send-tasks",
            body = buildJsonObject {
                put("fileId", fileId.trim())
                workId?.trim()?.takeIf(String::isNotEmpty)?.let { put("workId", it) }
            },
            transform = JsonElement::toKindleTaskPayload,
        )
    }

    override suspend fun cancelKindleTask(context: AdministrativeSettingsContext, taskId: String) =
        idCall(context, ApiMethod.Post, "/api/kindle-send-tasks", taskId, "/cancel", JsonElement::toKindleTaskPayload)

    override suspend fun retryKindleTask(context: AdministrativeSettingsContext, taskId: String) =
        idCall(context, ApiMethod.Post, "/api/kindle-send-tasks", taskId, "/retry", JsonElement::toKindleTaskPayload)

    override suspend fun deleteKindleTask(context: AdministrativeSettingsContext, taskId: String) =
        idCall(context, ApiMethod.Delete, "/api/kindle-send-tasks", taskId, transform = { it.toDeletedFlag(taskId) })

    override suspend fun loadEmailSettings(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/email-settings", transform = JsonElement::toEmailSettings)

    override suspend fun updateEmailSettings(context: AdministrativeSettingsContext, update: SmtpSettingsUpdate): AdministrativeSettingsResult<EmailSettings> {
        validateSmtp(update)?.let { return it }
        return call(context, ApiMethod.Put, "/api/email-settings", body = smtpRequest(update), transform = JsonElement::toEmailSettings)
    }

    override suspend fun testSmtp(context: AdministrativeSettingsContext, update: SmtpSettingsUpdate): AdministrativeSettingsResult<SmtpTestResult> {
        validateSmtp(update)?.let { return it }
        return call(context, ApiMethod.Post, "/api/email-settings/smtp-test", body = smtpRequest(update), transform = JsonElement::toSmtpTestResult)
    }

    override suspend fun listUsers(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/admin/users", transform = JsonElement::toManagedUsers)

    override suspend fun loadUser(context: AdministrativeSettingsContext, userId: String) =
        idCall(context, ApiMethod.Get, "/api/admin/users", userId, transform = JsonElement::toManagedUserPayload)

    override suspend fun createUser(context: AdministrativeSettingsContext, user: CreateManagedUser): AdministrativeSettingsResult<ManagedUser> {
        validateUser(user.name, user.email, user.password)?.let { return it }
        return call(context, ApiMethod.Post, "/api/admin/users", body = user.toRequest(), transform = JsonElement::toManagedUserPayload)
    }

    override suspend fun updateUser(context: AdministrativeSettingsContext, userId: String, user: UpdateManagedUser): AdministrativeSettingsResult<ManagedUser> {
        validateUser(user.name, user.email)?.let { return it }
        return idCall(context, ApiMethod.Patch, "/api/admin/users", userId, body = user.toRequest(), transform = JsonElement::toManagedUserPayload)
    }

    override suspend fun resetUserPassword(context: AdministrativeSettingsContext, userId: String, password: String): AdministrativeSettingsResult<ManagedPasswordChange> {
        if (password.length !in 10..128) return invalid("INVALID_PASSWORD", "password")
        return idCall(
            context,
            ApiMethod.Put,
            "/api/admin/users",
            userId,
            suffix = "/password",
            body = buildJsonObject { put("password", password) },
            transform = JsonElement::toManagedPasswordChange,
        )
    }

    override suspend fun deleteUser(context: AdministrativeSettingsContext, userId: String, confirmation: String): AdministrativeSettingsResult<DeletedManagedUser> {
        if (confirmation.isBlank() || confirmation.length > 191) return invalid("INVALID_CONFIRMATION", "confirmation")
        return idCall(
            context,
            ApiMethod.Delete,
            "/api/admin/users",
            userId,
            body = buildJsonObject { put("confirmation", confirmation) },
            transform = JsonElement::toDeletedManagedUser,
        )
    }

    override suspend fun loadLibraries(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/libraries", transform = JsonElement::toLibraries)

    override suspend fun createLibrary(context: AdministrativeSettingsContext, library: LibraryDraft): AdministrativeSettingsResult<Library> {
        validateLibrary(library)?.let { return it }
        return call(context, ApiMethod.Post, "/api/libraries", body = library.toRequest(), transform = JsonElement::toLibraryPayload)
    }

    override suspend fun updateLibrary(context: AdministrativeSettingsContext, libraryId: String, library: LibraryDraft): AdministrativeSettingsResult<Library> {
        validateLibrary(library)?.let { return it }
        return idCall(context, ApiMethod.Patch, "/api/libraries", libraryId, body = library.toRequest(), transform = JsonElement::toLibraryPayload)
    }

    override suspend fun deleteLibrary(context: AdministrativeSettingsContext, libraryId: String) =
        idCall(context, ApiMethod.Delete, "/api/libraries", libraryId, transform = { it.toDeletedFlag(libraryId) })

    override suspend fun loadDirectory(context: AdministrativeSettingsContext, path: String?) =
        call(
            context,
            ApiMethod.Get,
            "/api/libraries/tree",
            query = queryOf("path" to path?.trim()?.takeIf(String::isNotEmpty)),
            transform = JsonElement::toDirectoryNode,
        )

    override suspend fun listImportTasks(context: AdministrativeSettingsContext, filter: ImportTaskFilter): AdministrativeSettingsResult<ImportTaskPage> {
        validatePage(filter.page, filter.pageSize, 100)?.let { return it }
        return call(
            context,
            ApiMethod.Get,
            "/api/import-tasks",
            query = queryOf(
                "page" to filter.page.toString(),
                "pageSize" to filter.pageSize.toString(),
                "status" to filter.status?.wireValue,
                "keyword" to filter.keyword?.trim()?.takeIf(String::isNotEmpty),
            ),
            transform = JsonElement::toImportTaskPage,
        )
    }

    override suspend fun loadImportTask(context: AdministrativeSettingsContext, taskId: String) =
        idCall(context, ApiMethod.Get, "/api/import-tasks", taskId, transform = JsonElement::toImportTaskPayload)

    override suspend fun listImportTaskLogs(
        context: AdministrativeSettingsContext,
        taskId: String,
        page: Int,
        pageSize: Int,
    ): AdministrativeSettingsResult<ImportTaskLogPage> {
        if (taskId.isBlank()) return invalid("INVALID_ID", "taskId")
        validatePage(page, pageSize, 100)?.let { return it }
        return call(
            context,
            ApiMethod.Get,
            "/api/import-tasks/${taskId.encodeURLPathPart()}/logs",
            query = queryOf("page" to page.toString(), "pageSize" to pageSize.toString()),
            transform = JsonElement::toImportTaskLogPage,
        )
    }

    override suspend fun retryImportTask(context: AdministrativeSettingsContext, taskId: String) =
        idCall(context, ApiMethod.Post, "/api/import-tasks", taskId, "/retry", JsonElement::toImportTaskPayload)

    override suspend fun deleteImportTask(
        context: AdministrativeSettingsContext,
        taskId: String,
    ) = idCall(
        context,
        ApiMethod.Delete,
        "/api/import-tasks",
        taskId,
        transform = JsonElement::toImportTaskDeletion,
    )

    override suspend fun clearCompletedImportTasks(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Delete, "/api/import-tasks", transform = JsonElement::toDeletedCount)

    override suspend fun clearImportQueue(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Post, "/api/import-tasks/clear", transform = JsonElement::toQueueOperationPayload)

    override suspend fun rescanImportFolders(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Post, "/api/import-tasks/rescan", transform = JsonElement::toImportRescanRequest)

    override suspend fun scanDirectory(context: AdministrativeSettingsContext, path: String): AdministrativeSettingsResult<ImportScanJob> {
        if (path.isBlank()) return invalid("INVALID_DIRECTORY", "path")
        return call(
            context,
            ApiMethod.Post,
            "/api/import-tasks/scan-directory",
            body = buildJsonObject { put("path", path.trim()) },
            transform = JsonElement::toImportScanJobPayload,
        )
    }

    override suspend fun listImportScanJobs(context: AdministrativeSettingsContext, status: ImportScanStatus?) =
        call(
            context,
            ApiMethod.Get,
            "/api/import-scan-jobs",
            query = queryOf("status" to status?.wireValue),
            transform = JsonElement::toImportScanJobs,
        )

    override suspend fun loadImportScanJob(context: AdministrativeSettingsContext, jobId: String) =
        idCall(context, ApiMethod.Get, "/api/import-scan-jobs", jobId, transform = JsonElement::toImportScanJobPayload)

    override suspend fun cancelImportScanJob(context: AdministrativeSettingsContext, jobId: String) =
        idCall(context, ApiMethod.Post, "/api/import-scan-jobs", jobId, "/cancel", JsonElement::toImportScanJobPayload)

    override suspend fun loadImportPreferences(context: AdministrativeSettingsContext): AdministrativeSettingsResult<ImportPreferences> =
        mapSettingsResult(loadSystemSettings(context), ::importPreferencesFrom)

    override suspend fun updateImportPreferences(
        context: AdministrativeSettingsContext,
        preferences: ImportPreferences,
    ): AdministrativeSettingsResult<ImportPreferences> {
        if (!preferences.stabilitySeconds.isFinite() || preferences.stabilitySeconds !in 0.5..300.0) {
            return invalid("INVALID_STABILITY_SECONDS", "stabilitySeconds")
        }
        val result = call(
            context,
            ApiMethod.Put,
            "/api/system-settings",
            body = systemSettingsRequest(preferences.toSettings()),
            transform = JsonElement::toSystemSettings,
        )
        return mapSettingsResult(result, ::importPreferencesFrom)
    }

    override suspend fun listOrganizeJobs(context: AdministrativeSettingsContext, filter: OrganizeJobFilter): AdministrativeSettingsResult<OrganizeJobPage> {
        validatePage(filter.page, filter.pageSize, 100)?.let { return it }
        return call(
            context,
            ApiMethod.Get,
            "/api/organize/jobs",
            query = queryOf(
                "page" to filter.page.toString(),
                "pageSize" to filter.pageSize.toString(),
                "search" to filter.search?.trim()?.takeIf(String::isNotEmpty),
                "status" to filter.status?.wireValue,
            ),
            transform = JsonElement::toOrganizeJobPage,
        )
    }

    override suspend fun loadPendingOrganizeJobs(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/organize/pending", transform = JsonElement::toPendingOrganizeJobs)

    override suspend fun listOrganizeRuns(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/organize/runs", transform = JsonElement::toOrganizeRuns)

    override suspend fun loadOrganizeJob(context: AdministrativeSettingsContext, jobId: String) =
        idCall(context, ApiMethod.Get, "/api/organize/jobs", jobId, transform = JsonElement::toOrganizeJobPayload)

    override suspend fun recognizeOrganizeJob(context: AdministrativeSettingsContext, jobId: String) =
        idCall(context, ApiMethod.Post, "/api/organize/jobs", jobId, "/recognize", JsonElement::toOrganizeJobPayload)

    override suspend fun deleteOrganizeJob(context: AdministrativeSettingsContext, jobId: String) =
        idCall(context, ApiMethod.Delete, "/api/organize/jobs", jobId, transform = { it.toDeletedFlag(jobId) })

    override suspend fun loadOrganizeCandidates(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/organize/candidates", transform = JsonElement::toOrganizeCandidates)

    override suspend fun loadOrganizePolicy(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/organize/policy", transform = JsonElement::toOrganizePolicyPayload)

    override suspend fun updateOrganizePolicy(context: AdministrativeSettingsContext, policy: OrganizePolicy): AdministrativeSettingsResult<OrganizePolicy> {
        if (policy.intervalMinutes !in 1..100_800) return invalid("INVALID_INTERVAL", "intervalMinutes")
        if (policy.localMetadataPriority.toSet().size != policy.localMetadataPriority.size) {
            return invalid("DUPLICATE_METADATA_SOURCE", "localMetadataPriority")
        }
        return call(context, ApiMethod.Put, "/api/organize/policy", body = policy.toRequest(), transform = JsonElement::toOrganizePolicyPayload)
    }

    override suspend fun loadOpfQueueStatus(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/metadata/opf-sync/status", transform = JsonElement::toOpfQueueStatus)

    override suspend fun listLibraryOperations(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/library/operations", transform = JsonElement::toLibraryOperations)

    override suspend fun undoLibraryOperation(context: AdministrativeSettingsContext, operationId: String) =
        idCall(context, ApiMethod.Post, "/api/library/operations", operationId, "/undo", JsonElement::toUndoOperation)

    override suspend fun listCategories(context: AdministrativeSettingsContext, filter: CategoryFilter): AdministrativeSettingsResult<CategoryPage> {
        validatePage(filter.page, filter.pageSize, 100)?.let { return it }
        return call(
            context,
            ApiMethod.Get,
            "/api/library/categories",
            query = queryOf(
                "kind" to filter.kind.wireValue,
                "search" to filter.search?.trim()?.takeIf(String::isNotEmpty),
                "page" to filter.page.toString(),
                "pageSize" to filter.pageSize.toString(),
            ),
            transform = JsonElement::toCategoryPage,
        )
    }

    override suspend fun renameCategory(
        context: AdministrativeSettingsContext,
        categoryId: String,
        name: String,
    ): AdministrativeSettingsResult<LibraryOperation> {
        if (name.isBlank()) return invalid("INVALID_CATEGORY_NAME", "name")
        return idCall(
            context,
            ApiMethod.Patch,
            "/api/library/categories",
            categoryId,
            body = buildJsonObject { put("name", name.trim()) },
            transform = JsonElement::toCategoryOperation,
        )
    }

    override suspend fun mergeCategories(
        context: AdministrativeSettingsContext,
        kind: CategoryKind,
        targetId: String,
        sourceIds: List<String>,
    ): AdministrativeSettingsResult<LibraryOperation> {
        if (targetId.isBlank() || sourceIds.isEmpty() || targetId in sourceIds || sourceIds.any(String::isBlank)) {
            return invalid("INVALID_CATEGORY_SELECTION", "sourceIds")
        }
        return call(
            context,
            ApiMethod.Post,
            "/api/library/categories/merge",
            body = buildJsonObject {
                put("kind", kind.wireValue)
                put("targetId", targetId)
                put("sourceIds", JsonArray(sourceIds.distinct().map(::JsonPrimitive)))
            },
            transform = JsonElement::toCategoryOperation,
        )
    }

    override suspend fun deleteCategory(context: AdministrativeSettingsContext, categoryId: String) =
        idCall(context, ApiMethod.Delete, "/api/library/categories", categoryId, transform = JsonElement::toCategoryOperation)

    override suspend fun loadMetadataProviders(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/metadata/providers", transform = JsonElement::toMetadataProviders)

    override suspend fun loadMetadataProvider(context: AdministrativeSettingsContext, providerId: String) =
        idCall(context, ApiMethod.Get, "/api/metadata/providers", providerId, transform = JsonElement::toMetadataProviderPayload)

    override suspend fun updateMetadataProvider(
        context: AdministrativeSettingsContext,
        providerId: String,
        update: MetadataProviderUpdate,
    ): AdministrativeSettingsResult<MetadataProvider> {
        if (update.priority < 0) return invalid("INVALID_PROVIDER_PRIORITY", "priority")
        return idCall(
            context,
            ApiMethod.Patch,
            "/api/metadata/providers",
            providerId,
            body = update.toRequest(),
            transform = JsonElement::toMetadataProviderPayload,
        )
    }

    override suspend fun testMetadataProvider(context: AdministrativeSettingsContext, providerId: String) =
        idCall(context, ApiMethod.Post, "/api/metadata/providers", providerId, "/test", JsonElement::toProviderTestResult)

    override suspend fun updateMetadataPipeline(
        context: AdministrativeSettingsContext,
        mediaKind: MediaKind,
        entries: List<MetadataPipelineEntry>,
    ): AdministrativeSettingsResult<MetadataProviders> {
        if (entries.map(MetadataPipelineEntry::providerId).any(String::isBlank) || entries.distinctBy(MetadataPipelineEntry::providerId).size != entries.size) {
            return invalid("INVALID_PROVIDER_PIPELINE", "entries")
        }
        return call(
            context,
            ApiMethod.Put,
            "/api/metadata/provider-pipelines/${mediaKind.wireValue.encodeURLPathPart()}",
            body = entries.toPipelineRequest(),
            transform = JsonElement::toMetadataProviders,
        )
    }

    override suspend fun loadOpdsSettings(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/system-settings/opds", transform = JsonElement::toOpdsSettings)

    override suspend fun updateOpdsSettings(
        context: AdministrativeSettingsContext,
        enabled: Boolean,
        publicBaseUrl: String?,
    ): AdministrativeSettingsResult<OpdsSettings> {
        val normalizedUrl = publicBaseUrl?.trim()?.takeIf(String::isNotEmpty)
        if (normalizedUrl != null && normalizedUrl.length > 2048) return invalid("INVALID_PUBLIC_BASE_URL", "publicBaseUrl")
        return call(
            context,
            ApiMethod.Put,
            "/api/system-settings/opds",
            body = buildJsonObject {
                put("enabled", enabled)
                put("publicBaseUrl", normalizedUrl?.let(::JsonPrimitive) ?: JsonNull)
            },
            transform = JsonElement::toOpdsSettings,
        )
    }

    override suspend fun listBackups(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/backups", transform = JsonElement::toBackups)

    override suspend fun loadBackup(context: AdministrativeSettingsContext, backupId: String) =
        idCall(context, ApiMethod.Get, "/api/backups", backupId, transform = JsonElement::toBackupPayload)

    override suspend fun createBackup(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Post, "/api/backups", transform = JsonElement::toBackupPayload)

    override suspend fun downloadBackup(
        context: AdministrativeSettingsContext,
        backupId: String,
        maximumBytes: Int,
    ): AdministrativeSettingsResult<BackupDownload> {
        if (backupId.isBlank()) return invalid("INVALID_ID", "backupId")
        if (maximumBytes <= 0) return invalid("INVALID_MAXIMUM_BYTES", "maximumBytes")
        return binaryCall(context, backupId, maximumBytes)
    }

    override suspend fun restoreBackup(
        context: AdministrativeSettingsContext,
        backupId: String,
        confirmation: BackupRestoreConfirmation,
    ) = idCall(
        context,
        ApiMethod.Post,
        "/api/backups",
        backupId,
        "/restore",
        body = buildJsonObject {
            put("confirm", true)
            put("confirmText", confirmation.wireValue)
        },
        transform = JsonElement::toBackupRestore,
    )

    override suspend fun deleteBackup(context: AdministrativeSettingsContext, backupId: String) =
        idCall(context, ApiMethod.Delete, "/api/backups", backupId, transform = { it.toDeletedFlag(backupId) })

    override suspend fun loadWorkDetailTabOrder(context: AdministrativeSettingsContext): AdministrativeSettingsResult<WorkDetailTabOrder> =
        mapSettingsResult(loadSystemSettings(context), ::tabOrderFrom)

    override suspend fun updateWorkDetailTabOrder(
        context: AdministrativeSettingsContext,
        order: WorkDetailTabOrder,
    ): AdministrativeSettingsResult<WorkDetailTabOrder> {
        if (order.tabs.toSet() != WorkDetailTab.entries.toSet() || order.tabs.size != WorkDetailTab.entries.size) {
            return invalid("INVALID_TAB_ORDER", "tabs")
        }
        val result = call(
            context,
            ApiMethod.Put,
            "/api/system-settings",
            body = systemSettingsRequest(mapOf(WORK_DETAIL_ORDER_KEY to SettingValue.TextList(order.tabs.map(WorkDetailTab::wireValue)))),
            transform = JsonElement::toSystemSettings,
        )
        return mapSettingsResult(result, ::tabOrderFrom)
    }

    override suspend fun startHealthRun(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Post, "/api/system/health/runs", transform = JsonElement::toHealthRun)

    override suspend fun loadHealthRun(context: AdministrativeSettingsContext, runId: String) =
        idCall(context, ApiMethod.Get, "/api/system/health/runs", runId, transform = JsonElement::toHealthRun)

    override suspend fun restartImportQueue(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Post, "/api/system/queues/import/restart", transform = JsonElement::toQueueOperationPayload)

    override suspend fun loadQueueOperation(context: AdministrativeSettingsContext, operationId: String) =
        idCall(context, ApiMethod.Get, "/api/system/queue-operations", operationId, transform = JsonElement::toQueueOperationPayload)

    override suspend fun listManagementEvents(
        context: AdministrativeSettingsContext,
        filter: ManagementEventFilter,
    ): AdministrativeSettingsResult<ManagementEventPage> {
        validatePage(filter.page, filter.pageSize, 100)?.let { return it }
        return call(
            context,
            ApiMethod.Get,
            "/api/management/events",
            query = queryOf(
                "page" to filter.page.toString(),
                "pageSize" to filter.pageSize.toString(),
                "level" to filter.level,
                "source" to filter.source,
                "targetType" to filter.targetType,
                "search" to filter.search?.trim()?.takeIf(String::isNotEmpty),
                "dateFrom" to filter.dateFrom,
                "dateTo" to filter.dateTo,
            ),
            transform = JsonElement::toManagementEventPage,
        )
    }

    override suspend fun clearManagementEvents(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Delete, "/api/management/events", transform = JsonElement::toClearedManagementEvents)

    override suspend fun loadAllManagementEventsForExport(
        context: AdministrativeSettingsContext,
        filter: ManagementEventFilter,
    ): AdministrativeSettingsResult<List<ManagementEvent>> {
        val exported = mutableListOf<ManagementEvent>()
        var page = 1
        var totalPages = 1
        do {
            when (val result = listManagementEvents(context, filter.copy(page = page, pageSize = 100))) {
                is AdministrativeSettingsResult.Failure -> return result
                is AdministrativeSettingsResult.Content -> {
                    exported += result.value.events
                    totalPages = result.value.pageInfo.totalPages
                }
            }
            page += 1
        } while (page <= totalPages)
        return AdministrativeSettingsResult.Content(exported)
    }

    override suspend fun loadLogSettings(context: AdministrativeSettingsContext) =
        call(context, ApiMethod.Get, "/api/system/log-settings", transform = JsonElement::toLogSettings)

    override suspend fun updateLogCapacity(
        context: AdministrativeSettingsContext,
        maximumBytes: Long,
    ): AdministrativeSettingsResult<EventStorage> {
        if (maximumBytes !in MINIMUM_LOG_BYTES..MAXIMUM_LOG_BYTES) {
            return invalid("INVALID_LOG_CAPACITY", "maximumBytes")
        }
        return call(
            context,
            ApiMethod.Put,
            "/api/system/log-settings",
            body = buildJsonObject { put("maxBytes", maximumBytes) },
            transform = { it.toLogSettings().storage },
        )
    }

    private suspend fun loadSystemSettings(
        context: AdministrativeSettingsContext,
    ): AdministrativeSettingsResult<Map<String, SettingValue>> =
        call(context, ApiMethod.Get, "/api/system-settings", transform = JsonElement::toSystemSettings)

    private suspend fun binaryCall(
        context: AdministrativeSettingsContext,
        backupId: String,
        maximumBytes: Int,
    ): AdministrativeSettingsResult<BackupDownload> {
        val startGeneration = freshnessMutex.withLock { responseGeneration }
        val result = request(context) { client ->
            client.loadAuthenticatedBinary(
                apiPath = "/api/backups/${backupId.encodeURLPathPart()}/download",
                maximumBytes = maximumBytes,
                allowedMimeTypes = setOf("application/zip", "application/octet-stream"),
            )
        }
        if (freshnessMutex.withLock { responseGeneration } != startGeneration) return stale()
        return when (result) {
            is ApiResult.Failure -> AdministrativeSettingsResult.Failure(result.error.toAdministrativeSettingsError())
            is ApiResult.Success -> {
                val fileName = contentDispositionFileName(result.value.contentDisposition)
                    ?: "shuku-backup-${backupId.safeFileName()}.zip"
                AdministrativeSettingsResult.Content(
                    BackupDownload(result.value.bytes, fileName, result.value.mimeType),
                )
            }
        }
    }

    private suspend fun <T> idCall(
        context: AdministrativeSettingsContext,
        method: ApiMethod,
        prefix: String,
        id: String,
        suffix: String = "",
        transform: (JsonElement) -> T,
    ): AdministrativeSettingsResult<T> = idCall(context, method, prefix, id, suffix, null, transform)

    private suspend fun <T> idCall(
        context: AdministrativeSettingsContext,
        method: ApiMethod,
        prefix: String,
        id: String,
        suffix: String = "",
        body: JsonObject?,
        transform: (JsonElement) -> T,
    ): AdministrativeSettingsResult<T> {
        if (id.isBlank()) return invalid("INVALID_ID", "id")
        return call(context, method, "$prefix/${id.encodeURLPathPart()}$suffix", body = body, transform = transform)
    }

    private suspend fun <T> call(
        context: AdministrativeSettingsContext,
        method: ApiMethod,
        apiPath: String,
        query: Map<String, List<String>> = emptyMap(),
        body: JsonObject? = null,
        transform: (JsonElement) -> T,
    ): AdministrativeSettingsResult<T> {
        val startGeneration = freshnessMutex.withLock { responseGeneration }
        val result = request(context) { client ->
            client.execute(
                ApiRequest(
                    method = method,
                    apiPath = apiPath,
                    queryParameters = query,
                    responseDeserializer = JsonElement.serializer(),
                    requestBody = body?.let(encoder::encodeToString),
                ),
            )
        }
        if (freshnessMutex.withLock { responseGeneration } != startGeneration) return stale()
        return when (result) {
            is ApiResult.Failure -> AdministrativeSettingsResult.Failure(result.error.toAdministrativeSettingsError())
            is ApiResult.Success -> try {
                AdministrativeSettingsResult.Content(transform(result.value))
            } catch (error: AdministrativeSettingsWireException) {
                protocol(error.stableCode)
            }
        }
    }

    private suspend fun <T> request(
        context: AdministrativeSettingsContext,
        block: suspend (ApiClient) -> ApiResult<T>,
    ): ApiResult<T> {
        val client = clientProvider(context.toServerProfile())
        return try {
            block(client)
        } finally {
            client.close()
        }
    }

    private fun AdministrativeSettingsContext.toServerProfile(): ServerProfile {
        val parsed = ServerBaseUrl.parse(baseUrl)
        check(parsed is ServerBaseUrlParseResult.Valid) { "Invalid administrative-settings server base URL" }
        return ServerProfile(
            id = profileId,
            displayName = profileDisplayName,
            baseUrl = parsed.baseUrl,
            serverIdentity = serverIdentity,
            isActive = true,
            tlsMode = when (tlsMode) {
                AdministrativeSettingsTlsMode.SystemTrust -> TlsMode.SystemTrust
                AdministrativeSettingsTlsMode.InsecureSkipAllValidation -> TlsMode.InsecureSkipAllValidation
            },
        )
    }

    private fun AppError.toAdministrativeSettingsError(): AdministrativeSettingsError =
        AdministrativeSettingsError(
            kind = when (kind) {
                AppErrorKind.InvalidRequest,
                AppErrorKind.PayloadTooLarge,
                AppErrorKind.Validation,
                -> AdministrativeSettingsErrorKind.Validation
                AppErrorKind.Unauthorized -> AdministrativeSettingsErrorKind.Unauthorized
                AppErrorKind.Forbidden -> AdministrativeSettingsErrorKind.Forbidden
                AppErrorKind.NotFoundOrUnavailable,
                AppErrorKind.Gone,
                -> AdministrativeSettingsErrorKind.NotFound
                AppErrorKind.Conflict -> AdministrativeSettingsErrorKind.Conflict
                AppErrorKind.RateLimited -> AdministrativeSettingsErrorKind.RateLimited
                AppErrorKind.ServiceUnavailable,
                AppErrorKind.ServerFailure,
                -> AdministrativeSettingsErrorKind.Server
                AppErrorKind.NetworkUnavailable,
                AppErrorKind.Timeout,
                AppErrorKind.TlsFailure,
                AppErrorKind.StorageFailure,
                AppErrorKind.Cancelled,
                -> AdministrativeSettingsErrorKind.Transport
                AppErrorKind.ProtocolViolation -> AdministrativeSettingsErrorKind.Protocol
            },
            code = code,
            fieldViolations = fieldErrors.keys.sorted().map {
                AdministrativeSettingsFieldViolation(it, "INVALID_FIELD")
            },
        )

    private fun validateSmtp(update: SmtpSettingsUpdate): AdministrativeSettingsResult.Failure? = when {
        update.host.isBlank() -> invalid("INVALID_SMTP_HOST", "host")
        update.port !in 1..65_535 -> invalid("INVALID_SMTP_PORT", "port")
        update.fromEmail.isBlank() || !update.fromEmail.looksLikeEmail() -> invalid("INVALID_FROM_EMAIL", "fromEmail")
        update.maximumAttachmentMegabytes != null && update.maximumAttachmentMegabytes !in 1.0..1000.0 ->
            invalid("INVALID_ATTACHMENT_LIMIT", "maximumAttachmentMegabytes")
        else -> null
    }

    private fun validateUser(
        name: String,
        email: String,
        password: String? = null,
    ): AdministrativeSettingsResult.Failure? = when {
        name.trim().length !in 1..40 -> invalid("INVALID_NAME", "name")
        !email.trim().looksLikeEmail() -> invalid("INVALID_EMAIL", "email")
        password != null && password.length !in 10..128 -> invalid("INVALID_PASSWORD", "password")
        else -> null
    }

    private fun validateLibrary(library: LibraryDraft): AdministrativeSettingsResult.Failure? = when {
        library.rootPath.isBlank() -> invalid("INVALID_ROOT_PATH", "rootPath")
        library.minimumFileSizeBytes < 0 -> invalid("INVALID_MIN_FILE_SIZE", "minimumFileSizeBytes")
        else -> null
    }

    private fun validatePage(
        page: Int,
        pageSize: Int,
        maximumPageSize: Int,
    ): AdministrativeSettingsResult.Failure? = when {
        page < 1 -> invalid("INVALID_PAGE", "page")
        pageSize !in 1..maximumPageSize -> invalid("INVALID_PAGE_SIZE", "pageSize")
        else -> null
    }

    private fun importPreferencesFrom(settings: Map<String, SettingValue>): AdministrativeSettingsResult<ImportPreferences> {
        val enabled = (settings[IMPORT_STABILITY_ENABLED] as? SettingValue.Toggle)?.value ?: false
        val seconds = when (val stored = settings[IMPORT_STABILITY_SECONDS]) {
            is SettingValue.Integer -> stored.value.toDouble()
            is SettingValue.Decimal -> stored.value
            else -> 2.0
        }
        val extensions = (settings[IMPORT_ALLOWED_EXTENSIONS] as? SettingValue.TextList)?.value ?: emptyList()
        val ignorePatterns = (settings[IMPORT_IGNORE_PATTERNS] as? SettingValue.Text)?.value.orEmpty()
        return AdministrativeSettingsResult.Content(ImportPreferences(enabled, seconds, extensions, ignorePatterns))
    }

    private fun ImportPreferences.toSettings(): Map<String, SettingValue> = mapOf(
        IMPORT_STABILITY_ENABLED to SettingValue.Toggle(stabilityCheckEnabled),
        IMPORT_STABILITY_SECONDS to SettingValue.Decimal(stabilitySeconds),
        IMPORT_ALLOWED_EXTENSIONS to SettingValue.TextList(allowedExtensions),
        IMPORT_IGNORE_PATTERNS to SettingValue.Text(ignorePatterns),
    )

    private fun tabOrderFrom(settings: Map<String, SettingValue>): AdministrativeSettingsResult<WorkDetailTabOrder> {
        val raw = when (val stored = settings[WORK_DETAIL_ORDER_KEY]) {
            is SettingValue.TextList -> stored.value
            is SettingValue.Text -> parseStoredStringList(stored.value)
            else -> null
        } ?: WorkDetailTab.entries.map(WorkDetailTab::wireValue)
        val parsed = raw.mapNotNull { value -> WorkDetailTab.entries.firstOrNull { it.wireValue == value } }
        val normalized = (parsed + WorkDetailTab.entries).distinct()
        return AdministrativeSettingsResult.Content(WorkDetailTabOrder(normalized))
    }

    private fun parseStoredStringList(value: String): List<String>? = try {
        (encoder.parseToJsonElement(value) as? JsonArray)?.map { element ->
            (element as? JsonPrimitive)?.takeIf(JsonPrimitive::isString)?.content
                ?: return null
        }
    } catch (_: IllegalArgumentException) {
        null
    }

    private fun <T, R> mapSettingsResult(
        result: AdministrativeSettingsResult<T>,
        transform: (T) -> AdministrativeSettingsResult<R>,
    ): AdministrativeSettingsResult<R> = when (result) {
        is AdministrativeSettingsResult.Content -> transform(result.value)
        is AdministrativeSettingsResult.Failure -> result
    }

    private fun queryOf(vararg pairs: Pair<String, String?>): Map<String, List<String>> =
        pairs.mapNotNull { (name, value) -> value?.let { name to listOf(it) } }.toMap()

    private fun String.looksLikeEmail(): Boolean {
        val at = indexOf('@')
        return at > 0 && at < lastIndex && substring(at + 1).contains('.') && length <= 320
    }

    private fun String.safeFileName(): String = filter { it.isLetterOrDigit() || it == '-' || it == '_' }.take(64).ifBlank { "backup" }

    private fun contentDispositionFileName(value: String?): String? {
        if (value == null) return null
        val encodedMarker = "filename*=UTF-8''"
        val encodedStart = value.indexOf(encodedMarker, ignoreCase = true)
        val encoded = if (encodedStart >= 0) {
            value.substring(encodedStart + encodedMarker.length).substringBefore(';').trim()
        } else {
            null
        }
        val encodedName = encoded?.let { candidate ->
            try {
                candidate.decodeURLPart()
            } catch (_: IllegalArgumentException) {
                null
            }
        }
        val quotedMarker = "filename=\""
        val quotedStart = value.indexOf(quotedMarker, ignoreCase = true)
        val quotedName = if (quotedStart >= 0) {
            value.substring(quotedStart + quotedMarker.length).substringBefore('"')
        } else {
            null
        }
        return (encodedName ?: quotedName)?.takeIf(::isSafeDownloadFileName)
    }

    private fun isSafeDownloadFileName(value: String): Boolean =
        value.isNotBlank() && '/' !in value && '\\' !in value && value.all { it.code >= 0x20 }

    private fun invalid(code: String, field: String): AdministrativeSettingsResult.Failure =
        AdministrativeSettingsResult.Failure(
            AdministrativeSettingsError(
                AdministrativeSettingsErrorKind.Validation,
                code,
                listOf(AdministrativeSettingsFieldViolation(field, "INVALID_FIELD")),
            ),
        )

    private fun <T> protocol(code: String): AdministrativeSettingsResult<T> =
        AdministrativeSettingsResult.Failure(
            AdministrativeSettingsError(AdministrativeSettingsErrorKind.Protocol, code),
        )

    private fun <T> stale(): AdministrativeSettingsResult<T> =
        AdministrativeSettingsResult.Failure(
            AdministrativeSettingsError(AdministrativeSettingsErrorKind.Stale, "STALE_RESPONSE"),
        )

    private companion object {
        val encoder = Json { explicitNulls = false }
        const val IMPORT_STABILITY_ENABLED = "import.stabilityCheck.enabled"
        const val IMPORT_STABILITY_SECONDS = "import.stabilityCheck.seconds"
        const val IMPORT_ALLOWED_EXTENSIONS = "import.allowedExtensions"
        const val IMPORT_IGNORE_PATTERNS = "import.ignorePatterns"
        const val WORK_DETAIL_ORDER_KEY = "workDetail.tabOrder"
        const val MINIMUM_LOG_BYTES = 1L * 1024L * 1024L
        const val MAXIMUM_LOG_BYTES = 100L * 1024L * 1024L
    }
}
