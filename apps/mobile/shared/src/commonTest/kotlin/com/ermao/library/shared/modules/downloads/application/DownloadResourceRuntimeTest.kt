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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlin.test.assertFailsWith
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.infrastructure.DownloadCatalogCodec
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class DownloadResourceRuntimeTest {
    @Test
    fun readerExpectationRejectsChangedAssetBeforeTaskOrTransfer() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val changed = descriptor.copy(source = descriptor.source.copy(totalBytes = 20))
        val gateway = SuccessfulGateway(changed)
        val result = DownloadResourceRuntime(catalog, gateway, { 42 }).download(
            context, "resource", "task", NoopSink, expectedDescriptor = descriptor,
        )
        assertEquals("ASSET_VERSION_CHANGED", assertIs<DownloadResourceResult.Failure>(result).error.code)
        assertEquals(0, gateway.requests.size)
        assertEquals(0, catalog.listTasks(namespace).size)
    }
    @Test
    fun emitsResourceProgressAndCompletionOnlyAfterCompletedArtifactIsPersisted() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val observations = mutableListOf<DownloadResourceObservation>()
        val runtime = DownloadResourceRuntime(catalog, SuccessfulGateway(descriptor), nowEpochMillis = { 42 })

        val result = runtime.download(
            context = context,
            resourceId = "resource",
            taskId = "task",
            sink = NoopSink,
            observer = DownloadResourceObserver(observations::add),
        )

        val ready = assertIs<DownloadResourceResult.Completed>(result)
        assertEquals("resource", ready.artifact.descriptor.identity.resourceId)
        assertEquals("asset", ready.artifact.descriptor.identity.assetId)
        assertEquals(
            listOf(
                DownloadResourceObservationKind.Preparing,
                DownloadResourceObservationKind.TaskCreated,
                DownloadResourceObservationKind.Downloading,
                DownloadResourceObservationKind.Progress,
                DownloadResourceObservationKind.Progress,
                DownloadResourceObservationKind.Completed,
            ),
            observations.map(DownloadResourceObservation::kind),
        )
        assertEquals(listOf(4L, 10L), observations.filter { it.kind == DownloadResourceObservationKind.Progress }.map { it.transferredBytes })
        assertEquals(ready.artifact, catalog.listArtifacts(namespace).single())
    }

    @Test
    fun concurrentRequestsReuseOneTaskAndTransfer() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val gateway = SuccessfulGateway(descriptor)
        val runtime = DownloadResourceRuntime(catalog, gateway, { 42 })
        val results = (0..4).map { index -> async { runtime.download(context, "resource", "task-$index", NoopSink) } }.awaitAll()
        results.forEach { assertIs<DownloadResourceResult.Completed>(it) }
        assertEquals(1, gateway.requests.size)
        assertEquals(1, catalog.listTasks(namespace).size)
        assertEquals(1, catalog.listArtifacts(namespace).size)
    }

    @Test
    fun nativeCancellationPersistsPauseAndResumeUsesSameTaskAndOffset() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val gateway = SuccessfulGateway(descriptor)
        val runtime = DownloadResourceRuntime(catalog, gateway, { 42 })
        val cancellation = DownloadCancellation()
        assertFailsWith<CancellationException> {
            runtime.download(context, "resource", "task", NoopSink,
                observer = DownloadResourceObserver { if (it.transferredBytes == 4L) cancellation.cancel() },
                cancellation = cancellation)
        }
        val paused = catalog.listTasks(namespace).single()
        assertEquals(DownloadTaskStatus.Paused, paused.status)
        assertEquals(4, paused.transferredBytes)
        assertEquals(0, catalog.listArtifacts(namespace).size)
        assertIs<DownloadResourceResult.Completed>(runtime.download(context, "resource", "duplicate", NoopSink))
        assertEquals(listOf("task", "task"), gateway.requests.map { it.taskId })
        assertEquals(listOf(0L, 4L), gateway.requests.map { it.resumeFromBytes })
    }

    @Test
    fun resumedTwoGiBDownloadKeepsLongCountersThroughCompletionAndPersistence() = runBlocking {
        val total = 2L * 1024 * 1024 * 1024
        val large = descriptor.copy(source = descriptor.source.copy(totalBytes = total))
        val catalog = InMemoryDownloadCatalogRepository()
        val gateway = SuccessfulGateway(large)
        val observations = mutableListOf<DownloadResourceObservation>()
        val sink = object : DownloadByteSink {
            override suspend fun inspect(request: DownloadSinkRequest) = DownloadStoredBytes(total - 1)
            override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession = error("Unused by fake gateway")
        }
        val result = DownloadResourceRuntime(catalog, gateway, { 42 }).download(
            context, "resource", "large", sink, observer = DownloadResourceObserver(observations::add),
        )
        assertEquals(total - 1, gateway.requests.single().resumeFromBytes)
        assertEquals(total, assertIs<DownloadResourceResult.Completed>(result).artifact.verifiedBytes)
        assertEquals(listOf(total - 1, total), observations
            .filter { it.kind == DownloadResourceObservationKind.Progress }.map { it.transferredBytes })
        val completed = catalog.listTasks(namespace).single()
        assertEquals(total, DownloadCatalogCodec.decode(DownloadCatalogCodec.encode(completed)).transferredBytes)
    }

    @Test
    fun failedTransferRetriesFromZeroAndReusesTask() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val gateway = SuccessfulGateway(descriptor, failuresRemaining = 1)
        val runtime = DownloadResourceRuntime(catalog, gateway, { 42 })
        assertIs<DownloadResourceResult.Failure>(runtime.download(context, "resource", "task", NoopSink))
        assertEquals(DownloadTaskStatus.FailedRetryable, catalog.listTasks(namespace).single().status)
        assertEquals(0, catalog.listArtifacts(namespace).size)
        assertIs<DownloadResourceResult.Completed>(runtime.download(context, "resource", "retry", NoopSink))
        assertEquals(listOf(0L, 0L), gateway.requests.map { it.resumeFromBytes })
        assertEquals(1, catalog.listTasks(namespace).size)
    }

    @Test
    fun persistedTaskCodecKeepsIdentityProgressAndRejectsInvalidBody(): Unit = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadResourceRuntime(catalog, SuccessfulGateway(descriptor), { 42 })
        runtime.download(context, "resource", "task", NoopSink)
        val completed = catalog.listTasks(namespace).single()
        val encoded = DownloadCatalogCodec.encode(completed)
        assertEquals(completed, DownloadCatalogCodec.decode(encoded))
        assertFailsWith<IllegalArgumentException> { DownloadCatalogCodec.decode(encoded.replace("\"transferredBytes\":10", "\"transferredBytes\":11")) }
        assertFailsWith<IllegalArgumentException> { DownloadCatalogCodec.decode("{}") }
    }

    @Test
    fun reconcilesDurablePartialAfterProcessDeathInsteadOfTrustingProgressRecord() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        catalog.saveTask(com.ermao.library.shared.modules.downloads.domain.DownloadTask(
            "original-task", descriptor, DownloadTaskStatus.Downloading, 3,
        ))
        val gateway = SuccessfulGateway(descriptor)
        val runtime = DownloadResourceRuntime(catalog, gateway, { 42 })
        runtime.recoverInterrupted(namespace)
        val sink = object : DownloadByteSink {
            override suspend fun inspect(request: DownloadSinkRequest) = DownloadStoredBytes(6)
            override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession = error("Unused")
        }
        assertIs<DownloadResourceResult.Completed>(runtime.download(context, "resource", "new-task", sink))
        assertEquals("original-task", gateway.requests.single().taskId)
        assertEquals(6, gateway.requests.single().resumeFromBytes)
    }

    @Test
    fun registersAtomicallyPublishedFileAfterInterruptedCatalogCommitWithoutTransfer() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val gateway = SuccessfulGateway(descriptor)
        val sink = object : DownloadByteSink {
            override suspend fun inspect(request: DownloadSinkRequest) = DownloadStoredBytes(0, "published/file")
            override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession = error("Published file must not be rewritten")
        }
        val result = DownloadResourceRuntime(catalog, gateway, { 42 }).download(context, "resource", "task", sink)
        assertEquals("published/file", assertIs<DownloadResourceResult.Completed>(result).artifact.localReference)
        assertEquals(0, gateway.requests.size)
        assertEquals(DownloadTaskStatus.Completed, catalog.listTasks(namespace).single().status)
        assertEquals(1, catalog.listArtifacts(namespace).size)
    }

    @Test
    fun titleChangesReuseCompletedTaskButSourceVersionReplacesStaleTask() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val original = descriptor.copy(source = descriptor.source.copy(sourceModifiedAtMillis = 100))
        val first = SuccessfulGateway(original)
        DownloadResourceRuntime(catalog, first, { 42 }).download(context, "resource", "first", NoopSink)
        val renamed = SuccessfulGateway(original.copy(bookTitle = "New title"))
        DownloadResourceRuntime(catalog, renamed, { 42 }).download(context, "resource", "renamed", NoopSink)
        assertEquals(0, renamed.requests.size)
        val revised = SuccessfulGateway(original.copy(source = original.source.copy(sourceModifiedAtMillis = 101)))
        DownloadResourceRuntime(catalog, revised, { 42 }).download(context, "resource", "revised", NoopSink)
        assertEquals(1, revised.requests.size)
        assertEquals(1, catalog.listTasks(namespace).size)
        assertEquals(101, catalog.listTasks(namespace).single().descriptor.source.sourceModifiedAtMillis)
    }

    @Test
    fun terminalOrMissingFileRecordIsDiscardedAndRebuilt() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        catalog.saveTask(com.ermao.library.shared.modules.downloads.domain.DownloadTask(
            id = "broken",
            descriptor = descriptor,
            status = DownloadTaskStatus.FailedTerminal,
            failureCode = "DOWNLOAD_LOCAL_FILE_INVALID",
        ))
        val discarded = mutableListOf<String>()
        val sink = object : DownloadByteSink {
            override suspend fun discard(request: DownloadSinkRequest) {
                discarded += request.taskId
            }
            override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession = error("Unused")
        }
        val gateway = SuccessfulGateway(descriptor)

        assertIs<DownloadResourceResult.Completed>(
            DownloadResourceRuntime(catalog, gateway, { 42 }).ensure(context, "resource", "rebuilt", sink),
        )

        assertEquals(listOf("broken"), discarded)
        assertEquals("rebuilt", catalog.listTasks(namespace).single().id)
        assertEquals(1, gateway.requests.size)
    }

    private class SuccessfulGateway(
        private val descriptor: DownloadDescriptor,
        private var failuresRemaining: Int = 0,
    ) : DownloadsGateway {
        val requests = mutableListOf<DownloadTransferRequest>()
        override suspend fun load(context: DownloadRequestContext, resourceId: String): DownloadBootstrapResult =
            DownloadBootstrapResult.Success(DownloadBootstrap(descriptor))

        override suspend fun transfer(
            context: DownloadRequestContext,
            request: DownloadTransferRequest,
            sink: DownloadByteSink,
            progressObserver: DownloadProgressObserver?,
        ): DownloadTransferResult {
            requests += request
            progressObserver?.onProgress(maxOf(4, request.resumeFromBytes), descriptor.totalBytes)
            delay(1)
            if (failuresRemaining-- > 0) return DownloadTransferResult.Failure(AppError(AppErrorKind.NetworkUnavailable, "OFFLINE"))
            progressObserver?.onProgress(descriptor.totalBytes, descriptor.totalBytes)
            return DownloadTransferResult.Success(CompletedTransfer("managed/asset.bin", descriptor.totalBytes, null, null))
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
