package com.ermao.library.shared.modules.workmanagement.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.VolumeMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.WorkMetadataDraft
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.http.content.TextContent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

class KtorWorkManagementRepositoryTest {
    @Test
    fun readsExplicitCompatibilityCapability() = runBlocking {
        val repository = repository {
            respond(
                """{"ok":true,"data":{"capabilities":{"workDetailManagement":true}}}""",
                HttpStatusCode.OK,
                jsonHeaders,
            )
        }

        val result = assertIs<WorkManagementResult.Content<Boolean>>(
            repository.supportsNativeManagement(context),
        )
        assertTrue(result.value)
    }

    @Test
    fun volumeEditUsesTypedPatchContract() = runBlocking {
        val repository = repository { request ->
            assertEquals("PATCH", request.method.value)
            assertTrue(request.url.encodedPath.endsWith("/api/works/work/volumes/volume"))
            val body = assertIs<TextContent>(request.body).text
            assertTrue(body.contains("\"title\":\"Volume 2\""))
            assertTrue(body.contains("\"sortOrder\":3"))
            respond("""{"ok":true,"data":{"workId":"work"}}""", HttpStatusCode.OK, jsonHeaders)
        }

        val result = repository.updateVolume(
            context,
            "work",
            "volume",
            VolumeMetadataDraft("Volume 2", 2.0, 3, "Publisher", "zh-CN", "isbn", null, null),
        )

        assertEquals("work", assertIs<WorkManagementResult.Content<*>>(result).value.let {
            (it as com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome).workId
        })
    }

    @Test
    fun reclassifyDoesNotReturnAVersionId() = runBlocking {
        val repository = repository {
            respond(
                """{"ok":true,"data":{"movedVolumeIds":["volume"],"operation":{"id":"op"}}}""",
                HttpStatusCode.OK,
                jsonHeaders,
            )
        }

        val result = assertIs<WorkManagementResult.Content<*>>(
            repository.reclassifyVolume(context, "work", "volume", ManagedMediaKind.Comic),
        ).value as com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome

        assertEquals(null, result.targetVersionId)
    }

    @Test
    fun splitAndTransferReadServerTargetVersionId() = runBlocking {
        var requestIndex = 0
        val repository = repository {
            val body = when (requestIndex++) {
                0 -> """{"ok":true,"data":{"workId":"work","targetWorkId":"work-split","sourceVersionId":"version-source","targetVersionId":"version-split","transferMode":"CREATED_VERSION"}}"""
                else -> """{"ok":true,"data":{"workId":"work","targetWorkId":"work-target","sourceVersionId":"version-source","targetVersionId":"version-target","transferMode":"APPENDED_VOLUME"}}"""
            }
            respond(body, HttpStatusCode.OK, jsonHeaders)
        }

        val split = assertIs<WorkManagementResult.Content<*>>(
            repository.splitVolume(context, "work", "volume", "Split", null),
        ).value as com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome
        assertEquals("work-split", split.targetWorkId)
        assertEquals("version-split", split.targetVersionId)

        val transfer = assertIs<WorkManagementResult.Content<*>>(
            repository.transferVolume(context, "work", "volume", "work-target"),
        ).value as com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome
        assertEquals("work-target", transfer.targetWorkId)
        assertEquals("version-target", transfer.targetVersionId)
    }

    @Test
    fun workEditAndDeleteUseSourcePreservingContracts() = runBlocking {
        var requestIndex = 0
        val repository = repository { request ->
            val body = assertIs<TextContent>(request.body).text
            when (requestIndex++) {
                0 -> {
                    assertEquals("PATCH", request.method.value)
                    assertTrue(body.contains("\"title\":\"Updated\""))
                    assertTrue(body.contains("\"organized\":true"))
                }
                else -> {
                    assertEquals("DELETE", request.method.value)
                    assertTrue(body.contains("\"deleteSource\":false"))
                }
            }
            respond("""{"ok":true,"data":{"workId":"work"}}""", HttpStatusCode.OK, jsonHeaders)
        }

        assertIs<WorkManagementResult.Content<Unit>>(
            repository.updateWork(
                context,
                "work",
                WorkMetadataDraft("Updated", "Author", "Description", null, null, listOf("tag")),
            ),
        )
        assertTrue(
            assertIs<WorkManagementResult.Content<*>>(repository.deleteWork(context, "work"))
                .value
                .let { it as com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome }
                .deletedWork,
        )
    }

