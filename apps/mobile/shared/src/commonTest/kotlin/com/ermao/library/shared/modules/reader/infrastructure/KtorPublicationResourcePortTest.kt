package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.ReaderAdmission
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.OnlinePublicationReadFailure
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.Headers
import io.ktor.http.HttpStatusCode
import io.ktor.utils.io.ByteChannel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs

class KtorPublicationResourcePortTest {
    @Test
    fun retainsTheAuthorizedServerErrorWithoutReadingAnUnfinishedBody(): Unit = runBlocking {
        val failures = mapOf(
            "PUBLICATION_CORRUPT" to ReaderErrorCode.ParseFailed,
            "PUBLICATION_UNSUPPORTED" to ReaderErrorCode.UnsupportedFormat,
            "PUBLICATION_PARSE_FAILED" to ReaderErrorCode.ParseFailed,
            "PUBLICATION_STRUCTURE_INVALID" to ReaderErrorCode.ParseFailed,
            "PUBLICATION_PARSER_LIMIT" to ReaderErrorCode.OutOfMemoryRisk,
            "PUBLICATION_PARSER_MEMORY" to ReaderErrorCode.OutOfMemoryRisk,
            "PUBLICATION_DRM_PROTECTED" to ReaderErrorCode.DrmProtected,
            "PUBLICATION_SECURITY_REJECTED" to ReaderErrorCode.SecurityRejected,
            "PUBLICATION_TXT_NUL_CHARACTER" to ReaderErrorCode.TxtNulCharacter,
            "PUBLICATION_TXT_ENCODING_UNSUPPORTED" to ReaderErrorCode.TxtEncodingUnsupported,
            "PUBLICATION_TXT_EMPTY" to ReaderErrorCode.TxtEmpty,
            "PUBLICATION_NOT_FOUND" to ReaderErrorCode.PublicationUnavailable,
        )
        for ((code, expected) in failures) {
            val failure = readFailure(HttpStatusCode.NotFound, code)
            assertEquals(code, failure.code)
            assertEquals(expected, failure.errorCode)
            assertFalse(ReaderAdmission.permitsDownload(failure.errorCode))
        }
    }

    @Test
    fun wrongStatusAndUnknownHeadersCannotSelectDownloads(): Unit = runBlocking {
        for ((status, header, expected) in listOf(
            Triple(HttpStatusCode.NotFound, "PUBLICATION_ONLINE_LIMIT", ReaderErrorCode.PublicationUnavailable),
            Triple(HttpStatusCode.Unauthorized, "PUBLICATION_ONLINE_LIMIT", ReaderErrorCode.Unauthorized),
            Triple(HttpStatusCode.Forbidden, "PUBLICATION_TXT_NUL_CHARACTER", ReaderErrorCode.Forbidden),
            Triple(HttpStatusCode.NotFound, "UNKNOWN_MISSING", ReaderErrorCode.PublicationUnavailable),
            Triple(HttpStatusCode.TooManyRequests, null, ReaderErrorCode.RateLimited),
            Triple(HttpStatusCode.ServiceUnavailable, null, ReaderErrorCode.ServerUnavailable),
        )) {
            val failure = readFailure(status, header)
            assertEquals(expected, failure.errorCode)
            assertFalse(ReaderAdmission.permitsDownload(failure.errorCode))
        }
    }

    @Test
    fun onlyTheDeclaredLimitAndRevisionStatusesRetainThoseCauses(): Unit = runBlocking {
        for ((status, code, expected) in listOf(
            Triple(HttpStatusCode.PayloadTooLarge, "PUBLICATION_ONLINE_LIMIT", ReaderErrorCode.OnlineLimit),
            Triple(HttpStatusCode.PayloadTooLarge, "PUBLICATION_RESOURCE_TOO_LARGE", ReaderErrorCode.OnlineLimit),
            Triple(HttpStatusCode.Conflict, "PUBLICATION_RESOURCE_CHANGED", ReaderErrorCode.PublicationChanged),
        )) {
            val failure = readFailure(status, code)
            assertEquals(code, failure.code)
            assertEquals(expected, failure.errorCode)
        }
    }

    private suspend fun readFailure(status: HttpStatusCode, code: String?): OnlinePublicationReadFailure {
        val body = ByteChannel(autoFlush = true)
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        val profile = ServerProfile("profile", "Books", baseUrl, "server", true, TlsMode.SystemTrust)
        val http = HttpClient(MockEngine {
            respond(body, status, Headers.build { code?.let { append("X-Error-Code", it) } })
        }) { followRedirects = false }
        val port = KtorPublicationResourcePort(ApiClient(profile, http, Json))
        return try {
            assertIs<OnlinePublicationReadFailure>(withTimeout(1000) {
                port.read("/api/reader/v4/resources/book/publication/manifest.json", 1024, setOf("application/webpub+json"))
            })
        } finally { body.cancel(null); port.close() }
    }
}
