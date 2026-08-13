package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.time.currentEpochMillis
import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

enum class DownloadVolumeObservationKind {
    Preparing,
    TaskCreated,
    Downloading,
    Progress,
    ReadyToOpen,
    Failed,
    Cancelled,
}

/** Flat platform boundary for one volume's foreground download-to-reader handoff. */
data class DownloadVolumeObservation(
    val volumeId: String,
    val kind: DownloadVolumeObservationKind,
    val task: DownloadTask? = null,
    val transferredBytes: Long = 0,
    val totalBytes: Long? = null,
    val artifact: CompletedDownloadArtifact? = null,
    val error: AppError? = null,
) {
    init {
        require(volumeId.isNotBlank())
        require(transferredBytes >= 0)
        require(totalBytes == null || totalBytes > 0)
        require(totalBytes == null || transferredBytes <= totalBytes)
        require((kind == DownloadVolumeObservationKind.ReadyToOpen) == (artifact != null))
        require((kind == DownloadVolumeObservationKind.Failed) == (error != null))
    }
}

fun interface DownloadVolumeObserver {
    fun onChanged(observation: DownloadVolumeObservation)
}

sealed interface DownloadVolumeResult {
    data class ReadyToOpen(val artifact: CompletedDownloadArtifact) : DownloadVolumeResult
    data class Failure(val error: AppError) : DownloadVolumeResult
}

/**
 * Executes the complete foreground intent without owning platform navigation.
 * ReadyToOpen is emitted only after the sink commit and completed artifact persistence.
 */
class DownloadVolumeRuntime(
    catalog: DownloadCatalogRepository,
    private val gateway: DownloadsGateway,
    private val nowEpochMillis: () -> Long = ::currentEpochMillis,
) {
    private val runtime = DownloadsRuntime(catalog)

    suspend fun downloadThenOpen(
        context: DownloadRequestContext,
        volumeId: String,
        taskId: String,
        sink: DownloadByteSink,
        observer: DownloadVolumeObserver? = null,
    ): DownloadVolumeResult {
        require(volumeId.isNotBlank())
        require(taskId.isNotBlank())
        observer.emit(DownloadVolumeObservation(volumeId, DownloadVolumeObservationKind.Preparing))
        var task: DownloadTask? = null
        try {
            val descriptor = when (val bootstrap = gateway.load(context, volumeId)) {
                is DownloadBootstrapResult.Success -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapResult.Failure -> {
                    observer.emit(
                        DownloadVolumeObservation(
                            volumeId = volumeId,
                            kind = DownloadVolumeObservationKind.Failed,
                            error = bootstrap.error,
                        ),
                    )
                    return DownloadVolumeResult.Failure(bootstrap.error)
                }
            }
            task = DownloadTask(taskId, descriptor)
            runtime.saveTask(task)
            observer.emit(task.observation(DownloadVolumeObservationKind.TaskCreated))
            val downloadingTask = runtime.transitionTask(context.namespace, taskId, DownloadTaskEvent.Start)
            task = downloadingTask
            observer.emit(downloadingTask.observation(DownloadVolumeObservationKind.Downloading))

            return when (val transfer = gateway.transfer(
                context = context,
                request = DownloadTransferRequest(taskId, descriptor),
                sink = sink,
                progressObserver = DownloadProgressObserver { transferred, total ->
                    observer.emit(
                        downloadingTask.observation(
                            kind = DownloadVolumeObservationKind.Progress,
                            transferredBytes = transferred,
                            totalBytes = total,
                        ),
                    )
                },
            )) {
                is DownloadTransferResult.Success -> {
                    val artifact = CompletedDownloadArtifact(
                        descriptor = descriptor,
                        localReference = transfer.transfer.localReference,
                        verifiedBytes = transfer.transfer.verifiedBytes,
                        completedAtEpochMillis = nowEpochMillis(),
                    )
                    task = runtime.transitionTask(
                        context.namespace,
                        taskId,
                        DownloadTaskEvent.Complete(artifact),
                    )
                    observer.emit(
                        task.observation(
                            kind = DownloadVolumeObservationKind.ReadyToOpen,
                            transferredBytes = artifact.verifiedBytes,
                            totalBytes = artifact.verifiedBytes,
                            artifact = artifact,
                        ),
                    )
                    DownloadVolumeResult.ReadyToOpen(artifact)
                }
                is DownloadTransferResult.Failure -> {
                    task = runtime.transitionTask(
                        context.namespace,
                        taskId,
                        DownloadTaskEvent.Fail(
                            code = transfer.error.code,
                            retryable = transfer.error.kind.isRetryableDownloadFailure(),
                        ),
                    )
                    observer.emit(task.observation(DownloadVolumeObservationKind.Failed, error = transfer.error))
                    DownloadVolumeResult.Failure(transfer.error)
                }
            }
        } catch (cancelled: CancellationException) {
            val activeTask = task
            if (activeTask != null) {
                withContext(NonCancellable) {
                    runCatching {
                        task = runtime.transitionTask(context.namespace, taskId, DownloadTaskEvent.Cancel)
                    }
                }
                observer.emit((task ?: activeTask).observation(DownloadVolumeObservationKind.Cancelled))
            } else {
                observer.emit(DownloadVolumeObservation(volumeId, DownloadVolumeObservationKind.Cancelled))
            }
            throw cancelled
        }
    }
}

private fun DownloadTask.observation(
    kind: DownloadVolumeObservationKind,
    transferredBytes: Long = this.transferredBytes,
    totalBytes: Long = descriptor.source.totalBytes,
    artifact: CompletedDownloadArtifact? = null,
    error: AppError? = null,
) = DownloadVolumeObservation(
    volumeId = descriptor.identity.volumeId,
    kind = kind,
    task = this,
    transferredBytes = transferredBytes,
    totalBytes = totalBytes,
    artifact = artifact,
    error = error,
)

private fun DownloadVolumeObserver?.emit(observation: DownloadVolumeObservation) {
    this?.onChanged(observation)
}

private fun AppErrorKind.isRetryableDownloadFailure(): Boolean = this in setOf(
    AppErrorKind.NetworkUnavailable,
    AppErrorKind.Timeout,
    AppErrorKind.RateLimited,
    AppErrorKind.ServiceUnavailable,
    AppErrorKind.ServerFailure,
    AppErrorKind.TlsFailure,
)
