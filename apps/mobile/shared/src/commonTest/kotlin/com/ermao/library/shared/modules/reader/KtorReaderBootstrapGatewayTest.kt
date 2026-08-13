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

class KtorReaderBootstrapGatewayTest {
    @Test
    fun mapsExactV4SnapshotAndArtifactVersion() = runBlocking {
        val content = assertIs<Content>(gateway(VALID_BOOTSTRAP).load(request())).value

        assertEquals(
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|readium:epub|epub-v1",
            content.artifactVersion,
        )
        assertEquals("/api/volumes/volume-1/file", content.publication.apiPath)
        assertEquals(1_234, content.publication.expectedSizeBytes)
        assertEquals("readium:epub", content.publication.publicationFingerprint.parser)
        assertEquals(18, content.remoteSnapshot?.revision)
        assertEquals(2_222, content.remoteSnapshot?.receivedAtEpochMillis)
        assertEquals(ReaderEnginePlatform.Ios, content.remoteSnapshot?.locator?.platform)
    }

    @Test
    fun malformedProgressSnapshotFailsClosedWithoutPercentageFallback() = runBlocking {
        val mismatch = VALID_BOOTSTRAP.replace(
            "\"locations\":{\"cssSelector\":\"#chapter-title\"},\"text\":{\"highlight\":\"Chapter\"}",
            "\"locations\":{\"progression\":0.8}",
        )

        val failure = assertIs<Failure>(gateway(mismatch).load(request()))

        assertEquals("READER_PROGRESS_SNAPSHOT_INVALID", failure.failureCode)
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
              "publicationFingerprint":{"originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parser":"readium:epub","normalization":"epub-v1"},"book":{"id":"work-1","title":"Book"},
              "mediaVersion":{"id":"media-1","workId":"work-1","mediaKind":"EBOOK","completed":true},
              "volume":{"id":"volume-1","title":"Volume"},"availableVolumes":[],
              "files":[{"id":"file-1","kind":"EPUB","mimeType":"application/epub+zip","sizeBytes":1234,"url":"/api/files/file-1","contentHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sortOrder":0}],
              "units":[],"fileUrl":"/api/volumes/volume-1/file","capabilities":{},"publication":{"manifestUrl":"/api/reader/v4/volumes/volume-1/publication/manifest.json","positionsUrl":"/api/reader/v4/volumes/volume-1/publication/positions.json"},
              "progressSnapshot":{"schemaVersion":4,"revision":18,"locator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","publication":{"originalFileHash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parser":"readium:epub","normalization":"epub-v1"},"payload":{"href":"EPUB/chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title"},"text":{"highlight":"Chapter"}}},"displayPercent":80.0,"receivedAtEpochMillis":2222}
            }
        """.trimIndent()
    }
}
