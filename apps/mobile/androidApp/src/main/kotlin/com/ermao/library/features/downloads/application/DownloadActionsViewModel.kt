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
import com.ermao.library.shared.modules.downloads.ReaderLocalArtifact
import com.ermao.library.shared.modules.downloads.ReaderNeedsDownload
import com.ermao.library.shared.modules.downloads.ReaderRemoteStream
import com.ermao.library.shared.modules.downloads.ReaderUnavailable
import com.ermao.library.shared.modules.downloads.ReaderAccessRequest
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

sealed interface AndroidReaderAccessOutcome {
    data class LocalArtifact(
        val readerType: String,
        val format: String,
        val localReference: String,
        val expectedBytes: Long,
    ) : AndroidReaderAccessOutcome
    data class RemoteStream(val readerType: String, val format: String) : AndroidReaderAccessOutcome
    data object DownloadRequired : AndroidReaderAccessOutcome
    data class Unavailable(val reasonCode: String) : AndroidReaderAccessOutcome
}

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
    private val activeReaderChecks = mutableMapOf<String, Job>()

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
            transfer(resourceId, descriptor)
        }
        activeTransfers[resourceId] = job
        job.invokeOnCompletion { activeTransfers.remove(resourceId, job) }
    }

    fun requestReaderAccess(
        resourceId: String,
        isOnline: Boolean = true,
        onOutcome: (AndroidReaderAccessOutcome) -> Unit,
    ) {
        if (resourceId.isBlank() || activeReaderChecks[resourceId]?.isActive == true) return
        mutableFailureByResource.value -= resourceId
        val job = viewModelScope.launch {
            sharedCatalog.listArtifacts(context.namespace)
                .filter { it.identity.resourceId == resourceId }
                .maxByOrNull { it.completedAtEpochMillis }
                ?.let { artifact ->
                    onOutcome(artifact.toReaderAccessOutcome())
                    return@launch
                }
            val descriptor = when (val bootstrap = gateway.load(context, resourceId)) {
                is DownloadBootstrapSuccess -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapFailure -> {
                    saveBootstrapFailure(resourceId, bootstrap.error.code)
                    onOutcome(AndroidReaderAccessOutcome.Unavailable(bootstrap.error.code))
                    return@launch
                }
            }
            when (val decision = runtime.readerAccess(
                ReaderAccessRequest(
                    namespace = context.namespace,
                    resourceId = descriptor.identity.resourceId,
                    readerType = descriptor.readerType,
                    isOnline = isOnline,
                ),
            )) {
                is ReaderLocalArtifact -> onOutcome(decision.artifact.toReaderAccessOutcome())
                is ReaderUnavailable -> onOutcome(
                    AndroidReaderAccessOutcome.Unavailable(decision.reasonCode),
                )
                else -> if (decision == ReaderRemoteStream) {
                    onOutcome(AndroidReaderAccessOutcome.RemoteStream(descriptor.readerType.name, descriptor.format))
                } else {
                    check(decision == ReaderNeedsDownload)
                    onOutcome(AndroidReaderAccessOutcome.DownloadRequired)
                }
            }
        }
        activeReaderChecks[resourceId] = job
        job.invokeOnCompletion { activeReaderChecks.remove(resourceId, job) }
    }

    private fun CompletedDownloadArtifact.toReaderAccessOutcome() = AndroidReaderAccessOutcome.LocalArtifact(
        readerType = descriptor.readerType.name,
        format = descriptor.format,
        localReference = localReference,
        expectedBytes = verifiedBytes,
    )

    private suspend fun transfer(resourceId: String, descriptor: DownloadDescriptor) {
        var task: DownloadTask? = null
        var progressJob: Job? = null
        var progressUpdates: Channel<Long>? = null
        try {
                task = DownloadTask(
                    id = UUID.randomUUID().toString(),
                    descriptor = descriptor,
                )
                runtime.saveTask(task)
                runtime.transitionTask(
                    context.namespace,
                    task.id,
                    downloadStartEvent(),
                )
                progressUpdates = Channel(Channel.CONFLATED)
                progressJob = viewModelScope.launch {
                    var persistedBytes = 0L
                    for (transferredBytes in progressUpdates) {
                        if (transferredBytes <= persistedBytes || transferredBytes >= descriptor.source.totalBytes) continue
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
                    request = DownloadTransferRequest(task.id, descriptor),
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
                    task?.let { sharedCatalog.deleteTask(context.namespace, it.id) }
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
        activeTransfers[resourceId]?.cancel()
    }

    fun cancelAll() {
        activeReaderChecks.values.forEach(Job::cancel)
        activeTransfers.values.forEach(Job::cancel)
    }

    fun removeDownload(record: AndroidDownloadRecord) {
        viewModelScope.launch {
            sharedCatalog.deleteTask(context.namespace, record.taskId)
        }
    }

    suspend fun cancelAllAndJoin() {
        val jobs = (activeReaderChecks.values + activeTransfers.values).distinct()
        cancelAll()
        jobs.forEach { it.cancelAndJoin() }
        activeReaderChecks.clear()
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
