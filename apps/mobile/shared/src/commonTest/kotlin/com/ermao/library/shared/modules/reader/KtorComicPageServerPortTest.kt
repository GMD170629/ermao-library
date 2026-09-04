package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.ComicPageReadResult
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.domain.RemoteComicPage
import com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource
import com.ermao.library.shared.modules.reader.infrastructure.KtorComicPageServerPort
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.client.engine.mock.respond
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class KtorComicPageServerPortTest {
    @Test
    fun sendsManifestRevisionOnEveryPageRequestAndChecksResponseRevision() = runBlocking {
        val port = port { request ->
            assertEquals("/api/reader/v5/resources/resource-1/comic/pages/0", request.url.encodedPath)
            assertEquals(REVISION, request.url.parameters["revision"])
            assertEquals("original", request.url.parameters["imageVariant"])
            respond(
                content = byteArrayOf(1, 2, 3),
                status = HttpStatusCode.OK,
                headers = headersOf(
                    HttpHeaders.ContentType to listOf(ContentType.Image.JPEG.toString()),
                    HttpHeaders.ContentLength to listOf("3"),
                    "X-Comic-Revision" to listOf(REVISION),
                ),
            )
        }

        val result = assertIs<ComicPageReadResult.Content>(
            port.read(source(), 0, ReaderComicImageVariant.Original),
        )
        assertEquals(0, result.pageIndex)
    }

    @Test
    fun missingOrChangedResponseRevisionIsAStablePublicationChange() = runBlocking {
        val missing = assertIs<ComicPageReadResult.Failure>(
            port { request ->
                respond(
                    content = byteArrayOf(1),
                    status = HttpStatusCode.OK,
                    headers = headersOf(
                        HttpHeaders.ContentType to listOf(ContentType.Image.JPEG.toString()),
                        HttpHeaders.ContentLength to listOf("1"),
                    ),
                )
            }.read(source(), 0, ReaderComicImageVariant.Original),
        )
        assertEquals("COMIC_RESOURCE_CHANGED", missing.code)
        assertEquals("PUBLICATION_CHANGED", missing.readerError.code.wireValue)

        val changed = assertIs<ComicPageReadResult.Failure>(
            port {
                respond(
                    content = byteArrayOf(1),
                    status = HttpStatusCode.OK,
                    headers = headersOf(
                        HttpHeaders.ContentType to listOf(ContentType.Image.JPEG.toString()),
                        HttpHeaders.ContentLength to listOf("1"),
                        "X-Comic-Revision" to listOf(OTHER_REVISION),
                    ),
                )
            }.read(source(), 0, ReaderComicImageVariant.Original),
        )
        assertEquals("COMIC_RESOURCE_CHANGED", changed.code)
    }

    @Test
    fun mapsPreconditionFailureWithoutReadingAnUntrustedBody() = runBlocking {
        val failure = assertIs<ComicPageReadResult.Failure>(
            port {
                respond(
                    content = byteArrayOf(),
                    status = HttpStatusCode.PreconditionFailed,
                    headers = headersOf("X-Error-Code" to listOf("COMIC_RESOURCE_CHANGED")),
                )
            }.read(source(), 0, ReaderComicImageVariant.DataSaver),
        )
        assertEquals("COMIC_RESOURCE_CHANGED", failure.code)
    }

    private fun port(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ) = KtorComicPageServerPort(
        profile = profile(),
        createClient = { profile ->
            ApiClient(profile, HttpClient(MockEngine(handler)), Json { ignoreUnknownKeys = false })
        },
    )

    private fun source() = RemoteComicReaderSource(
        resourceId = "resource-1",
        displayTitle = "Comic",
        bookId = "book-1",
        assetId = "asset-1",
        namespace = ReaderSyncNamespace("server-1", "user-1", 3),
        sourceFormat = ReaderSourceFormat.Cbz,
        manifestApiPath = "/api/reader/v5/resources/resource-1/comic/manifest",
        pageApiPathTemplate = "/api/reader/v5/resources/resource-1/comic/pages/{pageIndex}",
        revision = REVISION,
        pages = listOf(RemoteComicPage(0, "pages/0", "image/jpeg", 1200, 1800)),
    )

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
    }

    private companion object {
        const val REVISION = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        const val OTHER_REVISION = "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    }
}