    @Test
    fun metadataQueriesAndApplyFollowProviderPipelineContract() = runBlocking {
        var requestIndex = 0
        val repository = repository { request ->
            when (requestIndex++) {
                0 -> respond(
                    """{"ok":true,"data":{"providers":[{"id":"openlibrary","name":"Open Library","enabled":true,"mediaKinds":["EBOOK"]}],"pipelines":[{"mediaKind":"EBOOK","providers":[{"providerId":"openlibrary","enabled":true}]}]}}""",
                    HttpStatusCode.OK,
                    jsonHeaders,
                )
                1 -> {
                    assertTrue(assertIs<TextContent>(request.body).text.contains("\"source\":\"openlibrary\""))
                    respond(
                        """{"ok":true,"data":{"candidates":[{"id":"candidate","source":"openlibrary","title":"Book","author":"Author","tags":[],"volumeMetadata":{"publisher":"Press","language":"en","isbn":"123"},"confidence":0.9}],"message":null}}""",
                        HttpStatusCode.OK,
                        jsonHeaders,
                    )
                }
                else -> {
                    assertEquals("true", request.url.parameters["applyToAllVolumes"])
                    val body = assertIs<TextContent>(request.body).text
                    assertTrue(body.contains("\"fields\":[\"title\",\"publisher\"]"))
                    assertTrue(body.contains("\"volumeId\":\"volume\""))
                    respond("""{"ok":true,"data":{"book":{},"appliedFields":[]}}""", HttpStatusCode.OK, jsonHeaders)
                }
            }
        }

        val providers = assertIs<WorkManagementResult.Content<*>>(
            repository.loadMetadataProviders(context, ManagedMediaKind.Ebook),
        ).value as List<*>
        assertTrue((providers.single() as com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider).enabled)
        val search = assertIs<WorkManagementResult.Content<*>>(
            repository.searchMetadata(context, "work", "openlibrary", "Book"),
        ).value as com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
        val candidate = search.candidates.single()
        assertEquals("Press", candidate.publisher)
        assertIs<WorkManagementResult.Content<Unit>>(
            repository.applyMetadata(
                context,
                "work",
                "openlibrary",
                candidate,
                linkedSetOf(MetadataField.Title, MetadataField.Publisher),
                "volume",
                true,
            ),
        )
        Unit
    }

    @Test
    fun missingSmtpConfigurationIsAUsableNotReadyState() = runBlocking {
        val repository = repository {
            respond(
                """{"ok":true,"data":{"kindle":{"email":"reader@kindle.com"},"smtp":null}}""",
                HttpStatusCode.OK,
                jsonHeaders,
            )
        }

        val settings = assertIs<WorkManagementResult.Content<*>>(
            repository.loadKindleSettings(context),
        ).value as com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
        assertFalse(settings.ready)
        assertEquals("reader@kindle.com", settings.recipientEmail)
        assertEquals("", settings.senderEmail)
    }

    @Test
    fun readingStatusUsesOnlyServerSupportedManualStates() = runBlocking {
        val repository = repository { request ->
            assertEquals("PUT", request.method.value)
            assertTrue(request.url.encodedPath.endsWith("/api/reader/v4/volumes/volume/reading-status"))
            assertTrue(assertIs<TextContent>(request.body).text.contains("\"status\":\"FINISHED\""))
            respond(
                """{"ok":true,"data":{"volumeId":"volume","status":"FINISHED","percent":100}}""",
                HttpStatusCode.OK,
                jsonHeaders,
            )
        }

        assertIs<WorkManagementResult.Content<Unit>>(
            repository.setReadingStatus(context, "volume", ManagedReadingStatus.Finished),
        )
        Unit
    }

    private fun repository(handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData):
        KtorWorkManagementRepository {
        val engine = MockEngine(handler)
        val client = ApiClient(profile, HttpClient(engine), Json { ignoreUnknownKeys = true })
        return KtorWorkManagementRepository { client }
    }

    private val profile = run {
        val parsed = assertIs<ServerBaseUrlParseResult.Valid>(ServerBaseUrl.parse("https://library.example"))
        ServerProfile("profile", "Library", parsed.baseUrl, "server", true, TlsMode.SystemTrust)
    }
    private val context = WorkManagementContext(profile, PrivateDataNamespace("server", "user", 1))

    private companion object {
        val jsonHeaders = headersOf(HttpHeaders.ContentType, "application/json")
    }
}
