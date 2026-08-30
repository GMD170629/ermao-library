package com.ermao.library.shared.modules.downloads.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult
import com.ermao.library.shared.modules.downloads.application.DownloadByteSink
import com.ermao.library.shared.modules.downloads.application.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.application.DownloadBundleByteSink
import com.ermao.library.shared.modules.downloads.application.DownloadBundleByteSinkSession
import com.ermao.library.shared.modules.downloads.application.DownloadBundleMemberSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadBundleSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.application.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferResult
import com.ermao.library.shared.modules.downloads.domain.DownloadArtifactKind
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.engine.mock.respondError
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

class KtorDownloadsGatewayTest {
    @Test
    fun bootstrapMapsBookResourceAndPrimaryAsset() = runBlocking {
        val gateway = gateway { request ->
            assertTrue(request.url.encodedPath.endsWith("/api/resources/resource"))
            respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }

        val loaded = gateway.load(context, "resource")
        val result = assertIs<DownloadBootstrapResult.Success>(loaded)
        val descriptor = result.bootstrap.descriptor
        assertEquals("book", descriptor.identity.bookId)
        assertEquals("resource", descriptor.identity.resourceId)
        assertEquals("asset", descriptor.identity.assetId)
        assertEquals("/api/assets/asset", descriptor.source.apiPath)
        assertEquals(2, descriptor.resourceSortOrder)
        assertEquals(6, descriptor.source.totalBytes)
        Unit
    }

