package com.ermao.library.shared.modules.servers.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.servers.application.ServerProbeResult
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

class KtorServerProbeTest {
    @Test
    fun probesHealthBeforeCompatibilityAndReturnsServerIdentity() = runBlocking {
        val harness = ProbeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
        )

        val result = harness.probe.probe(profile())

        assertEquals("server-fixture", assertIs<ServerProbeResult.Compatible>(result).serverIdentity)
        assertEquals(listOf("/api/health", "/api/mobile/compatibility"), harness.requestPaths)
    }

    @Test
    fun nonSuccessfulHealthStatusStopsBeforeCompatibilityEvenWithSuccessEnvelope() = runBlocking {
        val harness = ProbeHarness(Response(503, HEALTHY))

        val failure = assertIs<ServerProbeResult.Failure>(harness.probe.probe(profile()))

        assertEquals(AppErrorKind.ServiceUnavailable, failure.error.kind)
        assertEquals("SERVER_NOT_READY", failure.error.code)
        assertEquals(listOf("/api/health"), harness.requestPaths)
    }

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile(
            id = "profile-fixture",
            displayName = "Books",
            baseUrl = baseUrl,
            serverIdentity = "pending",
            isActive = false,
            tlsMode = TlsMode.SystemTrust,
        )
    }

    private class ProbeHarness(vararg responses: Response) {
        val requestPaths = mutableListOf<String>()
        private val pendingResponses = ArrayDeque(responses.toList())
        val probe = KtorServerProbe { profile ->
            val engine = MockEngine { request ->
                requestPaths += request.url.encodedPath
                val response = pendingResponses.removeFirst()
                respond(
                    content = response.body,
                    status = HttpStatusCode.fromValue(response.statusCode),
                    headers = headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }
            ApiClient(profile, HttpClient(engine), Json { ignoreUnknownKeys = false })
        }
    }

    private data class Response(val statusCode: Int, val body: String)

    private companion object {
        const val HEALTHY = """{"ok":true,"data":{"service":"ermao-books","status":"ok"}}"""
        const val COMPATIBLE = """{"ok":true,"data":{"service":"ermao-books","serverIdentity":"server-fixture","serverVersion":"1.0.0","protocol":{"version":1,"minimumSupportedClientVersion":1},"readerSchemaVersion":4,"capabilities":{"setup":true,"cookieSession":true,"readerV4":true,"mediaRange":true,"managedOfflineDownloads":true}}}"""
    }
}
