package com.ermao.library.features.downloads.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrapFailure
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadProgressObserver
import com.ermao.library.shared.modules.downloads.DownloadTask
import com.ermao.library.shared.modules.downloads.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.DownloadsRuntime
import com.ermao.library.shared.modules.downloads.KtorDownloadsGateway
import com.ermao.library.shared.modules.downloads.DownloadTransferFailure
import com.ermao.library.shared.modules.downloads.DownloadTransferSuccess
import com.ermao.library.shared.modules.downloads.downloadStartEvent
import com.ermao.library.shared.modules.downloads.downloadFailEvent
import com.ermao.library.shared.modules.downloads.downloadCompleteEvent
import com.ermao.library.shared.modules.downloads.downloadBytesTransferredEvent
import com.ermao.library.shared.modules.downloads.downloadPauseEvent
import com.ermao.library.shared.modules.downloads.downloadResumeEvent
import com.ermao.library.shared.modules.downloads.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.DownloadBatchOutcomeKind
import com.ermao.library.shared.modules.downloads.DownloadBatchResourceResult
import com.ermao.library.shared.modules.downloads.DownloadBatchResult
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class DownloadActionsViewModel(
    private val androidCatalog: AndroidDownloadCatalog,
    private val sharedCatalog: DownloadCatalogRepository,
    private val sink: AtomicDownloadFileSink,
    private val gateway: KtorDownloadsGateway,
    private val context: DownloadRequestContext,
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val runtime = DownloadsRuntime(sharedCatalog)
    private val namespace = AndroidDownloadNamespace(
        context.namespace.serverIdentity,
        context.namespace.userId,
        context.namespace.authorizationVersion,
    )
    private val mutableRecordsByResource = MutableStateFlow<Map<String, AndroidDownloadRecord>>(emptyMap())
    val recordsByResource: StateFlow<Map<String, AndroidDownloadRecord>> = mutableRecordsByResource.asStateFlow()
    private val mutableFailureByResource = MutableStateFlow<Map<String, String>>(emptyMap())
    val failureByResource: StateFlow<Map<String, String>> = mutableFailureByResource.asStateFlow()
    private val activeTransfers = mutableMapOf<String, Job>()
    private val pauseRequests = mutableSetOf<String>()

    init {
        viewModelScope.launch {
            androidCatalog.observe(namespace).collect { records ->
                mutableRecordsByResource.value = records
                    .groupBy(AndroidDownloadRecord::resourceId)
                    .mapValues { (_, assets) -> assets.maxBy(AndroidDownloadRecord::updatedAtEpochMillis) }
            }
        }
        viewModelScope.launch { recoverInterruptedTransfers() }
    }

    fun requestDownload(resourceId: String) {
        if (resourceId.isBlank() || activeTransfers[resourceId]?.isActive == true) return
        mutableFailureByResource.value -= resourceId
        val job = viewModelScope.launch {
            val descriptor = when (val bootstrap = gateway.load(context, resourceId)) {
                is DownloadBootstrapSuccess -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapFailure -> {
                    saveBootstrapFailure(resourceId, bootstrap.error.code)
                    return@launch
                }
            }
            if (!descriptor.isDownloadable) {
                saveBootstrapFailure(resourceId, "DOWNLOAD_NOT_AVAILABLE_OFFLINE")
                return@launch
            }
            val existing = sharedCatalog.listTasks(context.namespace)
                .filter { it.descriptor.identity.resourceId == resourceId }
                .maxByOrNull { it.transferredBytes }
                ?.takeIf { it.status == DownloadTaskStatus.Paused }
            transfer(resourceId, descriptor, existing)
        }
        activeTransfers[resourceId] = job
        job.invokeOnCompletion { activeTransfers.remove(resourceId, job) }
    }

    fun performBatch(resourceIds: Set<String>, onComplete: (DownloadBatchResult) -> Unit) {
        if (resourceIds.isEmpty()) {
            onComplete(DownloadBatchResult(emptyList()))
            return
        }
        val records = recordsByResource.value
        val results = resourceIds.sorted().map { resourceId ->
            when (records[resourceId]?.status) {
                null -> {
                    requestDownload(resourceId)
                    DownloadBatchResourceResult(resourceId, DownloadBatchOutcomeKind.Enqueued)
                }
                com.ermao.library.features.downloads.model.AndroidDownloadStatus.Paused -> {
                    requestDownload(resourceId)
                    DownloadBatchResourceResult(resourceId, DownloadBatchOutcomeKind.Resumed)
                }
                com.ermao.library.features.downloads.model.AndroidDownloadStatus.FailedRetryable -> {
                    requestDownload(resourceId)
                    DownloadBatchResourceResult(resourceId, DownloadBatchOutcomeKind.Retried)
                }
                com.ermao.library.features.downloads.model.AndroidDownloadStatus.FailedTerminal ->
                    DownloadBatchResourceResult(
                        resourceId,
                        DownloadBatchOutcomeKind.Failed,
                        records[resourceId]?.errorCode ?: "DOWNLOAD_NOT_RETRYABLE",
                    )
                else -> DownloadBatchResourceResult(resourceId, DownloadBatchOutcomeKind.Skipped)
            }
        }
        onComplete(DownloadBatchResult(results))
    }

    private suspend fun transfer(resourceId: String, descriptor: DownloadDescriptor, existing: DownloadTask? = null) {
        var task: DownloadTask? = null
        var progressJob: Job? = null
        var progressUpdates: Channel<Long>? = null
        try {
                task = existing ?: DownloadTask(
                    id = UUID.randomUUID().toString(),
                    descriptor = descriptor,
                )
                if (existing == null) {
                    runtime.saveTask(task)
                    runtime.transitionTask(context.namespace, task.id, downloadStartEvent())
                } else {
                    runtime.transitionTask(context.namespace, task.id, downloadResumeEvent())
                }
                progressUpdates = Channel(Channel.CONFLATED)
                progressJob = viewModelScope.launch {
                    var persistedBytes = 0L
                    for (transferredBytes in progressUpdates) {
                        if (transferredBytes <= persistedBytes || transferredBytes >= descriptor.totalBytes) continue
                        runtime.transitionTask(
                            context.namespace,
                            task.id,
                            downloadBytesTransferredEvent(transferredBytes),
                        )
                        persistedBytes = transferredBytes
                    }
                }
                when (val result = gateway.transfer(
                    context = context,
                    request = DownloadTransferRequest(
                        task.id,
                        descriptor,
                        resumeFromBytes = if (
                            descriptor.artifactKind == com.ermao.library.shared.modules.downloads.DownloadArtifactKind.SingleOriginalAsset
                        ) task.transferredBytes else 0,
                        preservePartialOnCancellation = true,
                    ),
                    sink = sink,
                    progressObserver = DownloadProgressObserver { transferredBytes, _ ->
                        progressUpdates.trySend(transferredBytes)
                    },
                )) {
                    is DownloadTransferSuccess -> {
                        progressUpdates.close()
                        progressJob.join()
                        val artifact = CompletedDownloadArtifact(
                            descriptor = descriptor,
                            localReference = result.transfer.localReference,
                            verifiedBytes = result.transfer.verifiedBytes,
                            completedAtEpochMillis = nowEpochMillis(),
                        )
                        runtime.transitionTask(
                            context.namespace,
                            task.id,
                            downloadCompleteEvent(artifact),
                        )
                    }
                    is DownloadTransferFailure -> {
                        progressUpdates.close()
                        progressJob.join()
                        runtime.transitionTask(
                            context.namespace,
                            task.id,
                            downloadFailEvent(result.error.code, result.error.kind.isRetryableDownloadFailure()),
                        )
                    }
                }
            } catch (cancelled: CancellationException) {
                progressUpdates?.close()
                progressJob?.cancelAndJoin()
                withContext(NonCancellable) {
                    task?.let {
                        if (pauseRequests.remove(resourceId)) {
                            runCatching { runtime.transitionTask(context.namespace, it.id, downloadPauseEvent()) }
                        } else {
                            sharedCatalog.deleteTask(context.namespace, it.id)
                        }
                    }
                }
                throw cancelled
            } catch (_: Exception) {
                progressUpdates?.close()
                progressJob?.cancelAndJoin()
                val currentTask = task
                if (currentTask != null) {
                    withContext(NonCancellable) {
                        runCatching {
                            runtime.transitionTask(
                                context.namespace,
                                currentTask.id,
                                downloadFailEvent("DOWNLOAD_FAILED", true),
                            )
                        }
                    }
                } else {
                    saveBootstrapFailure(resourceId, "DOWNLOAD_FAILED")
                }
            }
    }

    fun cancelDownload(resourceId: String) {
        pauseRequests += resourceId
        activeTransfers[resourceId]?.cancel()
    }

    fun cancelAll() {
        activeTransfers.values.forEach(Job::cancel)
    }

    fun removeDownload(record: AndroidDownloadRecord) {
        viewModelScope.launch {
            sharedCatalog.deleteTask(context.namespace, record.taskId)
        }
    }

    fun removeBook(bookId: String) {
        if (bookId.isBlank()) return
        viewModelScope.launch {
            val tasks = sharedCatalog.listTasks(context.namespace).filter { it.descriptor.identity.bookId == bookId }
            tasks.forEach { task ->
                activeTransfers[task.descriptor.identity.resourceId]?.cancelAndJoin()
                sharedCatalog.deleteTask(context.namespace, task.id)
            }
            sharedCatalog.listArtifacts(context.namespace)
                .filter { it.descriptor.identity.bookId == bookId }
                .forEach { sharedCatalog.deleteArtifact(context.namespace, it.identity) }
        }
    }

    suspend fun cancelAllAndJoin() {
        val jobs = activeTransfers.values.distinct()
        cancelAll()
        jobs.forEach { it.cancelAndJoin() }
        activeTransfers.clear()
    }

    private suspend fun recoverInterruptedTransfers() {
        androidCatalog.records(namespace)
            .filter { it.status in INTERRUPTED_STATUSES }
            .forEach { record ->
                androidCatalog.upsert(
                    record.copy(
                        status = com.ermao.library.features.downloads.model.AndroidDownloadStatus.FailedRetryable,
                        errorCode = "DOWNLOAD_INTERRUPTED",
                        updatedAtEpochMillis = nowEpochMillis(),
                    ),
                )
            }
    }

    private suspend fun saveBootstrapFailure(resourceId: String, code: String) {
        mutableFailureByResource.value += resourceId to code
    }

    companion object {
        private val INTERRUPTED_STATUSES = setOf(
            com.ermao.library.features.downloads.model.AndroidDownloadStatus.Queued,
            com.ermao.library.features.downloads.model.AndroidDownloadStatus.Downloading,
            com.ermao.library.features.downloads.model.AndroidDownloadStatus.Paused,
            com.ermao.library.features.downloads.model.AndroidDownloadStatus.Verifying,
        )

        fun factory(
            androidCatalog: AndroidDownloadCatalog,
            sharedCatalog: DownloadCatalogRepository,
            sink: AtomicDownloadFileSink,
            gateway: KtorDownloadsGateway,
            context: DownloadRequestContext,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { DownloadActionsViewModel(androidCatalog, sharedCatalog, sink, gateway, context) }
        }
    }
}

private fun com.ermao.library.shared.core.network.AppErrorKind.isRetryableDownloadFailure(): Boolean = this in setOf(
    com.ermao.library.shared.core.network.AppErrorKind.NetworkUnavailable,
    com.ermao.library.shared.core.network.AppErrorKind.Timeout,
    com.ermao.library.shared.core.network.AppErrorKind.ServiceUnavailable,
    com.ermao.library.shared.core.network.AppErrorKind.ServerFailure,
)
