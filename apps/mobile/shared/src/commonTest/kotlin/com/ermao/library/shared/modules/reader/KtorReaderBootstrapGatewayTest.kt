package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Content
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Failure
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderBootstrapGateway
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
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

class KtorReaderBootstrapGatewayTest {
    @Test
    fun mapsV4SnapshotAndVersionedPublicAnchor() = runBlocking {
        val content = assertIs<Content>(gateway(VALID_BOOTSTRAP).load(request())).value

        assertEquals("server-token", content.target.serverContentFingerprint.value)
        assertEquals(2_222, content.remoteSnapshot?.updatedAtEpochMillis)
        assertEquals("server-token", content.remoteSnapshot?.serverContentFingerprint?.value)
        assertEquals(ReaderEnginePlatform.Ios, content.remoteSnapshot?.anchor?.engineLocator?.platform)
    }

    @Test
    fun fingerprintMismatchRetainsOnlyPercentAndClientTimestamp() = runBlocking {
        val mismatch = VALID_BOOTSTRAP.replace(
            "\"contentFingerprint\":\"server-token\",\"location\"",
            "\"contentFingerprint\":\"old-token\",\"location\"",
        )

        val content = assertIs<Content>(gateway(mismatch).load(request())).value

        assertEquals(80.0, content.remoteSnapshot?.percent)
        assertEquals(2_222, content.remoteSnapshot?.updatedAtEpochMillis)
        assertNull(content.remoteSnapshot?.anchor)
    }

    @Test
    fun rejectsBootstrapForAnotherAuthenticatedUser() = runBlocking {
        val response = VALID_BOOTSTRAP.replace("\"userId\":\"user-1\"", "\"userId\":\"user-2\"")

        val failure = assertIs<Failure>(gateway(response).load(request()))

        assertEquals("READER_BOOTSTRAP_USER_MISMATCH", failure.failureCode)
    }

    private fun gateway(body: String) = KtorReaderBootstrapGateway(
        createClient = { profile ->
            val engine = MockEngine {
                assertEquals("/api/reader/v4/volumes/volume-1/bootstrap", it.url.encodedPath)
                respond(
                    """{"ok":true,"data":$body}""",
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }
            ApiClient(profile, HttpClient(engine), Json { ignoreUnknownKeys = false; explicitNulls = false })
        },
    )

    private fun request() = ReaderBootstrapRequest(profile(), ReaderSyncNamespace("server-1", "user-1", 3), "volume-1")

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private companion object {
        val VALID_BOOTSTRAP = """
            {
              "schemaVersion":4,"userId":"user-1","readerType":"reflowable","sourceFormat":"epub",
              "contentFingerprint":"server-token","book":{"id":"work-1","title":"Book"},
              "mediaVersion":{"id":"media-1","workId":"work-1","mediaKind":"EBOOK","completed":true},
              "volume":{"id":"volume-1","title":"Volume"},"availableVolumes":[],
              "files":[{"id":"file-1","kind":"publication","mimeType":"application/epub+zip","sizeBytes":1234,"url":"/api/files/file-1","contentHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sortOrder":0}],
              "units":[],"fileUrl":"/api/files/file-1","capabilities":{},
              "progressSnapshot":{"schemaVersion":4,"clientId":"ios-client","updatedAtEpochMillis":2222,"percent":80.0,"contentFingerprint":"server-token","location":{"kind":"reflow","resourceKey":"EPUB/chapter.xhtml","progression":0.8,"engineLocator":{"engine":"readium","platform":"ios","version":"3.8.0","payload":{"href":"EPUB/chapter.xhtml"}}}}
            }
        """.trimIndent()
    }
}
