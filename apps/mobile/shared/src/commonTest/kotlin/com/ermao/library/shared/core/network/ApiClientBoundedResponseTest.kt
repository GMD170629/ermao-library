package com.ermao.library.shared.core.network

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.ByteChannel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.async
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ApiClientBoundedResponseTest {
    @Test
    fun rejectsOversizeAndRedirectAtHeadersWhileBodyNeverCompletes(): Unit = runBlocking {
        for (status in listOf(HttpStatusCode.OK, HttpStatusCode.Found)) {
            val channel = ByteChannel(autoFlush = true)
            val api = client(channel, status, "1000000")
            try {
                val result = withTimeout(1000) { api.loadAuthenticatedBinary(PATH, 10, MIMES) }
                assertEquals(if (status == HttpStatusCode.OK) "BINARY_TOO_LARGE" else "BINARY_REDIRECT_REJECTED",
                    assertIs<ApiResult.Failure>(result).error.code)
            } finally { api.close() }
        }
    }

    @Test
    fun detectsOverflowWithoutContentLength(): Unit = runBlocking {
        val api = client(ByteReadChannel(ByteArray(11)))
        try {
            assertEquals("BINARY_TOO_LARGE", assertIs<ApiResult.Failure>(
                api.loadAuthenticatedBinary(PATH, 10, MIMES)).error.code)
        } finally { api.close() }
    }

    @Test
    fun rejectsChangedVersionBeforeWaitingForTheBody(): Unit = runBlocking {
        val body = ByteChannel()
        val api = client(body)
        try {
            val result = withTimeout(1000) {
                api.loadAuthenticatedBinary(PATH, 10, MIMES,
                    expectedResponseHeaders = mapOf("X-Publication-Revision" to "expected"))
            }
            assertEquals("BINARY_VERSION_CHANGED", assertIs<ApiResult.Failure>(result).error.code)
        } finally { body.cancel(null); api.close() }
    }

    @Test
    fun receivesOnlyTheRequestedBoundedResource(): Unit = runBlocking {
        val bytes = byteArrayOf(1, 2, 3)
        val api = client(ByteReadChannel(bytes), length = "3")
        try {
            assertContentEquals(bytes, assertIs<ApiResult.Success<AuthenticatedBinary>>(
                api.loadAuthenticatedBinary(PATH, 10, MIMES)).value.bytes)
        } finally { api.close() }
    }

    @Test
    fun incompleteResponseIsNeverAccepted(): Unit = runBlocking {
        val api = client(ByteReadChannel(byteArrayOf(1, 2)), length = "3")
        try {
            assertIs<ApiResult.Failure>(api.loadAuthenticatedBinary(PATH, 10, MIMES))
        } finally { api.close() }
    }

    @Test
    fun errorEnvelopesRemainBounded(): Unit = runBlocking {
        val api = client(ByteReadChannel(ByteArray(70000)), HttpStatusCode.InternalServerError)
        try {
            assertIs<ApiResult.Failure>(api.loadAuthenticatedBinary(PATH, 100000, MIMES))
        } finally { api.close() }
    }

    @Test
    fun closingClientCancelsAnUnfinishedBody(): Unit = runBlocking {
        val started = CompletableDeferred<Unit>()
        val body = ByteChannel()
        val api = client(body, onRequest = { started.complete(Unit) })
        val request = async { api.loadAuthenticatedBinary(PATH, 10, MIMES) }
        try {
            withTimeout(1000) { started.await() }
            api.close()
            withTimeout(1000) { request.join() }
            assertTrue(request.isCancelled)
        } finally { body.cancel(null); api.close() }
    }

    private fun client(body: ByteReadChannel, status: HttpStatusCode = HttpStatusCode.OK, length: String? = null,
        onRequest: () -> Unit = {},
    ): ApiClient {
        val headers = Headers.build {
            append(HttpHeaders.ContentType, "application/xhtml+xml")
            length?.let { append(HttpHeaders.ContentLength, it) }
        }
        return ApiClient(profile(), HttpClient(MockEngine { onRequest(); respond(body, status, headers) }) {
            followRedirects = false
        }, Json)
    }

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile", "Books", baseUrl, "server", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val PATH = "/api/reader/v4/resources/book/publication/chapter.xhtml"
        val MIMES = setOf("application/xhtml+xml")
    }
}
