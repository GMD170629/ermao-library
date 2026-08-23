package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.BootstrapReaderPublication
import com.ermao.library.shared.modules.reader.application.LocalReaderSourceResolver
import com.ermao.library.shared.modules.reader.application.PublicationDownloadPort
import com.ermao.library.shared.modules.reader.application.PublicationDownloadResult
import com.ermao.library.shared.modules.reader.application.PublicationDownloadSinkFactory
import com.ermao.library.shared.modules.reader.application.ReaderBootstrap
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
import com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult
import com.ermao.library.shared.modules.reader.application.ReaderPublicationDownload
import com.ermao.library.shared.modules.reader.domain.LocalReaderSource
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ReaderPublicationBootstrapTest {
    @Test
    fun opensOnlinePdfAsRemoteByteRangeWithoutDownloading() = runBlocking {
        var downloadCalls = 0
        val result = bootstrapper(
            downloadPort = PublicationDownloadPort { _, _ ->
                downloadCalls += 1
                PublicationDownloadResult.Failure("UNEXPECTED_DOWNLOAD", false)
            },
            nativePdfiumRangeV1 = true,
        ).execute(request())

        val content = assertIs<ReaderPublicationBootstrapResult.Content>(result)
        val source = assertIs<RemoteByteRangeReaderSource>(content.source)
        assertEquals(0, downloadCalls)
        assertEquals("/api/assets/asset-1", source.apiPath)
        assertEquals(25L * 1024L * 1024L, source.expectedSizeBytes)
        assertEquals(ReaderSourceFormat.Pdf, source.sourceFormat)
        assertEquals(request().namespace, source.namespace)
    }

    @Test
    fun completedLocalPdfWinsOverRemoteRange() = runBlocking {
        val local = localSource()
        var downloadCalls = 0
        val result = bootstrapper(
            downloadPort = PublicationDownloadPort { _, _ ->
                downloadCalls += 1
                PublicationDownloadResult.Failure("UNEXPECTED_DOWNLOAD", false)
            },
            resolver = LocalReaderSourceResolver { local },
            nativePdfiumRangeV1 = true,
        ).execute(request())

        assertEquals(local, assertIs<ReaderPublicationBootstrapResult.Content>(result).source)
        assertEquals(0, downloadCalls)
    }

    @Test
    fun disabledRangeFlagPreservesTheExistingDownloadPath() = runBlocking {
        val local = localSource()
        var downloadCalls = 0
        val result = bootstrapper(
            downloadPort = PublicationDownloadPort { _, _ ->
                downloadCalls += 1
                PublicationDownloadResult.Content(local)
            },
            nativePdfiumRangeV1 = false,
        ).execute(request())

        assertEquals(local, assertIs<ReaderPublicationBootstrapResult.Content>(result).source)
        assertEquals(1, downloadCalls)
    }

    private fun bootstrapper(
        downloadPort: PublicationDownloadPort,
        resolver: LocalReaderSourceResolver? = null,
        nativePdfiumRangeV1: Boolean,
    ) = BootstrapReaderPublication(
        bootstrapGateway = ReaderBootstrapGateway { ReaderBootstrapResult.Content(bootstrap()) },
        downloadPort = downloadPort,
        sinkFactory = PublicationDownloadSinkFactory { error("Download sink must not be opened by this test") },
        localSourceResolver = resolver,
        nativePdfiumRangeV1 = nativePdfiumRangeV1,
    )

    private fun bootstrap() = ReaderBootstrap(
        target = ReaderProgressSyncTarget(namespace(), "book-1", "resource-1", ReaderFormat.Pdf),
        publication = ReaderPublicationDownload(
            profile = profile(),
            resourceId = "resource-1",
            displayTitle = "PDF",
            bookId = "book-1",
            assetId = "asset-1",
            apiPath = "/api/assets/asset-1",
            originalSourceFormat = ReaderSourceFormat.Pdf,
            sourceFormat = ReaderSourceFormat.Pdf,
            mimeType = "application/pdf",
            expectedSizeBytes = 25L * 1024L * 1024L,
        ),
        remoteSnapshot = null,
        pageCount = 120,
    )

    private fun localSource() = LocalReaderSource(
        resourceId = "resource-1",
        displayTitle = "PDF",
        format = ReaderFormat.Pdf,
        bookId = "book-1",
        assetId = "asset-1",
        sourceFormat = ReaderSourceFormat.Pdf,
    )

    private fun request() = ReaderBootstrapRequest(profile(), namespace(), "resource-1")
    private fun namespace() = ReaderSyncNamespace("server-1", "user-1", 3)

    private fun profile(): ServerProfile {
        val url = assertIs<ServerBaseUrlParseResult.Valid>(ServerBaseUrl.parse("https://books.example")).baseUrl
        return ServerProfile("profile-1", "Books", url, "server-1", true, TlsMode.SystemTrust)
    }

}
