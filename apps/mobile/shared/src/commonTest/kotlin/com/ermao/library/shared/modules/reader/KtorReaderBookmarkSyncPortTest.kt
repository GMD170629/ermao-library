package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.domain.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderBookmarkSyncPort
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

class KtorReaderBookmarkSyncPortTest {
    @Test
    fun loadMapsAllFourBookmarkLocationMorphologies() = runBlocking {
        val port = port {
            respond(
                BOOKMARKS_RESPONSE,
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString()),
            )
        }

        val result = port.load(target())

        assertTrue(result.succeeded)
        assertEquals(listOf("reflow", "comic", "pdf", "audio"), result.bookmarks.map { it.location.kind })
        assertEquals(3, result.bookmarks[1].location.pageIndex)
        assertEquals(4, result.bookmarks[2].location.pageNumber)
        assertEquals("asset-1", result.bookmarks[3].location.assetId)
        assertEquals(42_000, result.bookmarks[3].location.positionMs)
    }

    @Test
    fun malformedLocationIsRejectedAtTheTransportBoundary() = runBlocking {
        val port = port {
            respond(
                BOOKMARKS_RESPONSE.replace("\"pageIndex\":3", "\"pageIndex\":0"),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString()),
            )
        }

        val result = port.load(target())

        assertFalse(result.succeeded)
        assertEquals("INVALID_BOOKMARK_RESPONSE", result.failureCode)
    }

    private fun port(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ) = KtorReaderBookmarkSyncPort(
        profile = profile(),
        createClient = { profile ->
            ApiClient(profile, HttpClient(MockEngine(handler)), Json { ignoreUnknownKeys = false })
        },
    )

    private fun target() = ReaderBookmarkSyncTarget("server-1", "resource-1")

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val BOOKMARKS_RESPONSE = """
            {"ok":true,"data":{"bookmarks":[
              {"id":"reflow-1","location":{"kind":"reflow","resourceKey":"chapter-1.xhtml","progression":0.25},"label":"Chapter 1","percent":10.0,"createdAt":"2026-08-13T00:00:00Z"},
              {"id":"comic-1","location":{"kind":"comic","pageIndex":3},"label":"Page 3","percent":30.0,"createdAt":"2026-08-13T01:00:00Z"},
              {"id":"pdf-1","location":{"kind":"pdf","pageNumber":4},"label":"Page 4","percent":40.0,"createdAt":"2026-08-13T02:00:00Z"},
              {"id":"audio-1","location":{"kind":"audio","assetId":"asset-1","chapterId":"chapter-2","positionMs":42000},"label":"Track 2","percent":50.0,"createdAt":"2026-08-13T03:00:00Z"}
            ]}}
        """
    }
}
