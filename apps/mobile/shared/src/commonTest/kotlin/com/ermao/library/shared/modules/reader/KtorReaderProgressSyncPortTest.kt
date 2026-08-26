package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.ReaderProgressQueryResult
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderProgressSyncPort
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
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class KtorReaderProgressSyncPortTest {
    @Test
    fun loadDecodesJsonProgressAndCarriesTheResponseEtag() = runBlocking {
        var request: HttpRequestData? = null
        val port = port { incoming ->
            request = incoming
            respond(
                PROGRESS_RESPONSE,
                HttpStatusCode.OK,
                headersOf(
                    HttpHeaders.ContentType to listOf("application/json; charset=utf-8"),
                    HttpHeaders.ETag to listOf("W/\"progress-2\""),
                ),
            )
        }

        val result = assertIs<ReaderProgressQueryResult.Current>(port.load(target(), null))

        assertEquals("W/\"progress-2\"", result.etag)
        assertEquals(2, result.snapshot?.revision)
        assertEquals("resource-1", result.snapshot?.resourceId)
        assertEquals("/api/reader/v4/resources/resource-1/progress", request?.url?.encodedPath)
        assertTrue(request?.headers?.get(HttpHeaders.IfNoneMatch) == null)
    }

    @Test
    fun loadSendsIfNoneMatchAndMaps304ToUnchanged() = runBlocking {
        var request: HttpRequestData? = null
        val port = port { incoming ->
            request = incoming
            respond(
                byteArrayOf(),
                HttpStatusCode.NotModified,
                headersOf(HttpHeaders.ETag to listOf("W/\"progress-2\"")),
            )
        }

        val result = assertIs<ReaderProgressQueryResult.Unchanged>(
            port.load(target(), "W/\"progress-1\""),
        )

        assertEquals("W/\"progress-2\"", result.etag)
        assertEquals("W/\"progress-1\"", request?.headers?.get(HttpHeaders.IfNoneMatch))
    }

    private fun port(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ) = KtorReaderProgressSyncPort(
        profile = profile(),
        createClient = { profile ->
            ApiClient(profile, HttpClient(MockEngine(handler)), Json { ignoreUnknownKeys = false })
        },
    )

    private fun target() = ReaderProgressSyncTarget(
        namespace = ReaderSyncNamespace("server-1", "user-1", 1),
        bookId = "book-1",
        resourceId = "resource-1",
        sourceFormat = ReaderFormat.Epub,
    )

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val PROGRESS_RESPONSE = """
            {"ok":true,"data":{"progressSnapshot":{"schemaVersion":4,"clientId":"android-client","revision":2,"locator":{"kind":"reflowable","engineLocator":{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","payload":{"href":"part00000.html","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title","fragments":["chapter-title"],"progression":0.42,"position":17},"text":{"highlight":"天地玄黄"}}}},"displayPercent":42.0,"receivedAtEpochMillis":1786500000100}}}
        """
    }
}
