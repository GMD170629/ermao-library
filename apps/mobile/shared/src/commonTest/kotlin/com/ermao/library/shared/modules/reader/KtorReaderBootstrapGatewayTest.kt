package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Content
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult.Failure
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
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
    fun mapsResourceAndPrimaryAssetToOriginalPublication() = runBlocking {
        val content = assertIs<Content>(gateway(VALID_BOOTSTRAP).load(request())).value

        assertEquals("resource-1", content.target.resourceId)
        assertEquals("book-1", content.target.bookId)
        assertEquals("/api/assets/asset-1", content.publication.apiPath)
        assertEquals(1_234, content.publication.expectedSizeBytes)
        assertEquals("asset-1", content.publication.assetId)
        assertEquals(18, content.remoteSnapshot?.revision)
        assertEquals(2_222, content.remoteSnapshot?.receivedAtEpochMillis)
        assertEquals(ReaderEnginePlatform.Ios, content.remoteSnapshot?.locator?.platform)
    }

    @Test
    fun acceptsAndOrdersResourceUnits() = runBlocking {
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
        assertEquals("asset-1", content.units.first().assetId)
    }

    @Test
    fun malformedProgressSnapshotDoesNotBlockPublicationBootstrap() = runBlocking {
        val mismatch = VALID_BOOTSTRAP.replace(
            "\"locations\":{\"cssSelector\":\"#chapter-title\"},\"text\":{\"highlight\":\"Chapter\"}",
            "\"locations\":{\"progression\":0.8}",
        )

        val content = assertIs<Content>(gateway(mismatch).load(request())).value

        assertNull(content.remoteSnapshot)
        assertEquals("/api/assets/asset-1", content.publication.apiPath)
    }

    @Test
    fun rejectsBootstrapForAnotherAuthenticatedUser() = runBlocking {
        val response = VALID_BOOTSTRAP.replace("\"userId\":\"user-1\"", "\"userId\":\"user-2\"")

        val failure = assertIs<Failure>(gateway(response).load(request()))

        assertEquals("READER_BOOTSTRAP_USER_MISMATCH", failure.failureCode)
    }

    @Test
    fun mapsMobiFamilyAndTextFormatsToTheirReaderFormats() = runBlocking {
        val variants = listOf(
            Triple("mobi", "application/x-mobipocket-ebook", ReaderFormat.Mobi),
            Triple("txt", "text/plain", ReaderFormat.Text),
        )
        variants.forEach { (wireFormat, mimeType, readerFormat) ->
            val response = VALID_BOOTSTRAP
                .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"$wireFormat\"")
                .replace("\"format\":\"epub\"", "\"format\":\"$wireFormat\"")
                .replace("application/epub+zip", mimeType)

            val content = assertIs<Content>(gateway(response).load(request())).value

            assertEquals(readerFormat, content.target.sourceFormat)
            assertEquals(wireFormat, content.publication.sourceFormat.wireValue)
            assertEquals(mimeType, content.publication.mimeType)
        }
    }

    @Test
    fun mapsPdfAndComicResourceContracts() = runBlocking {
        val pdf = VALID_BOOTSTRAP
            .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"pdf\"")
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"pdf\"")
            .replace("\"format\":\"epub\"", "\"format\":\"pdf\"")
            .replace("application/epub+zip", "application/pdf")
            .replace("\"pageCount\":null", "\"pageCount\":1")
            .replace("\"units\":[]", PDF_UNITS)
            .replace(REFLOWABLE_PUBLICATION, "\"publication\":null")
        val pdfContent = assertIs<Content>(gateway(pdf).load(request())).value
        assertEquals(ReaderFormat.Pdf, pdfContent.target.sourceFormat)
        assertEquals("Page 1", pdfContent.pdfPages.single().title)
        assertEquals(0, pdfContent.pdfPages.single().pageIndex)

        val comic = VALID_BOOTSTRAP
            .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"comic\"")
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"cbz\"")
            .replace("\"format\":\"epub\"", "\"format\":\"cbz\"")
            .replace("application/epub+zip", "application/vnd.comicbook+zip")
            .replace("\"units\":[]", COMIC_UNITS)
            .replace(REFLOWABLE_PUBLICATION, COMIC_PUBLICATION)
        val comicContent = assertIs<Content>(gateway(comic).load(request())).value
        assertEquals(ReaderFormat.Comic, comicContent.target.sourceFormat)
        assertEquals("pages/0", comicContent.comicPages.single().resourceHref)
        assertEquals("/api/assets/asset-1", comicContent.publication.apiPath)
    }

    @Test
    fun rejectsUnsupportedAndMismatchedAssets() = runBlocking {
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
            "READER_PUBLICATION_ASSET_INVALID",
            assertIs<Failure>(gateway(mismatched).load(request())).failureCode,
        )
    }

    private fun gateway(body: String) = KtorReaderBootstrapGateway(
        createClient = { profile ->
            val engine = MockEngine {
                when (it.url.encodedPath) {
                    "/api/reader/v4/resources/resource-1/bootstrap" -> respond(
                        "{\"ok\":true,\"data\":$body}",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                    "/api/reader/v4/resources/resource-1/comic/manifest" -> respond(
                        "{\"ok\":true,\"data\":$COMIC_MANIFEST}",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                    else -> respondError(HttpStatusCode.NotFound)
                }
            }
            ApiClient(profile, HttpClient(engine), Json { ignoreUnknownKeys = false; explicitNulls = false })
        },
    )

    private fun request() = ReaderBootstrapRequest(profile(), ReaderSyncNamespace("server-1", "user-1", 3), "resource-1")

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val EPUB_UNIT = """{"id":"pubnav-1","index":0,"title":"Chapter 1","href":"EPUB/chapter.xhtml#chapter-title","assetId":"asset-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"exactNavigation":true,"hrefBase":"publication-root","level":1,"navigationKey":"EPUB/chapter.xhtml#chapter-title","path":[0],"readingOrderPosition":1}}"""
        const val PDF_UNITS = """"units":[{"id":"pdf-page-1","index":0,"title":"Page 1","href":"page-1","assetId":"asset-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"pageNumber":1}}]"""
        const val COMIC_UNITS = """"units":[{"id":"comic-page-1","index":0,"title":"Page 1","href":"pages/0","assetId":"asset-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"pageIndex":0}}]"""
        const val COMIC_MANIFEST = """{"schemaVersion":1,"kind":"comic","resourceId":"resource-1","sourceFormat":"cbz","pageCount":1,"readingOrder":[{"pageIndex":0,"resourceHref":"pages/0","title":"Page 1","mediaType":"image/jpeg","width":1200,"height":1800,"sizeBytes":1234}]}"""
        const val REFLOWABLE_PUBLICATION = """"publication":{"kind":"reflowable","manifestUrl":"/api/reader/v4/resources/resource-1/publication/manifest.json","positionsUrl":"/api/reader/v4/resources/resource-1/publication/positions.json"}"""
        const val COMIC_PUBLICATION = """"publication":{"kind":"comic","manifestUrl":"/api/reader/v4/resources/resource-1/comic/manifest","pageUrlTemplate":"/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}","imageVariants":["original","data-saver"],"downloadArtifact":{"url":"/api/reader/v4/resources/resource-1/comic/archive","sourceFormat":"cbz","mimeType":"application/vnd.comicbook+zip","sizeBytes":1234}}"""
        val VALID_BOOTSTRAP = """
            {
              "schemaVersion":4,"userId":"user-1","readerType":"reflowable","sourceFormat":"epub",
              "book":{"id":"book-1","title":"Book","author":"Author","coverUrl":"/api/books/book-1/cover"},
              "resource":{"id":"resource-1","bookId":"book-1","sourceNodeId":"node-1","title":"Resource","resourceIndex":1.0,"sortOrder":0,"format":"epub","mediaKind":"BOOK","readerType":"reflowable","pageCount":null,"chapterCount":1,"durationMs":null,"trackCount":null,"progress":0.0,"resourceCompleted":false,"lastReadAt":null},
              "availableResources":[],
              "assets":[{"id":"asset-1","resourceId":"resource-1","sourceNodeId":"node-1","role":"PRIMARY","mimeType":"application/epub+zip","sizeBytes":1234,"durationMs":null,"discNumber":null,"trackNumber":null,"sortOrder":0,"url":"/api/assets/asset-1","codec":null}],
              "units":[],"resourceUrl":"/api/resources/resource-1","capabilities":{},$REFLOWABLE_PUBLICATION,
              "progressSnapshot":{"schemaVersion":4,"clientId":"ios-client","revision":18,"locator":{"kind":"reflowable","engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"EPUB/chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title"},"text":{"highlight":"Chapter"}}}},"displayPercent":80.0,"receivedAtEpochMillis":2222}
            }
        """.trimIndent()
    }
}
