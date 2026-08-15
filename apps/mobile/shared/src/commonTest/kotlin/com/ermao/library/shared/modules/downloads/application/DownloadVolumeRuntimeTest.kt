package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
import com.ermao.library.shared.modules.downloads.domain.DownloadSource
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.runBlocking

class DownloadVolumeRuntimeTest {
    @Test
    fun emitsTaskProgressAndReadyOnlyAfterCompletedArtifactIsPersisted() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val observations = mutableListOf<DownloadVolumeObservation>()
        val runtime = DownloadVolumeRuntime(catalog, SuccessfulGateway(descriptor), nowEpochMillis = { 42 })

        val result = runtime.downloadThenOpen(
            context = context,
            volumeId = "volume",
            taskId = "task",
            sink = NoopSink,
            observer = DownloadVolumeObserver(observations::add),
        )

        val ready = assertIs<DownloadVolumeResult.ReadyToOpen>(result)
        assertEquals("media", ready.artifact.descriptor.mediaVersionId)
        assertEquals(
            listOf(
                DownloadVolumeObservationKind.Preparing,
                DownloadVolumeObservationKind.TaskCreated,
                DownloadVolumeObservationKind.Downloading,
                DownloadVolumeObservationKind.Progress,
                DownloadVolumeObservationKind.Progress,
                DownloadVolumeObservationKind.ReadyToOpen,
            ),
            observations.map(DownloadVolumeObservation::kind),
        )
        assertEquals(listOf(4L, 10L), observations.filter { it.kind == DownloadVolumeObservationKind.Progress }.map { it.transferredBytes })
        assertEquals(ready.artifact, catalog.listArtifacts(namespace).single())
    }

    private class SuccessfulGateway(
        private val descriptor: DownloadDescriptor,
    ) : DownloadsGateway {
        override suspend fun load(context: DownloadRequestContext, volumeId: String): DownloadBootstrapResult =
            DownloadBootstrapResult.Success(DownloadBootstrap(descriptor))

        override suspend fun transfer(
            context: DownloadRequestContext,
            request: DownloadTransferRequest,
            sink: DownloadByteSink,
            progressObserver: DownloadProgressObserver?,
        ): DownloadTransferResult {
            progressObserver?.onProgress(4, 10)
            progressObserver?.onProgress(10, 10)
            return DownloadTransferResult.Success(CompletedTransfer("managed/volume.bin", 10, null, null))
        }
    }

    private object NoopSink : DownloadByteSink {
        override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession = error("Unused by fake gateway")
    }

    private val namespace = DownloadNamespace("server", "user", 1)
    private val profile = ServerProfile(
        id = "profile",
        displayName = "Books",
        baseUrl = (ServerBaseUrl.parse("https://books.example/base") as ServerBaseUrlParseResult.Valid).baseUrl,
        serverIdentity = "server",
        isActive = true,
        tlsMode = TlsMode.SystemTrust,
    )
    private val context = DownloadRequestContext(profile, namespace)
    private val descriptor = DownloadDescriptor(
        identity = DownloadIdentity(namespace, "work", "volume"),
        workTitle = "Book",
        workAuthor = "Author",
        coverApiPath = "/api/works/work/cover",
        volumeTitle = "Volume",
        format = "EPUB",
        readerType = DownloadReaderType.Reflowable,
        source = DownloadSource("/api/volumes/volume/file", "application/epub+zip", 10),
        mediaVersionId = "media",
        mediaKind = "EBOOK",
        mediaVersionCompleted = true,
        volumeIndex = 1.0,
        volumeSortOrder = 0,
    )
}
