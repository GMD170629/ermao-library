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
    fun loadMapsOpaqueBookmarkPositions() = runBlocking {
        val port = port {
            respond(
                BOOKMARKS_RESPONSE,
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString()),
            )
        }

        val result = port.load(target())

        assertTrue(result.succeeded)
        assertEquals(listOf("chapter-1.xhtml", "comic/page-3", "pdf/page-4", "asset-1"), result.bookmarks.map { it.currentHref })
        assertEquals(30.0, result.bookmarks[1].displayPercent)
        assertEquals(42_000, result.bookmarks[3].position.presentation.playback?.positionMillis)
    }

    @Test
    fun malformedLocationIsRejectedAtTheTransportBoundary() = runBlocking {
        val port = port {
            respond(
                BOOKMARKS_RESPONSE.replace("\"displayPercent\":30.0", "\"displayPercent\":101.0"),
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
              {"id":"reflow-1","position":{"locator":{"href":"chapter-1.xhtml"},"presentation":{"displayPercent":10.0,"totalProgression":0.1,"currentHref":"chapter-1.xhtml","chapter":{"href":"chapter-1.xhtml","title":"Chapter 1","index":0},"page":null,"playback":null}},"label":"Chapter 1","createdAt":"2026-08-13T00:00:00Z"},
              {"id":"comic-1","position":{"locator":{"href":"comic/page-3"},"presentation":{"displayPercent":30.0,"totalProgression":0.3,"currentHref":"comic/page-3","chapter":null,"page":{"number":3,"total":10},"playback":null}},"label":"Page 3","createdAt":"2026-08-13T01:00:00Z"},
              {"id":"pdf-1","position":{"locator":{"href":"pdf/page-4"},"presentation":{"displayPercent":40.0,"totalProgression":0.4,"currentHref":"pdf/page-4","chapter":null,"page":{"number":4,"total":10},"playback":null}},"label":"Page 4","createdAt":"2026-08-13T02:00:00Z"},
              {"id":"audio-1","position":{"locator":{"href":"asset-1"},"presentation":{"displayPercent":50.0,"totalProgression":0.5,"currentHref":"asset-1","chapter":{"href":"chapter-2","title":null,"index":null},"page":null,"playback":{"positionMillis":42000,"durationMillis":84000}}},"label":"Track 2","createdAt":"2026-08-13T03:00:00Z"}
            ]}}
        """
    }
}
