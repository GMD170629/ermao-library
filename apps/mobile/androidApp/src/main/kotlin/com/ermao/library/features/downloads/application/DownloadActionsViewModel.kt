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
    private val mutableRecordsByVolume = MutableStateFlow<Map<String, AndroidDownloadRecord>>(emptyMap())
    val recordsByVolume: StateFlow<Map<String, AndroidDownloadRecord>> = mutableRecordsByVolume.asStateFlow()
    private val mutableFailureByVolume = MutableStateFlow<Map<String, String>>(emptyMap())
    val failureByVolume: StateFlow<Map<String, String>> = mutableFailureByVolume.asStateFlow()
    private val activeTransfers = mutableMapOf<String, Job>()
    private val activeReaderChecks = mutableMapOf<String, Job>()

    init {
        viewModelScope.launch {
            androidCatalog.observe(namespace).collect { records ->
                mutableRecordsByVolume.value = records
                    .groupBy(AndroidDownloadRecord::volumeId)
                    .mapValues { (_, versions) -> versions.maxBy(AndroidDownloadRecord::updatedAtEpochMillis) }
            }
        }
        viewModelScope.launch { recoverInterruptedTransfers() }
    }

    fun requestDownload(volumeId: String) {
        if (volumeId.isBlank() || activeTransfers[volumeId]?.isActive == true) return
        mutableFailureByVolume.value -= volumeId
        val job = viewModelScope.launch {
            val descriptor = when (val bootstrap = gateway.load(context, volumeId)) {
                is DownloadBootstrapSuccess -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapFailure -> {
                    saveBootstrapFailure(volumeId, bootstrap.error.code)
                    return@launch
                }
            }
            transfer(volumeId, descriptor)
        }
        activeTransfers[volumeId] = job
        job.invokeOnCompletion { activeTransfers.remove(volumeId, job) }
    }

    fun requestReaderAccess(
        volumeId: String,
        isOnline: Boolean = true,
        onOutcome: (AndroidReaderAccessOutcome) -> Unit,
    ) {
        if (volumeId.isBlank() || activeReaderChecks[volumeId]?.isActive == true) return
        mutableFailureByVolume.value -= volumeId
        val job = viewModelScope.launch {
            sharedCatalog.listArtifacts(context.namespace)
                .filter { it.identity.volumeId == volumeId }
                .maxByOrNull { it.completedAtEpochMillis }
                ?.let { artifact ->
                    onOutcome(artifact.toReaderAccessOutcome())
                    return@launch
                }
            val descriptor = when (val bootstrap = gateway.load(context, volumeId)) {
                is DownloadBootstrapSuccess -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapFailure -> {
                    saveBootstrapFailure(volumeId, bootstrap.error.code)
                    onOutcome(AndroidReaderAccessOutcome.Unavailable(bootstrap.error.code))
                    return@launch
                }
            }
            when (val decision = runtime.readerAccess(
                ReaderAccessRequest(
                    namespace = context.namespace,
                    volumeId = descriptor.identity.volumeId,
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
        activeReaderChecks[volumeId] = job
        job.invokeOnCompletion { activeReaderChecks.remove(volumeId, job) }
    }

    private fun CompletedDownloadArtifact.toReaderAccessOutcome() = AndroidReaderAccessOutcome.LocalArtifact(
        readerType = descriptor.readerType.name,
        format = descriptor.format,
        localReference = localReference,
        expectedBytes = verifiedBytes,
    )

    private suspend fun transfer(volumeId: String, descriptor: DownloadDescriptor) {
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
                    saveBootstrapFailure(volumeId, "DOWNLOAD_FAILED")
                }
            }
    }

    fun cancelDownload(volumeId: String) {
        activeTransfers[volumeId]?.cancel()
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

    private suspend fun saveBootstrapFailure(volumeId: String, code: String) {
        mutableFailureByVolume.value += volumeId to code
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
