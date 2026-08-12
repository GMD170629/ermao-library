package com.ermao.library.shared.modules.administrativesettings.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.administrativesettings.*
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.OutgoingContent
import io.ktor.http.headersOf
import io.ktor.utils.io.ByteChannel
import io.ktor.utils.io.readRemaining
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertContentEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.io.readByteArray
import kotlinx.serialization.json.Json

class KtorAdministrativeSettingsRepositoryTest {
    @Test
    fun messagingAndUserOperationsUseRealContracts() = runBlocking {
        val harness = Harness(
            Response(200, KINDLE_SETTINGS),
            Response(200, KINDLE_SETTINGS_UPDATED),
            Response(200, EMAIL_SETTINGS),
            Response(200, SMTP_TEST),
            Response(200, USERS),
            Response(201, USER_PAYLOAD),
            Response(200, PASSWORD_CHANGED),
            Response(200, DELETED_USER),
        )

        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadKindleSettings(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.updateKindleEmail(context(), "reader@kindle.com"))
        val email = assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadEmailSettings(context())).value
        assertEquals(SmtpSecurity.StartTls, assertIs<EmailSettings>(email).smtp.security)
        val smtpUpdate = SmtpSettingsUpdate(
            host = "smtp.example.com",
            port = 587,
            security = SmtpSecurity.StartTls,
            username = "reader",
            password = "secret-value",
            fromEmail = "sender@example.com",
            fromName = "Library",
            maximumAttachmentMegabytes = 25.0,
            clearPassword = false,
        )
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.testSmtp(context(), smtpUpdate))
        assertEquals(1, assertIs<AdministrativeSettingsContent<*>>(harness.repository.listUsers(context())).value.let { assertIs<List<*>>(it).size })
        assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.createUser(
                context(),
                CreateManagedUser(
                    "Reader",
                    "reader@example.com",
                    "new-password",
                    ManagedUserRole.Member,
                    canManageSystem = true,
                    canViewManualImports = true,
                    monitorFolderIds = listOf("folder-1"),
                    locale = ManagedLocale.EnUs,
                ),
            ),
        )
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.resetUserPassword(context(), "user-1", "next-password"))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.deleteUser(context(), "user-1", "reader@example.com"))

        assertEquals(
            listOf(
                HttpMethod.Get to "/base/api/kindle-settings",
                HttpMethod.Put to "/base/api/kindle-settings",
                HttpMethod.Get to "/base/api/email-settings",
                HttpMethod.Post to "/base/api/email-settings/smtp-test",
                HttpMethod.Get to "/base/api/admin/users",
                HttpMethod.Post to "/base/api/admin/users",
                HttpMethod.Put to "/base/api/admin/users/user-1/password",
                HttpMethod.Delete to "/base/api/admin/users/user-1",
            ),
            harness.requests.map { it.method to it.path },
        )
        assertEquals("""{"email":"reader@kindle.com"}""", harness.requests[1].body)
        assertTrue(harness.requests[3].body.contains("\"clearSmtpPassword\":false"))
        assertTrue(harness.requests[5].body.contains("\"monitorFolderIds\":[\"folder-1\"]"))
        assertEquals("""{"password":"next-password"}""", harness.requests[6].body)
        assertEquals("""{"confirmation":"reader@example.com"}""", harness.requests[7].body)
    }

    @Test
    fun nativeSystemOperationsDoNotExposeOrUseWebPages() = runBlocking {
        val harness = Harness(
            Response(200, MONITOR_FOLDERS),
            Response(200, DIRECTORY),
            Response(200, IMPORT_TASKS),
            Response(200, ORGANIZE_POLICY),
            Response(200, OPDS),
            Response(201, BACKUP_PAYLOAD),
            Response(200, HEALTH_RUN),
            Response(202, QUEUE_OPERATION),
            Response(200, EVENTS),
            Response(200, LOG_SETTINGS),
        )

        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadMonitorFolders(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadDirectory(context(), "/books"))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.listImportTasks(context(), ImportTaskFilter()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadOrganizePolicy(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadOpdsSettings(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.createBackup(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.startHealthRun(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.restartImportQueue(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.listManagementEvents(context(), ManagementEventFilter()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadLogSettings(context()))

        val paths = harness.requests.map(CapturedRequest::path)
        assertEquals(
            listOf(
                "/base/api/monitor-folders",
                "/base/api/monitor-folders/tree",
                "/base/api/import-tasks",
                "/base/api/organize/policy",
                "/base/api/system-settings/opds",
                "/base/api/backups",
                "/base/api/system/health/runs",
                "/base/api/system/queues/import/restart",
                "/base/api/management/events",
                "/base/api/system/log-settings",
            ),
            paths,
        )
        assertTrue(paths.all { "/settings" !in it || "/system-settings" in it })
        assertEquals("/books", harness.requests[1].query["path"])
    }

    @Test
    fun approvedReadSurfacesUseTheRealDetailAndHistoryEndpoints() = runBlocking {
        val harness = Harness(
            Response(200, IMPORT_LOGS),
            Response(200, PENDING_ORGANIZE),
            Response(200, ORGANIZE_RUNS),
            Response(200, PROVIDER_PAYLOAD),
            Response(200, BACKUP_PAYLOAD),
        )

        assertIs<AdministrativeSettingsContent<*>>(harness.repository.listImportTaskLogs(context(), "task-1", 2, 25))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadPendingOrganizeJobs(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.listOrganizeRuns(context()))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadMetadataProvider(context(), "provider-1"))
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.loadBackup(context(), "backup-1"))

        assertEquals(
            listOf(
                "/base/api/import-tasks/task-1/logs",
                "/base/api/organize/pending",
                "/base/api/organize/runs",
                "/base/api/metadata/providers/provider-1",
                "/base/api/backups/backup-1",
            ),
            harness.requests.map(CapturedRequest::path),
        )
        assertEquals("2", harness.requests.first().query["page"])
        assertEquals("25", harness.requests.first().query["pageSize"])
    }

    @Test
    fun updateAndDeleteBodiesMatchTheWebContracts() = runBlocking {
        val harness = Harness(
            Response(200, MONITOR_FOLDER_PAYLOAD),
            Response(200, IMPORT_TASK_DELETED),
            Response(200, BACKUP_DELETED),
        )

        assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.updateMonitorFolder(
                context(),
                "folder-1",
                MonitorFolderDraft(
                    rootPath = "/books",
                    name = "Books",
                    shelfId = null,
                    enabled = true,
                    mediaKindPolicy = MediaKindPolicy.Mixed,
                    ignorePatterns = "*.tmp",
                    ignoreHidden = true,
                    minimumFileSizeBytes = 10240,
                    description = null,
                ),
            ),
        )
        assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.deleteImportTask(context(), "task-1", ImportDeleteMode.Source, deleteLibraryRecord = true),
        )
        assertIs<AdministrativeSettingsContent<*>>(harness.repository.deleteBackup(context(), "backup-1"))

        assertEquals(HttpMethod.Put, harness.requests[0].method)
        assertEquals("/base/api/monitor-folders/folder-1", harness.requests[0].path)
        assertEquals(
            """{"deleteMode":"source","deleteLibraryRecord":true}""",
            harness.requests[1].body,
        )
        assertEquals("", harness.requests[2].body)
    }

    @Test
    fun localizedMessagesNeverEscapeTypedFailures() = runBlocking {
        val harness = Harness(Response(409, """{"ok":false,"error":{"message":"健康检查运行期间无法操作","code":"HEALTH_RUN_ACTIVE"}}"""))

        val failure = assertIs<AdministrativeSettingsFailure>(harness.repository.restartImportQueue(context()))

        assertEquals(AdministrativeSettingsErrorKind.Conflict, failure.error.kind)
        assertEquals("HEALTH_RUN_ACTIVE", failure.error.code)
        assertEquals(false, failure.toString().contains("健康检查"))
    }

    @Test
    fun administrativeHttpFailuresHaveStableTypedMappings() = runBlocking {
        val cases = listOf(
            400 to AdministrativeSettingsErrorKind.Validation,
            401 to AdministrativeSettingsErrorKind.Unauthorized,
            409 to AdministrativeSettingsErrorKind.Conflict,
            413 to AdministrativeSettingsErrorKind.Validation,
            422 to AdministrativeSettingsErrorKind.Validation,
            503 to AdministrativeSettingsErrorKind.Server,
        )

        cases.forEach { (status, expectedKind) ->
            val harness = Harness(
                Response(status, """{"ok":false,"error":{"message":"不可作为程序分支","code":"CASE_$status"}}"""),
            )

            val failure = assertIs<AdministrativeSettingsFailure>(
                harness.repository.loadKindleSettings(context()),
            )

            assertEquals(expectedKind, failure.error.kind)
            assertEquals("CASE_$status", failure.error.code)
            assertEquals(false, failure.toString().contains("不可作为程序分支"))
        }
    }

    @Test
    fun malformedSuccessIsAProtocolFailure() = runBlocking {
        val harness = Harness(Response(200, """{"ok":true,"data":{"kindle":{"email":42}}}"""))

        val failure = assertIs<AdministrativeSettingsFailure>(harness.repository.loadKindleSettings(context()))

        assertEquals(AdministrativeSettingsErrorKind.Protocol, failure.error.kind)
        assertEquals("INVALID_email", failure.error.code)
    }

    @Test
    fun missingRequiredNullableWireFieldIsAProtocolFailure() = runBlocking {
        val harness = Harness(
            Response(
                200,
                """{"ok":true,"data":{"logs":[{"id":"log-1","level":"info","message":"display"}],"page":1,"pageSize":50,"total":1,"totalPages":1}}""",
            ),
        )

        val failure = assertIs<AdministrativeSettingsFailure>(
            harness.repository.listImportTaskLogs(context(), "task-1"),
        )

        assertEquals(AdministrativeSettingsErrorKind.Protocol, failure.error.kind)
        assertEquals("MISSING_createdAt", failure.error.code)
    }

    @Test
    fun invalidInputStopsBeforeNetwork() = runBlocking {
        val harness = Harness()

        val result = harness.repository.updateLogCapacity(context(), 1024L * 1024L - 1L)

        assertEquals("INVALID_LOG_CAPACITY", assertIs<AdministrativeSettingsFailure>(result).error.code)
        assertEquals(emptyList(), harness.requests)
    }

    @Test
    fun backupDownloadUsesAuthenticatedBinaryTransportWithABoundedPayload() = runBlocking {
        val harness = Harness(
            Response(
                200,
                "zip-content",
                "application/zip",
                "attachment; filename*=UTF-8''backup%20one.zip",
            ),
        )

        val download = assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.downloadBackup(context(), "backup-1", 1024),
        ).value
        val archive = assertIs<BackupDownload>(download)

        assertContentEquals("zip-content".encodeToByteArray(), archive.bytes)
        assertEquals("backup one.zip", archive.fileName)
        assertEquals("application/zip", archive.contentType)
        assertEquals(HttpMethod.Get, harness.requests.single().method)
        assertEquals("/base/api/backups/backup-1/download", harness.requests.single().path)
    }

    @Test
    fun backupRestoreRequiresAndSendsTheWebCompatibleConfirmationBody() = runBlocking {
        val harness = Harness(Response(200, BACKUP_RESTORED))

        assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.restoreBackup(context(), "backup-1", BackupRestoreConfirmation.Restore),
        )

        assertEquals(HttpMethod.Post, harness.requests.single().method)
        assertEquals("/base/api/backups/backup-1/restore", harness.requests.single().path)
        assertEquals("""{"confirm":true,"confirmText":"RESTORE"}""", harness.requests.single().body)
    }

    @Test
    fun backupDownloadRejectsAnOversizedStreamWithoutTrustingContentLength() = runBlocking {
        val harness = Harness(Response(200, "zip-content", "application/zip"))

        val failure = assertIs<AdministrativeSettingsFailure>(
            harness.repository.downloadBackup(context(), "backup-1", 3),
        )

        assertEquals(AdministrativeSettingsErrorKind.Validation, failure.error.kind)
        assertEquals("BINARY_TOO_LARGE", failure.error.code)
    }

    @Test
    fun importPreferencesUsePutAndPreserveTheSupportedHalfSecondValue() = runBlocking {
        val harness = Harness(Response(200, IMPORT_PREFERENCES), Response(200, IMPORT_PREFERENCES))

        val loaded = assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.loadImportPreferences(context()),
        ).value
        assertEquals(0.5, assertIs<ImportPreferences>(loaded).stabilitySeconds)
        assertIs<AdministrativeSettingsContent<*>>(
            harness.repository.updateImportPreferences(
                context(),
                ImportPreferences(true, 0.5, listOf(".epub"), "*.tmp"),
            ),
        )

        assertEquals(HttpMethod.Put, harness.requests.last().method)
        assertEquals("/base/api/system-settings", harness.requests.last().path)
        assertEquals(
            """{"settings":{"import.stabilityCheck.enabled":true,"import.stabilityCheck.seconds":0.5,"import.allowedExtensions":[".epub"],"import.ignorePatterns":"*.tmp"}}""",
            harness.requests.last().body,
        )
    }

    @Test
    fun cancellationPropagates() = runBlocking {
        val repository = KtorAdministrativeSettingsRepository { profile ->
            ApiClient(profile, HttpClient(MockEngine { throw CancellationException("cancelled") }), strictJson)
        }

        assertFailsWith<CancellationException> { repository.loadOpdsSettings(context()) }
        Unit
    }

    @Test
    fun invalidationRejectsAnOlderInFlightResponse() = runBlocking {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val repository = KtorAdministrativeSettingsRepository { profile ->
            ApiClient(
                profile,
                HttpClient(MockEngine {
                    entered.complete(Unit)
                    release.await()
                    respond(KINDLE_SETTINGS, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
                }),
                strictJson,
            )
        }
        val pending = async { repository.loadKindleSettings(context()) }
        entered.await()

        repository.invalidatePendingResponses()
        release.complete(Unit)

        val failure = assertIs<AdministrativeSettingsFailure>(pending.await())
        assertEquals(AdministrativeSettingsErrorKind.Stale, failure.error.kind)
        assertEquals("STALE_RESPONSE", failure.error.code)
    }

    private fun context(): AdministrativeSettingsContext = createAdministrativeSettingsContext(
        profileId = "profile-1",
        displayName = "Books",
        baseUrl = "https://books.example/base",
        serverIdentity = "server-fixture",
        acceptsInsecureTls = false,
    )

    private inner class Harness(vararg responses: Response) {
        val requests = mutableListOf<CapturedRequest>()
        private val pending = ArrayDeque(responses.toList())
        val repository = KtorAdministrativeSettingsRepository { profile ->
            ApiClient(
                profile,
                HttpClient(MockEngine { request ->
                    requests += CapturedRequest(
                        request.method,
                        request.url.encodedPath,
                        request.url.parameters.entries().associate { (key, values) -> key to values.first() },
                        request.body.readText(),
                    )
                    val response = pending.removeFirst()
                    val headers = response.contentDisposition?.let {
                        headersOf(
                            HttpHeaders.ContentType to listOf(response.contentType),
                            HttpHeaders.ContentDisposition to listOf(it),
                        )
                    } ?: headersOf(HttpHeaders.ContentType, response.contentType)
                    respond(
                        response.body,
                        HttpStatusCode.fromValue(response.statusCode),
                        headers,
                    )
                }),
                Json { explicitNulls = false },
            )
        }
    }

    private suspend fun OutgoingContent.readText(): String = when (this) {
        is OutgoingContent.ByteArrayContent -> bytes().decodeToString()
        is OutgoingContent.ReadChannelContent -> readFrom().readRemaining().readByteArray().decodeToString()
        is OutgoingContent.WriteChannelContent -> coroutineScope {
            val channel = ByteChannel()
            launch {
                try {
                    writeTo(channel)
                } finally {
                    channel.close()
                }
            }
            channel.readRemaining().readByteArray().decodeToString()
        }
        else -> ""
    }

    private data class CapturedRequest(
        val method: HttpMethod,
        val path: String,
        val query: Map<String, String>,
        val body: String,
    )

    private data class Response(
        val statusCode: Int,
        val body: String,
        val contentType: String = "application/json",
        val contentDisposition: String? = null,
    )

    private companion object {
        val strictJson = Json { explicitNulls = false }
        const val KINDLE_SETTINGS = """{"ok":true,"data":{"kindle":{"email":"reader@kindle.com"},"smtp":{"configured":true,"fromEmail":"sender@example.com"}}}"""
        const val KINDLE_SETTINGS_UPDATED = KINDLE_SETTINGS
        const val EMAIL_SETTINGS = """{"ok":true,"data":{"smtp":{"host":"smtp.example.com","port":587,"security":"starttls","username":"reader","fromEmail":"sender@example.com","fromName":"Library","maxAttachmentMb":25,"passwordConfigured":true},"kindle":{"email":"reader@kindle.com"}}}"""
        const val SMTP_TEST = """{"ok":true,"data":{"connected":true,"message":"ok"}}"""
        const val USER = """{"id":"user-1","email":"reader@example.com","name":"Reader","role":"member","status":"active","canManageSystem":true,"canViewManualImports":true,"authzVersion":7,"avatarUrl":null,"locale":"en-US","monitorFolderIds":["folder-1"],"authorization":{"isAdmin":false,"canManageSystem":true,"allLibraryScopes":false,"monitorFolderIds":["folder-1"],"canViewManualImports":true,"authzVersion":7},"createdAt":"2026-08-12T00:00:00Z","updatedAt":"2026-08-12T00:00:00Z"}"""
        const val USERS = """{"ok":true,"data":{"users":[$USER]}}"""
        const val USER_PAYLOAD = """{"ok":true,"data":{"user":$USER}}"""
        const val PASSWORD_CHANGED = """{"ok":true,"data":{"passwordChanged":true,"sessionsRevoked":true}}"""
        const val DELETED_USER = """{"ok":true,"data":{"deleted":true,"userId":"user-1"}}"""
        const val MONITOR_FOLDERS = """{"ok":true,"data":{"folders":[],"monitorRoot":"/books","lastUploadTargetPath":null,"lastDownloadTargetPath":null}}"""
        const val MONITOR_FOLDER_PAYLOAD = """{"ok":true,"data":{"folder":{"id":"folder-1","name":"Books","rootPath":"/books","shelfId":null,"enabled":true,"mediaKindPolicy":"MIXED","ignorePatterns":"*.tmp","ignoreHidden":true,"minFileSizeBytes":10240,"description":null,"createdAt":"2026-08-12T00:00:00Z","updatedAt":"2026-08-12T00:00:00Z"}}}"""
        const val DIRECTORY = """{"ok":true,"data":{"node":{"name":"books","path":"/books","readable":true,"error":null,"children":[]}}}"""
        const val IMPORT_TASKS = """{"ok":true,"data":{"tasks":[],"summary":{"completed":0,"failed":0},"page":1,"pageSize":20,"total":0,"totalPages":1}}"""
        const val IMPORT_LOGS = """{"ok":true,"data":{"logs":[{"id":"log-1","level":"info","message":"display only","createdAt":"2026-08-12T00:00:00Z"}],"page":2,"pageSize":25,"total":1,"totalPages":1}}"""
        const val IMPORT_TASK_DELETED = """{"ok":true,"data":{"deleted":true,"id":"task-1","deleteMode":"source","deleteLibraryRecord":true,"deletedLibraryRecord":true,"deletedWorkRecord":true,"deletedLibraryDatabaseRecords":1,"libraryRecordId":"work-1","deletedFiles":1,"missingFiles":[],"failedFileDeletes":[]}}"""
        const val ORGANIZE_POLICY = """{"ok":true,"data":{"policy":{"id":"default","enabled":false,"scheduleMode":"MANUAL","intervalMinutes":60,"autoRunOnNew":false,"autoRunOnNewSince":null,"rules":{"unrecognized":true,"missingMetadata":true},"writeMetadataToFiles":false,"preferLocalMetadata":true,"localMetadataPriority":["SIDECAR_OPF","EMBEDDED","PATH"],"lastScheduledAt":null,"nextRunAt":null,"updatedAt":"2026-08-12T00:00:00Z"}}}"""
        const val PENDING_ORGANIZE = """{"ok":true,"data":{"jobs":[],"books":[],"total":0}}"""
        const val ORGANIZE_RUNS = """{"ok":true,"data":{"runs":[{"id":"run-1","trigger":"MANUAL","scope":{"workIds":[],"rules":{"unrecognized":true,"missingMetadata":true}},"status":"COMPLETED","queuedCount":1,"completedCount":1,"reviewCount":0,"failedCount":0,"startedAt":"2026-08-12T00:00:00Z","finishedAt":"2026-08-12T00:01:00Z","createdAt":"2026-08-12T00:00:00Z","updatedAt":"2026-08-12T00:01:00Z"}]}}"""
        const val PROVIDER_PAYLOAD = """{"ok":true,"data":{"provider":{"id":"provider-1","sourceId":null,"name":"Provider","version":"1","description":"Metadata provider","mode":"REMOTE","mediaKinds":["EBOOK"],"fields":["title"],"capabilities":["search"],"automaticRateLimit":null,"configFields":[],"config":{},"configuredSecrets":{},"enabled":true,"priority":1,"lastTestAt":null,"lastTestStatus":null,"lastError":null}}}"""
        const val OPDS = """{"ok":true,"data":{"enabled":false,"configured":false,"publicBaseUrl":null,"catalogUrl":null}}"""
        const val BACKUP_PAYLOAD = """{"ok":true,"data":{"backup":{"id":"backup-1","kind":"full","name":"backup.zip","filename":"backup.zip","sizeBytes":42,"createdAt":"2026-08-12T00:00:00Z","counts":{"works":1}}}}"""
        const val BACKUP_RESTORED = """{"ok":true,"data":{"id":"backup-1","restored":true,"restoredAt":"2026-08-12T00:00:00Z","counts":{"works":1},"restoredCounts":{"works":1},"actualCounts":{"works":1}}}"""
        const val BACKUP_DELETED = """{"ok":true,"data":{"deleted":true,"id":"backup-1"}}"""
        const val IMPORT_PREFERENCES = """{"ok":true,"data":{"settings":{"import.stabilityCheck.enabled":true,"import.stabilityCheck.seconds":0.5,"import.allowedExtensions":[".epub"],"import.ignorePatterns":"*.tmp"}}}"""
        const val HEALTH_RUN = """{"ok":true,"data":{"run":{"runId":"run-1","status":"completed","version":2,"startedAt":1,"finishedAt":2,"groups":[],"items":[],"summary":{"total":0,"completed":0,"ok":0,"warning":0,"error":0,"skipped":0}}}}"""
        const val QUEUE_OPERATION = """{"ok":true,"data":{"operation":{"id":"operation-1","queueName":"import","action":"restart","status":"requested","actorUserId":"user-1","messageCode":"queue.restart.requested","requestedAt":"2026-08-12T00:00:00Z","startedAt":null,"finishedAt":null,"updatedAt":"2026-08-12T00:00:00Z"},"created":true}}"""
        const val EVENTS = """{"ok":true,"data":{"events":[],"page":1,"pageSize":20,"total":0,"totalPages":1,"storage":{"sizeBytes":0,"maxBytes":1048576,"lastPrunedAt":null},"facets":{"sources":[],"levels":[]}}}"""
        const val LOG_SETTINGS = """{"ok":true,"data":{"storage":{"sizeBytes":0,"maxBytes":1048576,"lastPrunedAt":null},"minBytes":1048576,"maxBytes":104857600}}"""
    }
}
