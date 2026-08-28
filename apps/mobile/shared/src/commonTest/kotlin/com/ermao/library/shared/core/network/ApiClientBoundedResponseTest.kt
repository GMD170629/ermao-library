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
    fun rejectsErrorHeadersWithoutWaitingForAnUnfinishedErrorBody(): Unit = runBlocking {
        for ((status, code) in listOf(HttpStatusCode.Unauthorized to "UNAUTHORIZED",
            HttpStatusCode.Forbidden to "FORBIDDEN", HttpStatusCode.NotFound to "NOT_FOUND",
            HttpStatusCode.Conflict to "CONFLICT", HttpStatusCode.PreconditionFailed to "CONFLICT",
            HttpStatusCode.PayloadTooLarge to "PAYLOAD_TOO_LARGE", HttpStatusCode.TooManyRequests to "RATE_LIMITED",
            HttpStatusCode.InternalServerError to "SERVER_FAILURE", HttpStatusCode.ServiceUnavailable to "UNAVAILABLE")) {
            val channel = ByteChannel(autoFlush = true)
            val api = client(channel, status)
            try {
                val result = withTimeout(1000) { api.loadAuthenticatedBinary(PATH, 10, MIMES) }
                assertEquals(code, assertIs<ApiResult.Failure>(result).error.code)
            } finally { channel.cancel(null); api.close() }
        }
    }

    @Test
    fun preservesAnAllowedErrorHeaderWithoutWaitingForAnUnfinishedBody(): Unit = runBlocking {
        val code = "PUBLICATION_TXT_NUL_CHARACTER"
        val body = ByteChannel(autoFlush = true)
        val api = client(body, HttpStatusCode.NotFound, extraHeaders = Headers.build { append("X-Error-Code", code) })
        try {
            val result = withTimeout(1000) {
                api.loadAuthenticatedBinary(PATH, 10, MIMES, errorCodeStatuses = mapOf(code to setOf(404)))
            }
            val failure = assertIs<ApiResult.Failure>(result).error
            assertEquals(code, failure.code)
            assertEquals(AppErrorKind.NotFoundOrUnavailable, failure.kind)
            assertEquals(null, failure.diagnosticMessage)
        } finally { body.cancel(null); api.close() }
    }

    @Test
    fun untrustedErrorHeadersCannotChangeTheHttpFailureCategory(): Unit = runBlocking {
        val allowedCode = "PUBLICATION_TXT_NUL_CHARACTER"
        val tooLongCode = "A".repeat(65)
        val cases = listOf(
            Triple(HttpStatusCode.Unauthorized, listOf(allowedCode), "UNAUTHORIZED"),
            Triple(HttpStatusCode.NotFound, listOf(allowedCode, allowedCode), "NOT_FOUND"),
            Triple(HttpStatusCode.NotFound, listOf("untrusted_lowercase"), "NOT_FOUND"),
            Triple(HttpStatusCode.NotFound, listOf("UNKNOWN_MISSING"), "NOT_FOUND"),
            Triple(HttpStatusCode.NotFound, listOf(tooLongCode), "NOT_FOUND"),
        )
        for ((status, codes, expected) in cases) {
            val body = ByteChannel(autoFlush = true)
            val api = client(body, status, extraHeaders = Headers.build {
                codes.forEach { append("X-Error-Code", it) }
            })
            try {
                val result = withTimeout(1000) {
                    api.loadAuthenticatedBinary(PATH, 10, MIMES, errorCodeStatuses = mapOf(
                        allowedCode to setOf(404), tooLongCode to setOf(404), "untrusted_lowercase" to setOf(404),
                    ))
                }
                assertEquals(expected, assertIs<ApiResult.Failure>(result).error.code)
            } finally { body.cancel(null); api.close() }
        }
    }

    @Test
    fun missingContentTypeAndInvalidLengthAreProtocolFailuresNotMissingBooks(): Unit = runBlocking {
        for ((contentType, length, expected) in listOf(
            Triple(null, null, "BINARY_CONTENT_TYPE_MISSING"),
            Triple("text/plain", null, "BINARY_CONTENT_TYPE_INVALID"),
            Triple("application/xhtml+xml", "-1", "BINARY_LENGTH_INVALID"),
            Triple("application/xhtml+xml", "not-a-number", "BINARY_LENGTH_INVALID"),
        )) {
            val body = ByteChannel(autoFlush = true)
            val api = client(body, length = length, contentType = contentType)
            try {
                val result = withTimeout(1000) { api.loadAuthenticatedBinary(PATH, 10, MIMES) }
                val error = assertIs<ApiResult.Failure>(result).error
                assertEquals(expected, error.code)
                assertEquals(AppErrorKind.ProtocolViolation, error.kind)
            } finally { body.cancel(null); api.close() }
        }
    }
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
        contentType: String? = "application/xhtml+xml",
        extraHeaders: Headers = Headers.Empty,
        onRequest: () -> Unit = {},
    ): ApiClient {
        val headers = Headers.build {
            contentType?.let { append(HttpHeaders.ContentType, it) }
            length?.let { append(HttpHeaders.ContentLength, it) }
            appendAll(extraHeaders)
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
