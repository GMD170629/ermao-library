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
    fun mapsResourceIdentityAndLightweightReflowableBootstrap() = runBlocking {
        val content = assertIs<Content>(gateway(VALID_BOOTSTRAP).load(request())).value

        assertEquals("resource-1", content.target.resourceId)
        assertEquals("book-1", content.target.bookId)
        assertEquals("asset-1", content.resource.assetId)
        assertEquals(18, content.remoteSnapshot?.revision)
        assertEquals(2_222, content.remoteSnapshot?.receivedAtEpochMillis)
        assertEquals(ReaderEnginePlatform.Ios, content.remoteSnapshot?.locator?.platform)
    }

    @Test
    fun acceptsAndOrdersFixedLayoutResourceUnits() = runBlocking {
        val later = PDF_UNIT
            .replace("pdf-page-1", "pdf-page-3")
            .replace("\"index\":0", "\"index\":2")
            .replace("\"title\":\"Page 1\"", "\"title\":\"   \"")
        val response = pdfBootstrap().replace(
            PDF_UNITS,
            "\"units\":[$later,$PDF_UNIT]",
        )

        val content = assertIs<Content>(gateway(response).load(request())).value

        assertEquals(listOf("pdf-page-1", "pdf-page-3"), content.units.map { it.id })
        assertEquals(listOf("Page 1", "pdf-page-3"), content.units.map { it.title })
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
    }

    @Test
    fun rejectsBootstrapForAnotherAuthenticatedUser() = runBlocking {
        val response = comicBootstrap().replace("\"userId\":\"user-1\"", "\"userId\":\"user-2\"")
        var comicManifestRequests = 0

        val failure = assertIs<Failure>(gateway(response) { comicManifestRequests += 1 }.load(request()))

        assertEquals("READER_BOOTSTRAP_USER_MISMATCH", failure.failureCode)
        assertEquals(0, comicManifestRequests)
    }

    @Test
    fun rejectsDisguisedMorphologiesBeforeComicManifestRequest() = runBlocking {
        val topLevelIdentity = "\"readerType\":\"reflowable\",\"sourceFormat\":\"epub\""
        val responses = listOf(
            "reflowable source advertised as comic" to VALID_BOOTSTRAP
                .replace(topLevelIdentity, "\"readerType\":\"comic\",\"sourceFormat\":\"epub\"")
                .replace(REFLOWABLE_PUBLICATION, COMIC_PUBLICATION),
            "comic source backed by reflowable resource" to VALID_BOOTSTRAP
                .replace(topLevelIdentity, "\"readerType\":\"comic\",\"sourceFormat\":\"cbz\"")
                .replace(REFLOWABLE_PUBLICATION, COMIC_PUBLICATION),
            "non-canonical comic source format" to comicBootstrap()
                .replace("\"sourceFormat\":\"cbz\"", "\"sourceFormat\":\"CBZ\""),
            "non-canonical comic resource format" to comicBootstrap()
                .replace("\"format\":\"CBZ\"", "\"format\":\"cbz\""),
            "non-canonical comic resource reader type" to comicBootstrap().replace(
                "\"format\":\"CBZ\",\"readerType\":\"comic\"",
                "\"format\":\"CBZ\",\"readerType\":\"Comic\"",
            ),
        )

        responses.forEach { (caseName, response) ->
            var comicManifestRequests = 0

            assertIs<Failure>(gateway(response) { comicManifestRequests += 1 }.load(request()))

            assertEquals(0, comicManifestRequests, caseName)
        }
    }

    @Test
    fun rejectsIdentityMismatchesBeforeComicManifestRequest() = runBlocking {
        val bootstrap = comicBootstrap()
        val responses = listOf(
            "requested resource" to bootstrap
                .replace(
                    "\"id\":\"resource-1\",\"bookId\":\"book-1\",\"sourceNodeId\":\"node-1\"",
                    "\"id\":\"resource-2\",\"bookId\":\"book-1\",\"sourceNodeId\":\"node-1\"",
                )
                .replace("/resources/resource-1/comic", "/resources/resource-2/comic"),
            "book" to bootstrap.replace(
                "\"bookId\":\"book-1\",\"sourceNodeId\":\"node-1\",\"title\":\"Resource\"",
                "\"bookId\":\"book-2\",\"sourceNodeId\":\"node-1\",\"title\":\"Resource\"",
            ),
            "asset owner" to bootstrap.replace(
                "\"resourceId\":\"resource-1\",\"sourceNodeId\":\"node-1\",\"role\":\"PRIMARY\"",
                "\"resourceId\":\"resource-2\",\"sourceNodeId\":\"node-1\",\"role\":\"PRIMARY\"",
            ),
            "unit asset" to bootstrap.replace("\"assetId\":\"asset-1\"", "\"assetId\":\"asset-2\""),
            "resource url" to bootstrap.replace(
                "\"resourceUrl\":\"/api/resources/resource-1\"",
                "\"resourceUrl\":\"/api/resources/resource-2\"",
            ),
        )

        responses.forEach { (caseName, response) ->
            var comicManifestRequests = 0

            val failure = assertIs<Failure>(gateway(response) { comicManifestRequests += 1 }.load(request()))

            assertEquals("READER_BOOTSTRAP_IDENTITY_MISMATCH", failure.failureCode, caseName)
            assertEquals(0, comicManifestRequests, caseName)
        }
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
                .replace("\"format\":\"EPUB\"", "\"format\":\"${wireFormat.uppercase()}\"")
                .replace("application/epub+zip", mimeType)

            val content = assertIs<Content>(gateway(response).load(request())).value

            assertEquals(readerFormat, content.target.sourceFormat)
            assertEquals(wireFormat, content.resource.sourceFormat.wireValue)
        }
    }

    @Test
    fun rejectsRetiredReflowablePublicationAccess() = runBlocking {
        val response = VALID_BOOTSTRAP.replace(
            REFLOWABLE_PUBLICATION,
            """"publication":{"kind":"reflowable","manifestUrl":"/api/reader/v4/resources/resource-1/publication/manifest.json","positionsUrl":"/api/reader/v4/resources/resource-1/publication/positions.json"}""",
        )

        assertEquals(
            "READER_BOOTSTRAP_INVALID",
            assertIs<Failure>(gateway(response).load(request())).failureCode,
        )
    }

    @Test
    fun mapsPdfAndComicResourceContracts() = runBlocking {
        val pdf = pdfBootstrap()
        val pdfContent = assertIs<Content>(gateway(pdf).load(request())).value
        assertEquals(ReaderFormat.Pdf, pdfContent.target.sourceFormat)
        assertEquals("Page 1", pdfContent.pdfPages.single().title)
        assertEquals(0, pdfContent.pdfPages.single().pageIndex)

        var comicManifestRequests = 0
        val comicContent = assertIs<Content>(
            gateway(comicBootstrap()) { comicManifestRequests += 1 }.load(request()),
        ).value
        assertEquals(ReaderFormat.Comic, comicContent.target.sourceFormat)
        assertEquals("pages/0", comicContent.comicPages.single().resourceHref)
        assertEquals("/api/reader/v4/resources/resource-1/comic/manifest", comicContent.comicAccess?.manifestApiPath)
        assertEquals(1, comicManifestRequests)
    }

    @Test
    fun imageDirectoryUsesOnlineManifestWithoutPretendingFirstPageIsPublication() = runBlocking {
        val imageDirectory = VALID_BOOTSTRAP
            .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"comic\"")
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"image_dir\"")
            .replace("\"format\":\"EPUB\"", "\"format\":\"IMAGE_DIR\"")
            .replace("application/epub+zip", "image/png")
            .replace("\"units\":[]", COMIC_UNITS)
            .replace(REFLOWABLE_PUBLICATION, IMAGE_DIRECTORY_PUBLICATION)

        val content = assertIs<Content>(gateway(imageDirectory).load(request())).value

        assertEquals("image_dir", content.resource.sourceFormat.wireValue)
        assertEquals(ReaderFormat.Comic, content.target.sourceFormat)
        assertNull(content.resource.assetId)
    }

    @Test
    fun rejectsUnsupportedAndMismatchedAssets() = runBlocking {
        val fb2 = VALID_BOOTSTRAP
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"fb2\"")
            .replace("\"format\":\"EPUB\"", "\"format\":\"FB2\"")
            .replace("application/epub+zip", "application/x-fictionbook+xml")
        val fb2Content = assertIs<Content>(gateway(fb2).load(request())).value
        assertEquals("fb2", fb2Content.resource.sourceFormat.wireValue)

        val mismatched = VALID_BOOTSTRAP.replace(
            "\"mimeType\":\"application/epub+zip\"",
            "\"mimeType\":\"application/x-mobipocket-ebook\"",
        )
        assertEquals(
            "READER_PUBLICATION_ASSET_INVALID",
            assertIs<Failure>(gateway(mismatched).load(request())).failureCode,
        )
    }

    private fun pdfBootstrap(): String = VALID_BOOTSTRAP
        .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"pdf\"")
        .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"pdf\"")
        .replace("\"format\":\"EPUB\"", "\"format\":\"PDF\"")
        .replace("application/epub+zip", "application/pdf")
        .replace("\"pageCount\":null", "\"pageCount\":1")
        .replace("\"units\":[]", PDF_UNITS)

    private fun comicBootstrap(): String = VALID_BOOTSTRAP
        .replace("\"readerType\":\"reflowable\"", "\"readerType\":\"comic\"")
        .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"cbz\"")
        .replace("\"format\":\"EPUB\"", "\"format\":\"CBZ\"")
        .replace("application/epub+zip", "application/vnd.comicbook+zip")
        .replace("\"units\":[]", COMIC_UNITS)
        .replace(REFLOWABLE_PUBLICATION, COMIC_PUBLICATION)

    private fun gateway(
        body: String,
        onComicManifestRequest: () -> Unit = {},
    ) = KtorReaderBootstrapGateway(
        createClient = { profile ->
            val comicManifest = if (body.contains("\"sourceFormat\":\"image_dir\"")) {
                IMAGE_DIRECTORY_MANIFEST
            } else {
                COMIC_MANIFEST
            }
            val engine = MockEngine {
                when {
                    it.url.encodedPath == "/api/reader/v4/resources/resource-1/bootstrap" -> respond(
                        "{\"ok\":true,\"data\":$body}",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                    it.url.encodedPath.endsWith("/comic/manifest") -> {
                        onComicManifestRequest()
                        respond(
                            "{\"ok\":true,\"data\":$comicManifest}",
                            HttpStatusCode.OK,
                            headersOf(HttpHeaders.ContentType, "application/json"),
                        )
                    }
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
        const val PDF_UNIT = """{"id":"pdf-page-1","index":0,"title":"Page 1","href":"page-1","assetId":"asset-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"pageNumber":1}}"""
        const val PDF_UNITS = """"units":[$PDF_UNIT]"""
        const val COMIC_UNITS = """"units":[{"id":"comic-page-1","index":0,"title":"Page 1","href":"pages/0","assetId":"asset-1","startMs":null,"endMs":null,"durationMs":null,"metadata":{"pageIndex":0}}]"""
        const val COMIC_MANIFEST = """{"schemaVersion":1,"kind":"comic","resourceId":"resource-1","sourceFormat":"cbz","pageCount":1,"readingOrder":[{"pageIndex":0,"resourceHref":"pages/0","title":"Page 1","mediaType":"image/jpeg","width":1200,"height":1800,"sizeBytes":1234}]}"""
        const val IMAGE_DIRECTORY_MANIFEST = """{"schemaVersion":1,"kind":"comic","resourceId":"resource-1","sourceFormat":"image_dir","pageCount":1,"readingOrder":[{"pageIndex":0,"resourceHref":"pages/0","title":"Page 1","mediaType":"image/png","width":1200,"height":1800,"sizeBytes":1234}]}"""
        const val REFLOWABLE_PUBLICATION = """"publication":null"""
        const val COMIC_PUBLICATION = """"publication":{"kind":"comic","manifestUrl":"/api/reader/v4/resources/resource-1/comic/manifest","pageUrlTemplate":"/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}","imageVariants":["original","data-saver"]}"""
        const val IMAGE_DIRECTORY_PUBLICATION = """"publication":{"kind":"comic","manifestUrl":"/api/reader/v4/resources/resource-1/comic/manifest","pageUrlTemplate":"/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}","imageVariants":["original","data-saver"]}"""
        val VALID_BOOTSTRAP = """
            {
              "schemaVersion":4,"userId":"user-1","readerType":"reflowable","sourceFormat":"epub",
              "book":{"id":"book-1","title":"Book","author":"Author","coverUrl":"/api/books/book-1/cover"},
              "resource":{"id":"resource-1","bookId":"book-1","sourceNodeId":"node-1","title":"Resource","resourceIndex":1.0,"sortOrder":0,"format":"EPUB","readerType":"reflowable","pageCount":null,"chapterCount":1,"durationMs":null,"trackCount":null,"progress":0.0,"resourceCompleted":false,"lastReadAt":null},
              "availableResources":[],
              "assets":[{"id":"asset-1","title":"Resource","resourceId":"resource-1","sourceNodeId":"node-1","role":"PRIMARY","mimeType":"application/epub+zip","sizeBytes":1234,"durationMs":null,"discNumber":null,"trackNumber":null,"sortOrder":0,"url":"/api/assets/asset-1","codec":null}],
              "units":[],"resourceUrl":"/api/resources/resource-1","capabilities":{},$REFLOWABLE_PUBLICATION,
              "progressSnapshot":{"schemaVersion":4,"clientId":"ios-client","revision":18,"locator":{"kind":"reflowable","engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"EPUB/chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title"},"text":{"highlight":"Chapter"}}}},"displayPercent":80.0,"receivedAtEpochMillis":2222}
            }
        """.trimIndent()
    }
}
