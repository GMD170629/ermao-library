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
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            content.artifactVersion,
        )
        assertEquals("/api/reader/v4/volumes/volume-1/publication/render.epub", content.publication.apiPath)
        assertEquals(2_345, content.publication.expectedSizeBytes)
        assertEquals(
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            content.publication.expectedContentHash,
        )
        assertEquals("epub-package:1", content.publication.publicationFingerprint.parser)
        assertEquals(ReaderSourceFormat.Epub, content.publication.sourceFormat)
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

    @Test
    fun mapsEveryMobiFamilySourceToTheMobiReader() = runBlocking {
        listOf(
            Triple("mobi", "MOBI", "application/x-mobipocket-ebook"),
            Triple("azw", "AZW", "application/vnd.amazon.ebook"),
            Triple("azw3", "AZW3", "application/vnd.amazon.ebook"),
            Triple("prc", "PRC", "application/x-mobipocket-ebook"),
        ).forEach { (wireFormat, kind, mimeType) ->
            val response = VALID_BOOTSTRAP
                .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"$wireFormat\"")
                .replace("\"format\":\"epub\"", "\"format\":\"$wireFormat\"")
                .replace(
                    "\"kind\":\"EPUB\",\"mimeType\":\"application/epub+zip\"",
                    "\"kind\":\"$kind\",\"mimeType\":\"$mimeType\"",
                )

            val content = assertIs<Content>(gateway(response).load(request())).value

            assertEquals(ReaderFormat.Epub, content.target.sourceFormat)
            assertEquals(wireFormat, content.publication.originalSourceFormat.wireValue)
            assertEquals(ReaderSourceFormat.Epub, content.publication.sourceFormat)
        }
    }

    @Test
    fun mapsP2FormatsOnlyWhenReaderTypeFileKindAndMimeMatch() = runBlocking {
        listOf(
            P2Format("txt", "reflowable", "TXT", "text/plain", ReaderFormat.Text),
            P2Format("cbz", "comic", "CBZ", "application/vnd.comicbook+zip", ReaderFormat.Comic),
            P2Format("pdf", "pdf", "PDF", "application/pdf", ReaderFormat.Pdf),
        ).forEach { format ->
            val response = VALID_BOOTSTRAP
                .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"${format.readerType}\"")
                .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"${format.sourceFormat}\"")
                .replace("\"format\":\"epub\"", "\"format\":\"${format.sourceFormat}\"")
                .replace(
                    "\"kind\":\"EPUB\",\"mimeType\":\"application/epub+zip\"",
                    "\"kind\":\"${format.kind}\",\"mimeType\":\"${format.mimeType}\"",
                )
                .let { value ->
                    if (format.sourceFormat == "cbz") value.replace(
                        "\"units\":[]",
                        "\"units\":[{\"unitType\":\"page\",\"href\":\"pages/001.jpg\",\"mediaType\":\"image/jpeg\",\"sortOrder\":0,\"width\":1200,\"height\":1800}]",
                    ) else value
                }

            val content = assertIs<Content>(gateway(response).load(request())).value
            assertEquals(
                if (format.readerType == "reflowable") ReaderFormat.Epub else format.readerFormat,
                content.target.sourceFormat,
            )
            assertEquals(format.sourceFormat, content.publication.originalSourceFormat.wireValue)
            assertEquals(
                if (format.readerType == "reflowable") ReaderSourceFormat.Epub.wireValue else format.sourceFormat,
                content.publication.sourceFormat.wireValue,
            )
            if (format.sourceFormat == "cbz") {
                assertEquals("pages/001.jpg", content.comicPages.single().resourceHref)
            }
        }
    }

    @Test
    fun rejectsUnsupportedAndMismatchedPublicationFiles() = runBlocking {
        val unsupported = VALID_BOOTSTRAP.replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"fb2\"")
        assertEquals(
            "READER_BOOTSTRAP_UNSUPPORTED",
            assertIs<Failure>(gateway(unsupported).load(request())).failureCode,
        )

        val mismatched = VALID_BOOTSTRAP.replace(
            "\"mimeType\":\"application/epub+zip\"",
            "\"mimeType\":\"application/x-mobipocket-ebook\"",
        )
        assertEquals(
            "READER_PUBLICATION_FILE_MISSING",
            assertIs<Failure>(gateway(mismatched).load(request())).failureCode,
        )
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

    private data class P2Format(
        val sourceFormat: String,
        val readerType: String,
        val kind: String,
        val mimeType: String,
        val readerFormat: ReaderFormat,
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
              "publicationFingerprint":{"originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parser":"epub-package:1","normalization":"shuku-epub-locator-dom-v2"},"contentFingerprint":"sha256:44645987ae2cd242d360a564e584a5c88fa0298b50f9a5282c89d87b5ba52bad","book":{"id":"work-1","title":"Book"},
              "mediaVersion":{"id":"media-1","workId":"work-1","mediaKind":"EBOOK","completed":true},
              "volume":{"id":"volume-1","title":"Volume","format":"epub"},"availableVolumes":[],
              "files":[{"id":"file-1","kind":"EPUB","mimeType":"application/epub+zip","sizeBytes":1234,"url":"/api/files/file-1","contentHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sortOrder":0}],
              "units":[],"fileUrl":"/api/volumes/volume-1/file","capabilities":{},"publication":{"manifestUrl":"/api/reader/v4/volumes/volume-1/publication/manifest.json","positionsUrl":"/api/reader/v4/volumes/volume-1/publication/positions.json","renderArtifact":{"schemaVersion":1,"url":"/api/reader/v4/volumes/volume-1/publication/render.epub","mimeType":"application/epub+zip","sizeBytes":2345,"contentHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}},
              "progressSnapshot":{"schemaVersion":4,"clientId":"ios-client","revision":18,"locator":{"kind":"reflowable","publication":{"originalFileHash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parser":"epub-package:1","normalization":"shuku-epub-locator-dom-v2"},"engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"EPUB/chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title"},"text":{"highlight":"Chapter"}}}},"displayPercent":80.0,"receivedAtEpochMillis":2222}
            }
        """.trimIndent()
    }
}
