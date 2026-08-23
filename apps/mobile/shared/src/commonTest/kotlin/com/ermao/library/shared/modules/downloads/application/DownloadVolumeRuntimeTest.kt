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
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class DownloadResourceRuntimeTest {
    @Test
    fun emitsResourceProgressAndReadyOnlyAfterCompletedArtifactIsPersisted() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val observations = mutableListOf<DownloadResourceObservation>()
        val runtime = DownloadResourceRuntime(catalog, SuccessfulGateway(descriptor), nowEpochMillis = { 42 })

        val result = runtime.downloadThenOpen(
            context = context,
            resourceId = "resource",
            taskId = "task",
            sink = NoopSink,
            observer = DownloadResourceObserver(observations::add),
        )

        val ready = assertIs<DownloadResourceResult.ReadyToOpen>(result)
        assertEquals("resource", ready.artifact.descriptor.identity.resourceId)
        assertEquals("asset", ready.artifact.descriptor.identity.assetId)
        assertEquals(
            listOf(
                DownloadResourceObservationKind.Preparing,
                DownloadResourceObservationKind.TaskCreated,
                DownloadResourceObservationKind.Downloading,
                DownloadResourceObservationKind.Progress,
                DownloadResourceObservationKind.Progress,
                DownloadResourceObservationKind.ReadyToOpen,
            ),
            observations.map(DownloadResourceObservation::kind),
        )
        assertEquals(listOf(4L, 10L), observations.filter { it.kind == DownloadResourceObservationKind.Progress }.map { it.transferredBytes })
        assertEquals(ready.artifact, catalog.listArtifacts(namespace).single())
    }

    private class SuccessfulGateway(
        private val descriptor: DownloadDescriptor,
    ) : DownloadsGateway {
        override suspend fun load(context: DownloadRequestContext, resourceId: String): DownloadBootstrapResult =
            DownloadBootstrapResult.Success(DownloadBootstrap(descriptor))

        override suspend fun transfer(
            context: DownloadRequestContext,
            request: DownloadTransferRequest,
            sink: DownloadByteSink,
            progressObserver: DownloadProgressObserver?,
        ): DownloadTransferResult {
            progressObserver?.onProgress(4, 10)
            progressObserver?.onProgress(10, 10)
            return DownloadTransferResult.Success(CompletedTransfer("managed/asset.bin", 10, null, null))
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
        identity = DownloadIdentity(namespace, "book", "resource", "asset"),
        bookTitle = "Book",
        bookAuthor = "Author",
        coverApiPath = "/api/books/book/cover",
        resourceTitle = "Resource",
        format = "epub",
        readerType = DownloadReaderType.Reflowable,
        source = DownloadSource("/api/assets/asset", "application/epub+zip", 10),
    )
}