    @Test
    fun bootstrapRejectsContradictoryResourceAndAssetIdentity() = runBlocking {
        val gateway = gateway {
            respond(
                BOOTSTRAP.replace("\"resourceId\":\"resource\"", "\"resourceId\":\"other\""),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        assertIs<DownloadBootstrapResult.Failure>(gateway.load(context, "resource"))
        Unit
    }

    @Test
    fun bootstrapRejectsGenericBinaryMimeEvenForKnownOriginalFormat() = runBlocking {
        val gateway = gateway {
            respond(
                BOOTSTRAP.replace("application/epub+zip", "application/octet-stream"),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        assertIs<DownloadBootstrapResult.Failure>(gateway.load(context, "resource"))
        Unit
    }

    @Test
    fun bootstrapRejectsAssetMimeThatDoesNotMatchItsExactSourceFormat() = runBlocking {
        val gateway = gateway {
            respond(
                BOOTSTRAP.replace("\"sourceFormat\":\"epub\"", "\"sourceFormat\":\"fb2\""),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        assertIs<DownloadBootstrapResult.Failure>(gateway.load(context, "resource"))
        Unit
    }

    @Test
    fun genericBinaryMimeDoesNotBypassOriginalFormatOrSafePathChecks() = runBlocking {
        val unsupportedFormat = BOOTSTRAP
            .replace("\"format\":\"epub\"", "\"format\":\"exe\"")
            .replace("application/epub+zip", "application/octet-stream")
        val unsafePath = BOOTSTRAP
            .replace("application/epub+zip", "application/octet-stream")
            .replace("/api/assets/asset", "https://evil.example/asset")

        assertIs<DownloadBootstrapResult.Failure>(gateway { respond(unsupportedFormat) }.load(context, "resource"))
        assertIs<DownloadBootstrapResult.Failure>(gateway { respond(unsafePath) }.load(context, "resource"))
        Unit
    }

    @Test
    fun bootstrapMapsComicResourceToPrimaryAssetDownload() = runBlocking {
        val gateway = gateway {
            respond(COMIC_BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }

        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource"))
            .bootstrap.descriptor

        assertEquals("cbz", descriptor.format)
        assertEquals("asset", descriptor.identity.assetId)
        assertEquals("/api/assets/asset", descriptor.source.apiPath)
        assertEquals("application/vnd.comicbook+zip", descriptor.source.mimeType)
        assertEquals(12, descriptor.source.totalBytes)
        Unit
    }

    @Test
    fun imageDirectoryBuildsAnOriginalPageSetWithoutAdvertisingAnArchive() = runBlocking {
        val imageDirectory = COMIC_BOOTSTRAP
            .replace("\"sourceFormat\":\"cbz\"", "\"sourceFormat\":\"image_dir\"")
            .replace("\"format\":\"cbz\"", "\"format\":\"image_dir\"")
            .replace("application/vnd.comicbook+zip", "image/png")
            .replace("\"role\":\"PRIMARY\"", "\"role\":\"PAGE\"")

        val gateway = gateway {
            respond(imageDirectory, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
        }

        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource"))
            .bootstrap.descriptor

        assertTrue(descriptor.isDownloadable)
        assertEquals("image_dir", descriptor.format)
        assertEquals("image/png", descriptor.source.mimeType)
        assertEquals(DownloadArtifactKind.OriginalPageSet, descriptor.artifactKind)
        assertEquals(listOf("asset"), descriptor.bundleMembers.map { it.assetId })
        Unit
    }

    @Test
    fun imageDirectoryTransfersEveryOriginalPageBeforeAtomicallyCommittingBundle() = runBlocking {
        val firstAsset = """{"id":"page-a","title":"Page 1","resourceId":"resource","sourceNodeId":"node","role":"PAGE","sourceFormat":"image_dir","mimeType":"image/png","sizeBytes":3,"sortOrder":0,"url":"/api/assets/page-a"}"""
        val secondAsset = """{"id":"page-b","title":"Page 2","resourceId":"resource","sourceNodeId":"node","role":"PAGE","sourceFormat":"image_dir","mimeType":"image/jpeg","sizeBytes":4,"sortOrder":1,"url":"/api/assets/page-b"}"""
        val originalAsset = """{"id":"asset","title":"Page 1","resourceId":"resource","sourceNodeId":"node","role":"PRIMARY","sourceFormat":"image_dir","mimeType":"application/vnd.comicbook+zip","sizeBytes":12,"sortOrder":0,"url":"/api/assets/asset"}"""
        val imageDirectory = COMIC_BOOTSTRAP
            .replace("\"sourceFormat\":\"cbz\"", "\"sourceFormat\":\"image_dir\"")
            .replace("\"format\":\"cbz\"", "\"format\":\"image_dir\"")
            .replace(originalAsset, "$firstAsset,$secondAsset")

        val gateway = gateway { request ->
            when (request.url.encodedPath) {
                "/base/api/resources/resource" -> respond(
                    imageDirectory,
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
                "/base/api/assets/page-a" -> respond(
                    "abc",
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType to listOf("image/png"), HttpHeaders.ContentLength to listOf("3")),
                )
                "/base/api/assets/page-b" -> respond(
                    "defg",
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType to listOf("image/jpeg"), HttpHeaders.ContentLength to listOf("4")),
                )
                else -> respondError(HttpStatusCode.NotFound)
            }
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource"))
            .bootstrap.descriptor
        val sink = RecordingBundleSink()
        val progress = mutableListOf<Long>()

        val result = gateway.transfer(
            context,
            DownloadTransferRequest("page-set-task", descriptor),
            sink,
        ) { transferred, _ -> progress += transferred }

        val completed = assertIs<DownloadTransferResult.Success>(result).transfer
        assertEquals("local://page-set", completed.localReference)
        assertEquals(7, completed.verifiedBytes)
        assertEquals(listOf("page-a", "page-b"), sink.members.map { it.first.assetId })
        assertContentEquals("abc".encodeToByteArray(), sink.members[0].second)
        assertContentEquals("defg".encodeToByteArray(), sink.members[1].second)
        assertEquals(listOf(3L, 7L), progress)
        assertEquals(1, sink.commitCount)
        assertEquals(0, sink.abortCount)
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
                assertTrue(it.url.encodedPath.endsWith("/api/assets/asset"))
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
        val bootstrap = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource")).bootstrap
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
        assertEquals("resource", sink.request?.resourceId)
        assertEquals("asset", sink.request?.assetId)
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
                        HttpHeaders.ContentType to listOf("application/epub+zip"),
                        HttpHeaders.ContentLength to listOf("4"),
                        HttpHeaders.ContentRange to listOf("bytes 2-5/6"),
                    ),
                )
            }
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource")).bootstrap.descriptor
        val result = gateway.transfer(
            context,
            DownloadTransferRequest("task", descriptor, 2),
            RecordingSink(),
        )
        assertIs<DownloadTransferResult.Success>(result)
        Unit
    }

    @Test
    fun changedAssetVersionRejectsResumeBeforeOpeningTheSink() = runBlocking {
        var transferring = false
        val gateway = gateway { request ->
            if (!transferring) respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            else {
                assertEquals("6:1000", request.headers["X-Asset-Version"])
                respond("cdef", HttpStatusCode.PartialContent, headersOf(
                    HttpHeaders.ContentType to listOf("application/epub+zip"),
                    HttpHeaders.ContentLength to listOf("4"),
                    HttpHeaders.ContentRange to listOf("bytes 2-5/6"),
                    "X-Asset-Version" to listOf("6:2000"),
                ))
            }
        }
        val original = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource")).bootstrap.descriptor
        val descriptor = original.copy(source = original.source.copy(sourceModifiedAtMillis = 1000))
        transferring = true
        val sink = RecordingSink()
        assertIs<DownloadTransferResult.Failure>(gateway.transfer(context, DownloadTransferRequest("task", descriptor, 2), sink))
        assertEquals(null, sink.request)
        assertEquals(0, sink.commitCount)
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
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource")).bootstrap.descriptor
        val sink = RecordingSink()

        assertIs<DownloadTransferResult.Failure>(
            gateway.transfer(context, DownloadTransferRequest("task", descriptor), sink),
        )
        assertEquals(0, sink.commitCount)
        assertEquals(0, sink.abortCount)
        Unit
    }

    @Test
    fun cancellationPropagatesBeforeSinkTransactionExists() = runBlocking {
        var requestCount = 0
        val gateway = gateway {
            requestCount += 1
            if (requestCount == 1) {
                respond(BOOTSTRAP, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            } else {
                throw CancellationException("cancel")
            }
        }
        val descriptor = assertIs<DownloadBootstrapResult.Success>(gateway.load(context, "resource")).bootstrap.descriptor
        val sink = RecordingSink()

        assertFailsWith<CancellationException> {
            gateway.transfer(context, DownloadTransferRequest("task", descriptor), sink)
        }
        assertEquals(0, sink.abortCount)
        Unit
    }

    private fun gateway(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): KtorDownloadsGateway =
        KtorDownloadsGateway(ApiClient(profile, HttpClient(MockEngine { request ->
            check(!request.url.encodedPath.contains("/reader/")) { "Downloads must not initialize Reader" }
            if (request.url.encodedPath == "/base/api/books/book") {
                respond(BOOK, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            } else handler(request)
        }), Json { ignoreUnknownKeys = false }))

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
        var request: DownloadSinkRequest? = null

        override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession {
            this.request = request
            return this
        }

        override suspend fun write(bytes: ByteArray) {
            this.bytes += bytes
        }

        override suspend fun commit(expectedTotalBytes: Long): String {
            commitCount += 1
            return "local://asset"
        }

        override suspend fun abort() {
            abortCount += 1
        }
    }

    private class RecordingBundleSink : DownloadByteSink, DownloadBundleByteSink {
        val members = mutableListOf<Pair<DownloadBundleMemberSinkRequest, ByteArray>>()
        var commitCount = 0
        var abortCount = 0

        override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession =
            error("A page-set transfer must begin a bundle")

        override suspend fun beginBundle(request: DownloadBundleSinkRequest): DownloadBundleByteSinkSession {
            assertEquals(DownloadArtifactKind.OriginalPageSet, request.artifactKind)
            assertEquals(2, request.memberCount)
            assertEquals(7, request.expectedTotalBytes)
            return BundleSession()
        }

        private inner class BundleSession : DownloadBundleByteSinkSession {
            override suspend fun beginMember(request: DownloadBundleMemberSinkRequest): DownloadByteSinkSession =
                MemberSession(request)

            override suspend fun commit(): String {
                require(members.size == 2) { "Bundle committed before every page was verified" }
                commitCount += 1
                return "local://page-set"
            }

            override suspend fun abort() {
                abortCount += 1
            }
        }

        private inner class MemberSession(
            private val request: DownloadBundleMemberSinkRequest,
        ) : DownloadByteSinkSession {
            private var bytes = byteArrayOf()

            override suspend fun write(bytes: ByteArray) {
                this.bytes += bytes
            }

            override suspend fun commit(expectedTotalBytes: Long): String {
                require(bytes.size.toLong() == expectedTotalBytes)
                members += request to bytes
                return "member://${request.assetId}"
            }

            override suspend fun abort() {
                abortCount += 1
            }
        }
    }

    private companion object {
        const val BOOK = """{"ok":true,"data":{"book":{"id":"book","libraryId":"library","sourceNodeId":"book-node","title":"Book","author":"Author","coverUrl":"/api/books/book/cover","visibilityState":"VISIBLE","curationState":"UNORGANIZED","publicationStatus":"UNKNOWN","trackingStatus":"UNKNOWN","metadataQuality":0,"coverStatus":"UNKNOWN"}}}"""
        const val BOOTSTRAP = """{"ok":true,"data":{"resource":{"id":"resource","bookId":"book","sourceNodeId":"node","title":"Resource","resourceIndex":1.5,"sortOrder":2,"format":"epub","readerType":"reflowable","assets":[{"id":"asset","title":"Resource","resourceId":"resource","sourceNodeId":"node","role":"PRIMARY","sourceFormat":"epub","mimeType":"application/epub+zip","sizeBytes":6,"sortOrder":0,"url":"/api/assets/asset"}]}}}"""
        const val COMIC_BOOTSTRAP = """{"ok":true,"data":{"resource":{"id":"resource","bookId":"book","sourceNodeId":"node","title":"Resource","resourceIndex":1.0,"sortOrder":0,"format":"cbz","readerType":"comic","assets":[{"id":"asset","title":"Page 1","resourceId":"resource","sourceNodeId":"node","role":"PRIMARY","sourceFormat":"cbz","mimeType":"application/vnd.comicbook+zip","sizeBytes":12,"sortOrder":0,"url":"/api/assets/asset"}]}}}"""
    }
}
