package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.application.DownloadPreparationUiState
import com.ermao.library.features.downloads.application.DownloadPreparationViewModel
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.CompletedTransfer
import com.ermao.library.shared.modules.downloads.DownloadBootstrap
import com.ermao.library.shared.modules.downloads.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.DownloadBootstrapResult
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadByteSink
import com.ermao.library.shared.modules.downloads.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadIdentity
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadProgressObserver
import com.ermao.library.shared.modules.downloads.DownloadReaderType
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.DownloadSource
import com.ermao.library.shared.modules.downloads.DownloadTransferGateway
import com.ermao.library.shared.modules.downloads.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.DownloadTransferResult
import com.ermao.library.shared.modules.downloads.DownloadTransferSuccess
import com.ermao.library.shared.modules.downloads.InMemoryDownloadCatalogRepository
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class DownloadPreparationViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun existingCurrentArtifactCompletesWithoutTransfer() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val descriptor = descriptor()
        catalog.saveArtifact(CompletedDownloadArtifact(descriptor, "artifact.epub", 8, 1))
        var transferCount = 0
        val viewModel = DownloadPreparationViewModel(
            volumeId = "volume",
            context = context(),
            catalog = catalog,
            sink = unusedSink,
            bootstrapGateway = bootstrap(descriptor),
            transferGateway = object : DownloadTransferGateway {
                override suspend fun transfer(
                    context: DownloadRequestContext,
                    request: DownloadTransferRequest,
                    sink: DownloadByteSink,
                    progressObserver: DownloadProgressObserver?,
                ): DownloadTransferResult {
                    transferCount += 1
                    error("transfer must not run")
                }
            },
        )

        advanceUntilIdle()

        assertIs<DownloadPreparationUiState.Completed>(viewModel.uiState.value)
        assertEquals("artifact.epub", viewModel.completed.first().localReference)
        assertEquals(0, transferCount)
    }

    @Test
    fun missingArtifactCreatesRealTaskPersistsProgressAndCompletesOnce() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val descriptor = descriptor()
        val viewModel = DownloadPreparationViewModel(
            volumeId = "volume",
            context = context(),
            catalog = catalog,
            sink = unusedSink,
            bootstrapGateway = bootstrap(descriptor),
            transferGateway = object : DownloadTransferGateway {
                override suspend fun transfer(
                    context: DownloadRequestContext,
                    request: DownloadTransferRequest,
                    sink: DownloadByteSink,
                    progressObserver: DownloadProgressObserver?,
                ): DownloadTransferResult {
                    progressObserver?.onProgress(4, 8)
                    return DownloadTransferSuccess(CompletedTransfer("artifact.epub", 8, null, null))
                }
            },
            nowEpochMillis = { 2 },
        )

        advanceUntilIdle()

        val completion = viewModel.completed.first()
        assertEquals("artifact.epub", completion.localReference)
        assertIs<DownloadPreparationUiState.Completed>(viewModel.uiState.value)
        assertEquals(8, catalog.listTasks(descriptor.identity.namespace).single().transferredBytes)
        assertEquals(1, catalog.listArtifacts(descriptor.identity.namespace).size)
    }

    private fun bootstrap(descriptor: DownloadDescriptor) = object : DownloadBootstrapGateway {
        override suspend fun load(context: DownloadRequestContext, volumeId: String) =
            DownloadBootstrapSuccess(DownloadBootstrap(descriptor))
    }

    private fun descriptor() = DownloadDescriptor(
        identity = DownloadIdentity(DownloadNamespace("server", "user", 2), "work", "volume", "fingerprint"),
        workTitle = "Book",
        workAuthor = "Author",
        coverApiPath = "/api/works/work/cover",
        volumeTitle = "Volume",
        format = "EPUB",
        readerType = DownloadReaderType.Reflowable,
        source = DownloadSource("/api/files/file", "application/epub+zip", 8),
        mediaVersionId = "media-version",
        mediaKind = "EBOOK",
    )

    private fun context(): DownloadRequestContext {
        val parsed = ServerBaseUrl.parse("https://example.test") as ServerBaseUrlParseResult.Valid
        return DownloadRequestContext(
            ServerProfile("profile", "Server", parsed.baseUrl, "server", true, TlsMode.SystemTrust),
            DownloadNamespace("server", "user", 2),
        )
    }

    private val unusedSink = object : DownloadByteSink {
        override suspend fun begin(request: DownloadSinkRequest) =
            object : DownloadByteSinkSession {
                override suspend fun write(bytes: ByteArray) = Unit
                override suspend fun commit(expectedTotalBytes: Long) = "artifact.epub"
                override suspend fun abort() = Unit
            }
        }
}
