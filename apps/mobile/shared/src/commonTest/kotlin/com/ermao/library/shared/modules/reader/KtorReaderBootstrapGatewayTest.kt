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
import io.ktor.client.engine.mock.respondError
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
    fun mapsExactV4SnapshotAndArtifactVersion() = runBlocking {
        val content = assertIs<Content>(gateway(VALID_BOOTSTRAP).load(request())).value

        assertEquals("/api/reader/v4/volumes/volume-1/publication/render.epub", content.publication.apiPath)
        assertEquals(2_345, content.publication.expectedSizeBytes)
        assertEquals(ReaderSourceFormat.Epub, content.publication.sourceFormat)
        assertEquals(18, content.remoteSnapshot?.revision)
        assertEquals(2_222, content.remoteSnapshot?.receivedAtEpochMillis)
        assertEquals(ReaderEnginePlatform.Ios, content.remoteSnapshot?.locator?.platform)
    }

    @Test
    fun acceptsNonEmptyUnitsFromTheRealReaderV4Contract() = runBlocking {
        val response = VALID_BOOTSTRAP.replace(
            "\"units\":[]",
            "\"units\":[$EPUB_UNIT]",
        )

        val content = assertIs<Content>(gateway(response).load(request())).value

        assertEquals(ReaderSourceFormat.Epub, content.publication.sourceFormat)
        assertEquals("pubnav-1", content.units.single().id)
        assertEquals(0, content.units.single().index)
        assertEquals("Chapter 1", content.units.single().title)
        assertEquals("EPUB/chapter.xhtml#chapter-title", content.units.single().href)
    }

    @Test
    fun retainsCanonicalUnitsInServerIndexOrderAndFallsBackBlankTitlesToIds() = runBlocking {
        val later = EPUB_UNIT
            .replace("pubnav-1", "pubnav-2")
            .replace("\"index\":0", "\"index\":2")
            .replace("\"title\":\"Chapter 1\"", "\"title\":\"   \"")
        val response = VALID_BOOTSTRAP.replace(
            "\"units\":[]",
            "\"units\":[$later,$EPUB_UNIT]",
        )

        val content = assertIs<Content>(gateway(response).load(request())).value

        assertEquals(listOf("pubnav-1", "pubnav-2"), content.units.map { it.id })
        assertEquals(listOf("Chapter 1", "pubnav-2"), content.units.map { it.title })
    }

    @Test
    fun malformedProgressSnapshotIsDiscardedWithoutBlockingPublicationBootstrap() = runBlocking {
        val mismatch = VALID_BOOTSTRAP.replace(
            "\"locations\":{\"cssSelector\":\"#chapter-title\"},\"text\":{\"highlight\":\"Chapter\"}",
            "\"locations\":{\"progression\":0.8}",
        )

        val content = assertIs<Content>(gateway(mismatch).load(request())).value

        assertNull(content.remoteSnapshot)
        assertEquals("/api/reader/v4/volumes/volume-1/publication/render.epub", content.publication.apiPath)
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
                    if (format.sourceFormat == "cbz") value
                        .replace("\"units\":[]", "\"units\":[$COMIC_UNIT]")
                        .replace(REFLOWABLE_PUBLICATION, COMIC_PUBLICATION)
                    else if (format.sourceFormat == "pdf") value
                        .replace(
                            "\"volume\":{\"id\":\"volume-1\",\"title\":\"Volume\",\"format\":\"pdf\"}",
                            "\"volume\":{\"id\":\"volume-1\",\"title\":\"Volume\",\"format\":\"pdf\",\"pageCount\":1}",
                        )
                        .replace("\"units\":[]", "\"units\":[$PDF_UNIT]")
                        .replace(REFLOWABLE_PUBLICATION, "\"publication\":null")
                    else value
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
                assertEquals("pages/0", content.comicPages.single().resourceHref)
            }
            if (format.sourceFormat == "pdf") {
                assertEquals("Page 1", content.pdfPages.single().title)
                assertEquals(0, content.pdfPages.single().pageIndex)
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

    @Test
    fun pdfBootstrapUsesDeclaredSizeWithoutAContentDigest() = runBlocking {
        val response = VALID_BOOTSTRAP
            .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"pdf\"")
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"pdf\"")
            .replace("\"format\":\"epub\"", "\"format\":\"pdf\"")
            .replace(
                "\"kind\":\"EPUB\",\"mimeType\":\"application/epub+zip\"",
                "\"kind\":\"PDF\",\"mimeType\":\"application/pdf\"",
            )

        val content = assertIs<Content>(gateway(response).load(request())).value
        assertEquals(1_234L, content.publication.expectedSizeBytes)
    }

    @Test
    fun pdfPageTitlesRemainHintsWhenServerPageNumbersDisagree() = runBlocking {
        val response = pdfBootstrap(PDF_UNIT.replace("\"pageNumber\":1", "\"pageNumber\":2"))

        val content = assertIs<Content>(gateway(response).load(request())).value

        assertEquals(listOf("Page 1"), content.pdfPages.map { it.title })
    }

    @Test
    fun duplicateReaderV4UnitsAreDroppedWithoutBlockingContentAccess() = runBlocking {
        val duplicate = PDF_UNIT.replace("\"index\":1", "\"index\":2")
        val response = pdfBootstrap("$PDF_UNIT,$duplicate")
            .replace("\"pageCount\":1", "\"pageCount\":2")

        val content = assertIs<Content>(gateway(response).load(request())).value

        assertEquals(1, content.units.size)
    }

    private fun gateway(body: String) = KtorReaderBootstrapGateway(
        createClient = { profile ->
            val engine = MockEngine {
                when (it.url.encodedPath) {
                    "/api/reader/v4/volumes/volume-1/bootstrap" -> respond(
                        """{"ok":true,"data":$body}""",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                    "/api/reader/v4/volumes/volume-1/comic/manifest" -> respond(
                        """{"ok":true,"data":$COMIC_MANIFEST}""",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                    else -> respondError(HttpStatusCode.NotFound)
                }
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

    private fun pdfBootstrap(units: String): String = VALID_BOOTSTRAP
        .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"pdf\"")
        .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"pdf\"")
        .replace("\"format\":\"epub\"", "\"format\":\"pdf\"")
        .replace(
            "\"kind\":\"EPUB\",\"mimeType\":\"application/epub+zip\"",
            "\"kind\":\"PDF\",\"mimeType\":\"application/pdf\"",
        )
        .replace(
            "\"volume\":{\"id\":\"volume-1\",\"title\":\"Volume\",\"format\":\"pdf\"}",
            "\"volume\":{\"id\":\"volume-1\",\"title\":\"Volume\",\"format\":\"pdf\",\"pageCount\":1}",
        )
        .replace("\"units\":[]", "\"units\":[$units]")
        .replace(REFLOWABLE_PUBLICATION, "\"publication\":null")

    private fun request() = ReaderBootstrapRequest(profile(), ReaderSyncNamespace("server-1", "user-1", 3), "volume-1")

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val EPUB_UNIT = """{"id":"pubnav-1","index":0,"title":"Chapter 1","href":"EPUB/chapter.xhtml#chapter-title","fileId":"file-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"exactNavigation":true,"hrefBase":"publication-root","level":1,"navigationKey":"EPUB/chapter.xhtml#chapter-title","path":[0],"readingOrderPosition":1}}"""
        const val PDF_UNIT = """{"id":"pdf-page-1","index":1,"title":"Page 1","href":"/private/library/book.pdf","fileId":"file-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"pageNumber":1,"sourceFileName":"book.pdf"}}"""
        const val COMIC_UNIT = """{"id":"comic-page-1","index":1,"title":"Page 1","href":"images/0001.jpg","fileId":"file-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"pageIndex":0}}"""
        const val COMIC_MANIFEST = """{"schemaVersion":1,"kind":"comic","volumeId":"volume-1","sourceFormat":"cbz","pageCount":1,"readingOrder":[{"pageIndex":0,"resourceHref":"pages/0","title":"Page 1","mediaType":"image/jpeg","width":1200,"height":1800,"sizeBytes":1234}]}"""
        const val REFLOWABLE_PUBLICATION = """"publication":{"kind":"reflowable","manifestUrl":"/api/reader/v4/volumes/volume-1/publication/manifest.json","positionsUrl":"/api/reader/v4/volumes/volume-1/publication/positions.json","renderArtifact":{"schemaVersion":1,"url":"/api/reader/v4/volumes/volume-1/publication/render.epub","mimeType":"application/epub+zip","sizeBytes":2345}}"""
        const val COMIC_PUBLICATION = """"publication":{"kind":"comic","manifestUrl":"/api/reader/v4/volumes/volume-1/comic/manifest","pageUrlTemplate":"/api/reader/v4/volumes/volume-1/comic/pages/{pageIndex}","imageVariants":["original","data-saver"],"downloadArtifact":{"url":"/api/reader/v4/volumes/volume-1/comic/archive","sourceFormat":"cbz","mimeType":"application/vnd.comicbook+zip","sizeBytes":1234}}"""
        val VALID_BOOTSTRAP = """
            {
              "schemaVersion":4,"userId":"user-1","readerType":"reflowable","sourceFormat":"epub",
              "book":{"id":"work-1","title":"Book"},
              "mediaVersion":{"id":"media-1","workId":"work-1","mediaKind":"EBOOK","completed":true},
              "volume":{"id":"volume-1","title":"Volume","format":"epub"},"availableVolumes":[],
              "files":[{"id":"file-1","kind":"EPUB","mimeType":"application/epub+zip","sizeBytes":1234,"url":"/api/files/file-1","sortOrder":0}],
              "units":[],"fileUrl":"/api/volumes/volume-1/file","capabilities":{},$REFLOWABLE_PUBLICATION,
              "progressSnapshot":{"schemaVersion":4,"clientId":"ios-client","revision":18,"locator":{"kind":"reflowable","engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"EPUB/chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title"},"text":{"highlight":"Chapter"}}}},"displayPercent":80.0,"receivedAtEpochMillis":2222}
            }
        """.trimIndent()
    }
}
