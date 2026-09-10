package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.workmanagement.createWorkManagementContext
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class KtorContentCoverTest {
    @Test fun bookMetadataPhasesAreIndependentOfPartialImportFailure() {
        val wire = Json.decodeFromString<BookWire>("""{"id":"book","libraryId":"lib","sourceNodeId":"root","title":"Book","visibilityState":"VISIBLE","curationState":"ACTIVE","publicationStatus":"UNKNOWN","trackingStatus":"NONE","metadataQuality":0,"coverStatus":"PENDING","coverUrl":"","metadataState":"COMPLETED","metadataPending":false,"metadataOnlineState":"FAILED","resourceImportSummary":{"pending":0,"failed":0,"failedFiles":1,"ready":1}}""")
        val detail = wire.toBookDetailSummary()
        assertEquals("COMPLETED", detail.metadataState)
        assertEquals(false, detail.metadataPending)
        assertEquals("FAILED", detail.metadataOnlineState)
        assertEquals(0, detail.failedResourceImportCount)
        assertEquals(1, detail.failedFileImportCount)
    }

    @Test fun unversionedCoversRevalidateAndFallbackIsNotArtwork() = runBlocking {
        val management = createWorkManagementContext("profile", "Test", "https://library.example", "server", false, "user", 1)
        val context = ContentRequestContext(management.profile, management.namespace)
        val repository = KtorContentRepository { profile ->
            ApiClient(profile, HttpClient(MockEngine { request ->
                assertEquals("no-cache", request.headers[HttpHeaders.CacheControl])
                respond(byteArrayOf(1, 2, 3), HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType to listOf("image/png"), "X-Shuku-Cover-Fallback" to listOf("1")))
            }), Json { ignoreUnknownKeys = true })
        }
        val result = assertIs<ContentResult.Content<com.ermao.library.shared.modules.library.AuthenticatedCover>>(
            repository.loadCover(context, "/api/books/b/cover", null))
        assertEquals(0, result.value.bytes.size)
    }

    @Test fun coverRequestsUseSmallVariantAndKeepBasePathAndValidators() = runBlocking {
        val management = createWorkManagementContext("profile", "Test", "https://library.example/base", "server", false, "user", 1)
        val context = ContentRequestContext(management.profile, management.namespace)
        val requests = mutableListOf<String>()
        val repository = KtorContentRepository { profile ->
            ApiClient(profile, HttpClient(MockEngine { request ->
                requests += request.url.toString()
                assertEquals("GET", request.method.value)
                assertEquals("cover-etag", request.headers[HttpHeaders.IfNoneMatch])
                respond(byteArrayOf(1, 2, 3), HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "image/png"))
            }), Json { ignoreUnknownKeys = false })
        }
        assertIs<ContentResult.Content<*>>(repository.loadCover(context, "/api/books/book/cover?size=medium&v=9", "cover-etag"))
        assertIs<ContentResult.Content<*>>(repository.loadCover(context, "/api/resources/book/previews/1?size=large", "cover-etag"))
        assertEquals(listOf("https://library.example/base/api/books/book/cover?v=9&size=small",
            "https://library.example/base/api/resources/book/previews/1?size=large"), requests)
    }

    @Test fun tagOptionsUseTheSharedLibraryFilterEndpoint() = runBlocking {
        val management = createWorkManagementContext("profile", "Test", "https://library.example/base", "server", false, "user", 1)
        val context = ContentRequestContext(management.profile, management.namespace)
        val repository = KtorContentRepository { profile ->
            ApiClient(profile, HttpClient(MockEngine { request ->
                assertEquals("/base/api/library/filter-options", request.url.encodedPath)
                assertEquals("tags", request.url.parameters["source"])
                assertEquals("历史", request.url.parameters["query"])
                assertEquals("20", request.url.parameters["limit"])
                respond(
                    """{"ok":true,"data":{"source":"tags","query":"历史","options":[{"value":"历史","label":"历史","count":4}],"hasMore":false,"indexReady":true}}""",
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }), Json { ignoreUnknownKeys = false })
        }

        val page = assertIs<ContentResult.Content<com.ermao.library.shared.modules.library.LibraryTagOptionPage>>(
            repository.loadTagOptions(context, " 历史 ", 20),
        ).value
        assertEquals("历史", page.options.single().value)
        assertEquals(4, page.options.single().count)
        assertEquals(false, page.hasMore)
        assertEquals(true, page.indexReady)
    }
}
