package com.ermao.library.shared.modules.downloads.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult
import com.ermao.library.shared.modules.downloads.application.DownloadByteSink
import com.ermao.library.shared.modules.downloads.application.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.application.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.application.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferResult
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

class KtorDownloadsGatewayTest {
    @Test
    fun bootstrapMapsTheMinimumDownloadContract() = runBlocking {
        val gateway = gateway { request ->
            assertTrue(request.url.encodedPath.endsWith("/api/reader/v4/volumes/volume/bootstrap"))
            respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }

        val result = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "volume"))
        assertEquals("work", result.bootstrap.descriptor.identity.workId)
        assertEquals("media", result.bootstrap.descriptor.mediaVersionId)
        assertEquals("EBOOK", result.bootstrap.descriptor.mediaKind)
        assertEquals(2, result.bootstrap.descriptor.volumeSortOrder)
        assertEquals(6, result.bootstrap.descriptor.source.totalBytes)
        Unit
    }

    @Test
    fun bootstrapRejectsContradictoryMediaVersionIdentity() = runBlocking {
        val gateway = gateway {
            respond(
                BOOTSTRAP.replace("\"mediaVersionId\":\"media\"", "\"mediaVersionId\":\"other\""),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        assertIs<DownloadBootstrapResult.Failure>(gateway.load(context, "volume"))
        Unit
    }

    @Test
    fun bootstrapMapsMobiFamilyAndRejectsTxt() = runBlocking {
        val mobi = BOOTSTRAP
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"azw3\"")
            .replace("\"format\":\"EPUB\"", "\"format\":\"AZW3\"")
            .replace("\"kind\":\"EPUB\"", "\"kind\":\"AZW3\"")
            .replace("application/epub+zip", "application/vnd.amazon.ebook")
        val mobiGateway = gateway {
            respond(mobi, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(mobiGateway.load(context, "volume"))
            .bootstrap.descriptor
        assertEquals("AZW3", descriptor.format)
        assertEquals("application/vnd.amazon.ebook", descriptor.source.mimeType)

        val txt = BOOTSTRAP
            .replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"txt\"")
            .replace("\"format\":\"EPUB\"", "\"format\":\"TXT\"")
            .replace("\"kind\":\"EPUB\"", "\"kind\":\"TXT\"")
            .replace("application/epub+zip", "text/plain")
        val txtGateway = gateway {
            respond(txt, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }
        assertIs<DownloadBootstrapResult.Failure>(txtGateway.load(context, "volume"))
        Unit
    }

    @Test
    fun bootstrapMapsComicMediaFileToExplicitArchiveDownload() = runBlocking {
        val gateway = gateway {
            respond(COMIC_BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }

        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "volume"))
            .bootstrap.descriptor

        assertEquals("CBZ", descriptor.format)
        assertEquals("COMIC", descriptor.mediaKind)
        assertEquals("/api/reader/v4/volumes/volume/comic/archive", descriptor.source.apiPath)
        assertEquals("application/vnd.comicbook+zip", descriptor.source.mimeType)
        assertEquals(12, descriptor.source.totalBytes)
        Unit
    }

    @Test
    fun transferStreamsChunksToSinkAndValidatesFull200() = runBlocking {
        var requestCount = 0
        val gateway = gateway {
            requestCount += 1
            if (requestCount == 1) {
                respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            } else {
                respond(
                    "abcdef",
                    HttpStatusCode.OK,
                    headersOf(
                        HttpHeaders.ContentType to listOf("application/epub+zip"),
                        HttpHeaders.ContentLength to listOf("6"),
                        HttpHeaders.ETag to listOf("W/\"6\""),
                    ),
                )
            }
        }
        val bootstrap = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "volume")).bootstrap
        val sink = RecordingSink()
        val progress = mutableListOf<Long>()

        val result = gateway.transfer(
            context,
            DownloadTransferRequest("task", bootstrap.descriptor),
            sink,
        ) { transferred, _ -> progress += transferred }

        assertIs<DownloadTransferResult.Success>(result)
        assertContentEquals("abcdef".encodeToByteArray(), sink.bytes)
        assertEquals(6, progress.last())
        assertEquals(1, sink.commitCount)
        assertEquals(0, sink.abortCount)
        Unit
    }

    @Test
    fun resumeRequiresMatching206ContentRange() = runBlocking {
        var requestCount = 0
        val gateway = gateway { request ->
            requestCount += 1
            if (requestCount == 1) {
                respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            } else {
                assertEquals("bytes=2-", request.headers[HttpHeaders.Range])
                respond(
                    "cdef",
                    HttpStatusCode.PartialContent,
                    headersOf(
                        HttpHeaders.ContentLength to listOf("4"),
                        HttpHeaders.ContentRange to listOf("bytes 2-5/6"),
                    ),
                )
            }
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "volume")).bootstrap.descriptor
        val result = gateway.transfer(context, DownloadTransferRequest("task", descriptor, 2), RecordingSink())
        assertIs<DownloadTransferResult.Success>(result)
        Unit
    }

    @Test
    fun invalidLengthAbortsAndNeverCommits() = runBlocking {
        var requestCount = 0
        val gateway = gateway {
            requestCount += 1
            if (requestCount == 1) {
                respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            } else {
                respond("abc", HttpStatusCode.OK, headersOf(HttpHeaders.ContentLength, "3"))
            }
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "volume")).bootstrap.descriptor
        val sink = RecordingSink()

        assertIs<DownloadTransferResult.Failure>(
            gateway.transfer(context, DownloadTransferRequest("task", descriptor), sink),
        )
        assertEquals(0, sink.commitCount)
        assertEquals(0, sink.abortCount)
        Unit
    }

    @Test
    fun cancellationAbortsSinkAndPropagates() = runBlocking {
        var requestCount = 0
        val gateway = gateway {
            requestCount += 1
            if (requestCount == 1) {
                respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            } else {
                throw CancellationException("cancel")
            }
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "volume")).bootstrap.descriptor
        val sink = RecordingSink()

        assertFailsWith<CancellationException> {
            gateway.transfer(context, DownloadTransferRequest("task", descriptor), sink)
        }
        // The request was cancelled before a sink transaction existed.
        assertEquals(0, sink.abortCount)
        Unit
    }

    private fun gateway(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): KtorDownloadsGateway =
        KtorDownloadsGateway(ApiClient(profile, HttpClient(MockEngine(handler)), Json { ignoreUnknownKeys = false }))

    private val namespace = DownloadNamespace("server", "user", 1)
    private val profile = ServerProfile(
        "profile",
        "Books",
        (ServerBaseUrl.parse("https://books.example/base") as ServerBaseUrlParseResult.Valid).baseUrl,
        "server",
        true,
        TlsMode.SystemTrust,
    )
    private val context = DownloadRequestContext(profile, namespace)

    private class RecordingSink : DownloadByteSink, DownloadByteSinkSession {
        var bytes = byteArrayOf()
        var commitCount = 0
        var abortCount = 0

        override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession = this
        override suspend fun write(bytes: ByteArray) {
            this.bytes += bytes
        }
        override suspend fun commit(expectedTotalBytes: Long): String {
            commitCount += 1
            return "local://volume"
        }
        override suspend fun abort() {
            abortCount += 1
        }
    }

    private companion object {
        const val BOOTSTRAP = """{"ok":true,"data":{"schemaVersion":4,"userId":"user","readerType":"reflowable","sourceFormat":"epub","book":{"id":"work","title":"Book","author":"Author","coverUrl":"/api/works/work/cover"},"mediaVersion":{"id":"media","workId":"work","mediaKind":"EBOOK","completed":false},"volume":{"id":"volume","mediaVersionId":"media","title":"Volume","volumeIndex":1.5,"sortOrder":2,"format":"EPUB","readerType":"reflowable"},"files":[{"id":"file","kind":"EPUB","mimeType":"application/epub+zip","sizeBytes":6,"url":"/api/files/file","sortOrder":0}],"fileUrl":"/api/volumes/volume/file"}}"""
        const val COMIC_BOOTSTRAP = """{"ok":true,"data":{"schemaVersion":4,"userId":"user","readerType":"comic","sourceFormat":"cbz","book":{"id":"work","title":"Comic","author":"Author","coverUrl":"/api/works/work/cover"},"mediaVersion":{"id":"media","workId":"work","mediaKind":"COMIC","completed":false},"volume":{"id":"volume","mediaVersionId":"media","title":"Volume","volumeIndex":1.0,"sortOrder":0,"format":"CBZ","readerType":"comic"},"files":[{"id":"file","kind":"COMIC","mimeType":"application/vnd.comicbook+zip","sizeBytes":12,"url":"/api/files/file","sortOrder":0}],"fileUrl":"/api/volumes/volume/file","publication":{"kind":"comic","manifestUrl":"/api/reader/v4/volumes/volume/comic/manifest","pageUrlTemplate":"/api/reader/v4/volumes/volume/comic/pages/{pageIndex}","imageVariants":["original"],"downloadArtifact":{"url":"/api/reader/v4/volumes/volume/comic/archive","sourceFormat":"cbz","mimeType":"application/vnd.comicbook+zip","sizeBytes":12}}}}"""
    }
}
