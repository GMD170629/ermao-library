package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.time.currentEpochMillis
import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.domain.transition
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

enum class DownloadResourceObservationKind {
    Preparing,
    TaskCreated,
    Downloading,
    Progress,
    ReadyToOpen,
    Failed,
    Cancelled,
}

data class DownloadResourceObservation(
    val resourceId: String,
    val kind: DownloadResourceObservationKind,
    val task: DownloadTask? = null,
    val transferredBytes: Long = 0,
    val totalBytes: Long? = null,
    val artifact: CompletedDownloadArtifact? = null,
    val error: AppError? = null,
) {
    init {
        require(resourceId.isNotBlank())
        require(transferredBytes >= 0)
        require(totalBytes == null || totalBytes > 0)
        require(totalBytes == null || transferredBytes <= totalBytes)
        require((kind == DownloadResourceObservationKind.ReadyToOpen) == (artifact != null))
        require((kind == DownloadResourceObservationKind.Failed) == (error != null))
    }
}

fun interface DownloadResourceObserver {
    fun onChanged(observation: DownloadResourceObservation)
}

sealed interface DownloadResourceResult {
    data class ReadyToOpen(val artifact: CompletedDownloadArtifact) : DownloadResourceResult
    data class Failure(val error: AppError) : DownloadResourceResult
}

/** Executes one resource's foreground download and emits ReadyToOpen after atomic persistence. */
class DownloadResourceRuntime(
    catalog: DownloadCatalogRepository,
    private val gateway: DownloadsGateway,
    private val nowEpochMillis: () -> Long = ::currentEpochMillis,
) {
    private val runtime = DownloadsRuntime(catalog)

    suspend fun downloadThenOpen(
        context: DownloadRequestContext,
        resourceId: String,
        taskId: String,
        sink: DownloadByteSink,
        observer: DownloadResourceObserver? = null,
    ): DownloadResourceResult {
        require(resourceId.isNotBlank())
        require(taskId.isNotBlank())
        observer.emit(DownloadResourceObservation(resourceId, DownloadResourceObservationKind.Preparing))
        var task: DownloadTask? = null
        try {
            val descriptor = when (val bootstrap = gateway.load(context, resourceId)) {
                is DownloadBootstrapResult.Success -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapResult.Failure -> {
                    observer.emit(
                        DownloadResourceObservation(
                            resourceId = resourceId,
                            kind = DownloadResourceObservationKind.Failed,
                            error = bootstrap.error,
                        ),
                    )
                    return DownloadResourceResult.Failure(bootstrap.error)
                }
            }
            require(descriptor.identity.resourceId == resourceId) { "Download bootstrap resource does not match request" }
            task = DownloadTask(taskId, descriptor)
            runtime.saveTask(task)
            observer.emit(task.observation(DownloadResourceObservationKind.TaskCreated))
            val downloadingTask = runtime.transitionTask(context.namespace, taskId, DownloadTaskEvent.Start)
            task = downloadingTask
            observer.emit(downloadingTask.observation(DownloadResourceObservationKind.Downloading))

            return when (val transfer = gateway.transfer(
                context = context,
                request = DownloadTransferRequest(taskId, descriptor),
                sink = sink,
                progressObserver = DownloadProgressObserver { transferred, total ->
                    observer.emit(
                        downloadingTask.observation(
                            kind = DownloadResourceObservationKind.Progress,
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
                            kind = DownloadResourceObservationKind.ReadyToOpen,
                            transferredBytes = artifact.verifiedBytes,
                            totalBytes = artifact.verifiedBytes,
                            artifact = artifact,
                        ),
                    )
                    DownloadResourceResult.ReadyToOpen(artifact)
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
                    observer.emit(task.observation(DownloadResourceObservationKind.Failed, error = transfer.error))
                    DownloadResourceResult.Failure(transfer.error)
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
                observer.emit((task ?: activeTask).observation(DownloadResourceObservationKind.Cancelled))
            } else {
                observer.emit(DownloadResourceObservation(resourceId, DownloadResourceObservationKind.Cancelled))
            }
            throw cancelled
        }
    }
}

private fun DownloadTask.observation(
    kind: DownloadResourceObservationKind,
    transferredBytes: Long = this.transferredBytes,
    totalBytes: Long = descriptor.source.totalBytes,
    artifact: CompletedDownloadArtifact? = null,
    error: AppError? = null,
) = DownloadResourceObservation(
    resourceId = descriptor.identity.resourceId,
    kind = kind,
    task = this,
    transferredBytes = transferredBytes,
    totalBytes = totalBytes,
    artifact = artifact,
    error = error,
)

private fun DownloadResourceObserver?.emit(observation: DownloadResourceObservation) {
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
