package com.ermao.library.shared.modules.workmanagement.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
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
    fun readsBookDetailManagementCapability() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE)

        val result = assertIs<WorkManagementResult.Content<Boolean>>(
            harness.repository.supportsNativeManagement(context),
        )

        assertTrue(result.value)
        assertEquals(listOf("/base/api/mobile/compatibility"), harness.requests.map(Request::path))
    }

    @Test
    fun cachesCapabilityForTheAuthenticatedAuthorizationVersion() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE)

        assertTrue(assertIs<WorkManagementResult.Content<Boolean>>(
            harness.repository.supportsNativeManagement(context),
        ).value)
        assertTrue(assertIs<WorkManagementResult.Content<Boolean>>(
            harness.repository.supportsNativeManagement(context),
        ).value)

        assertEquals(listOf("/base/api/mobile/compatibility"), harness.requests.map(Request::path))
    }

    @Test
    fun bookLevelCommandsUseCurrentBackendContractsAndCachedCapability() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE, OK, OK, DELETE_RESPONSE, OK)

        assertTrue(assertIs<WorkManagementResult.Content<Boolean>>(
            harness.repository.supportsNativeManagement(context),
        ).value)
        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.regenerateBookCover(context, "book-1", "resource-1"),
        )
        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.rescanBook(context, "source-1"),
        )
        assertIs<WorkManagementResult.Content<*>>(
            harness.repository.deleteBook(context, "book-1"),
        )
        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.setBookReadingStatus(context, "book-1", ManagedReadingStatus.Finished),
        )

        assertEquals(
            listOf(
                "/base/api/mobile/compatibility",
                "/base/api/books/book-1/resources/resource-1/cover/regenerate",
                "/base/api/source-nodes/source-1/continue",
                "/base/api/library/operations/books/delete-sources",
                "/base/api/library/operations/books/reading-status",
            ),
            harness.requests.map(Request::path),
        )
        assertEquals("{\"ids\":[\"book-1\"],\"confirmation\":\"DELETE_SOURCE_FILES\"}", harness.requests[3].body)
        assertEquals("{\"ids\":[\"book-1\"],\"status\":\"FINISHED\"}", harness.requests[4].body)
    }

    @Test
    fun disabledBookManagementReturnsUnavailableWithoutExecutingMutation() = runBlocking {
        val harness = Harness(CAPABILITY_FALSE)

        val result = assertIs<WorkManagementResult.Failure>(
            harness.repository.updateBook(context, "book-1", BookMetadataDraft("Book", null, null, null, null)),
        )

        assertEquals(WorkManagementErrorKind.Unavailable, result.error.kind)
        assertEquals("BOOK_DETAIL_MANAGEMENT_UNAVAILABLE", result.error.code)
        assertEquals(listOf("/base/api/mobile/compatibility"), harness.requests.map(Request::path))
        assertTrue(harness.requests.none { "/api/works" in it.path })
    }

    @Test
    fun bookEditUsesCurrentBookPatchContract() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE, OK)

        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.updateBook(
                context,
                "book-1",
                BookMetadataDraft("Updated", "Author", "Description", "Series", 2.0),
            ),
        )

        val request = harness.requests[1]
        assertEquals("PATCH", request.method)
        assertEquals("/base/api/books/book-1", request.path)
        assertTrue(request.body.contains("\"title\":\"Updated\""))
        assertTrue(request.body.contains("\"seriesName\":\"Series\""))
        assertFalse(request.body.contains("tags"))
        assertFalse(request.body.contains("organized"))
    }

    @Test
    fun resourceEditUsesCurrentBookResourcePatchContract() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE, RESOURCE_RESPONSE)

        val result = assertIs<WorkManagementResult.Content<BookMutationOutcome>>(
            harness.repository.updateResource(
                context,
                "book-1",
                "resource-1",
                ResourceMetadataDraft(publisher = "Publisher", language = "zh-CN", isbn = "123"),
            ),
        )

        val request = harness.requests[1]
        assertEquals("PATCH", request.method)
        assertEquals("/base/api/books/book-1/resources/resource-1", request.path)
        assertTrue(request.body.contains("\"publisher\":\"Publisher\""))
        assertTrue(request.body.contains("\"language\":\"zh-CN\""))
        assertEquals("book-1", result.value.bookId)
        assertEquals("resource-1", result.value.resourceId)
    }

    @Test
    fun metadataSearchUsesBookSourceNodeRoute() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE, METADATA_SEARCH_RESPONSE)

        val result = assertIs<WorkManagementResult.Content<*>>(
            harness.repository.searchMetadata(context, "book-1", "source-1", "openlibrary", "Book"),
        ).value

        val request = harness.requests[1]
        assertEquals("POST", request.method)
        assertEquals("/base/api/books/book-1/source-nodes/source-1/metadata/search", request.path)
        assertTrue(request.body.contains("\"providerId\":\"openlibrary\""))
        assertEquals("Candidate", (result as com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult).candidates.single().title)
    }

    @Test
    fun metadataApplyUsesSourceNodePatchWhileCoverUploadRemainsUnavailable() = runBlocking {
        val harness = Harness(CAPABILITY_TRUE, OK)
        val candidate = com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate(
            id = "candidate",
            source = "openlibrary",
            title = "Candidate",
            author = null,
            description = null,
            tags = emptyList(),
            seriesName = null,
            publisher = null,
            publishedAt = null,
            language = null,
            isbn = null,
            coverUrl = null,
            confidence = 1.0,
        )

        val apply = harness.repository.applyMetadata(
            context,
            "book-1",
            "source-1",
            "openlibrary",
            candidate,
            setOf(MetadataField.Title),
        )
        val upload = harness.repository.uploadCover(
            context,
            "book-1",
            "source-1",
            "Book",
            null,
            CoverUpload("cover.jpg", "image/jpeg", byteArrayOf(1)),
        )

        assertIs<WorkManagementResult.Content<Unit>>(apply)
        assertEquals(WorkManagementErrorKind.Unavailable, assertIs<WorkManagementResult.Failure>(upload).error.kind)
        assertEquals("PATCH", harness.requests[1].method)
        assertEquals("/base/api/books/book-1/source-nodes/source-1", harness.requests[1].path)
        assertTrue(harness.requests[1].body.contains("\"title\":\"Candidate\""))
    }

    @Test
    fun kindleSendUsesBookAndAssetIdsWithoutBookManagementCapability() = runBlocking {
        val harness = Harness(KINDLE_RESPONSE)

        val result = assertIs<WorkManagementResult.Content<KindleSendOutcome>>(
            harness.repository.sendToKindle(context, "book-1", "asset-1"),
        )

        val request = harness.requests.single()
        assertEquals("POST", request.method)
        assertEquals("/base/api/kindle-send-tasks", request.path)
        assertEquals("{\"bookId\":\"book-1\",\"assetId\":\"asset-1\"}", request.body)
        assertTrue(result.value.alreadyQueued)
    }

    @Test
    fun readingStatusUsesResourceRouteWithoutLegacyVolumePath() = runBlocking {
        val harness = Harness(OK)

        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.setReadingStatus(context, "resource-1", ManagedReadingStatus.Finished),
        )

        val request = harness.requests.single()
        assertEquals("PUT", request.method)
        assertEquals("/base/api/reader/v4/resources/resource-1/reading-status", request.path)
        assertEquals("{\"status\":\"FINISHED\"}", request.body)
        assertTrue(harness.requests.none { "/volumes" in it.path })
    }

    private val profile = run {
        val parsed = assertIs<ServerBaseUrlParseResult.Valid>(ServerBaseUrl.parse("https://library.example/base"))
        ServerProfile("profile", "Library", parsed.baseUrl, "server", true, TlsMode.SystemTrust)
    }
    private val context = BookManagementContext(profile, PrivateDataNamespace("server", "user", 1))

    private fun Harness(vararg responses: String) = HarnessFactory(responses.toList())

    private inner class HarnessFactory(responses: List<String>) {
        val requests = mutableListOf<Request>()
        private val pending = ArrayDeque(responses)
        val repository = KtorWorkManagementRepository {
            ApiClient(
                profile,
                HttpClient(MockEngine { request ->
                    val body = (request.body as? TextContent)?.text.orEmpty()
                    requests += Request(request.method.value, request.url.encodedPath, body)
                    respond(
                        pending.removeFirstOrNull() ?: OK,
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }),
                Json { ignoreUnknownKeys = false; explicitNulls = false },
            )
        }
    }

    private data class Request(val method: String, val path: String, val body: String)

    private companion object {
        const val CAPABILITY_TRUE = """{"ok":true,"data":{"capabilities":{"bookDetailManagement":true}}}"""
        const val CAPABILITY_FALSE = """{"ok":true,"data":{"capabilities":{"bookDetailManagement":false}}}"""
        const val OK = """{"ok":true,"data":{}}"""
        const val RESOURCE_RESPONSE = """{"ok":true,"data":{"resource":{"id":"resource-1","bookId":"book-1"}}}"""
        const val METADATA_SEARCH_RESPONSE = """{"ok":true,"data":{"sourceNodeId":"source-1","providerId":"openlibrary","query":"Book","message":null,"candidates":[{"id":"candidate","source":"openlibrary","title":"Candidate","description":null,"coverUrl":null,"confidence":0.9}]}}"""
        const val KINDLE_RESPONSE = """{"ok":true,"data":{"alreadyQueued":true}}"""
        const val DELETE_RESPONSE = """{"ok":true,"data":{"deletedBookIds":["book-1"]}}"""
    }
}
