package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.time.currentEpochMillis
import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.domain.DownloadArtifactKind
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.transition
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

enum class DownloadResourceObservationKind {
    Preparing,
    TaskCreated,
    Downloading,
    Progress,
    Completed,
    Failed,
    Paused,
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
        require((kind == DownloadResourceObservationKind.Completed) == (artifact != null))
        require((kind == DownloadResourceObservationKind.Failed) == (error != null))
    }
}

fun interface DownloadResourceObserver {
    fun onChanged(observation: DownloadResourceObservation)
}

sealed interface DownloadResourceResult {
    data class Completed(val artifact: CompletedDownloadArtifact) : DownloadResourceResult
    data class Failure(val error: AppError) : DownloadResourceResult
}

/** Explicit cancellation bridge for Swift Task cancellation and native lifecycle adapters. */
class DownloadCancellation {
    private data class State(val cancelled: Boolean = false, val job: Job? = null)
    private val state = MutableStateFlow(State())
    fun cancel() {
        state.update { it.copy(cancelled = true) }
        state.value.job?.cancel()
    }
    internal fun attach(job: Job) {
        state.update { it.copy(job = job) }
        if (state.value.cancelled) job.cancel()
    }
    internal fun detach() { state.update { it.copy(job = null) } }
}

/** One owner for explicit download task creation, resume, verification and registration.
 * The instance belongs to an authenticated application's lifecycle. Cancellation pauses;
 * removal is a separate command after the owning job has joined.
 */
class DownloadResourceRuntime(
    private val catalog: DownloadCatalogRepository,
    private val gateway: DownloadsGateway,
    private val nowEpochMillis: () -> Long = ::currentEpochMillis,
) {
    private val runtime = DownloadsRuntime(catalog)
    private val queue = Mutex()

    @Throws(Exception::class)
    suspend fun recoverInterrupted(namespace: DownloadNamespace) = queue.withLock {
        catalog.listTasks(namespace).filter { it.status == DownloadTaskStatus.Downloading }.forEach {
            catalog.saveTask(it.transition(DownloadTaskEvent.Pause))
        }
    }

    @Throws(Exception::class)
    suspend fun download(
        context: DownloadRequestContext,
        resourceId: String,
        taskId: String,
        sink: DownloadByteSink,
        observer: DownloadResourceObserver? = null,
        cancellation: DownloadCancellation? = null,
    ): DownloadResourceResult = coroutineScope {
        cancellation?.attach(coroutineContext.job)
        try { queue.withLock {
        require(resourceId.isNotBlank() && taskId.isNotBlank())
        observer.emit(DownloadResourceObservation(resourceId, DownloadResourceObservationKind.Preparing))
        val descriptor = when (val result = gateway.load(context, resourceId)) {
            is DownloadBootstrapResult.Success -> result.bootstrap.descriptor
            is DownloadBootstrapResult.Failure -> return@withLock failure(resourceId, result.error, observer)
        }
        require(descriptor.identity.namespace == context.namespace && descriptor.identity.resourceId == resourceId)
        if (!descriptor.isDownloadable) return@withLock failure(
            resourceId, AppError(AppErrorKind.InvalidRequest, "DOWNLOAD_NOT_AVAILABLE_OFFLINE"), observer,
        )
        val existing = catalog.findTask(descriptor)
        existing?.artifact?.let {
            observer.emit(existing.observation(DownloadResourceObservationKind.Completed, artifact = it))
            return@withLock DownloadResourceResult.Completed(it)
        }
        if (existing?.status == DownloadTaskStatus.FailedTerminal) return@withLock failure(
            resourceId, AppError(AppErrorKind.InvalidRequest, existing.failureCode ?: "DOWNLOAD_NOT_RETRYABLE"), observer,
        )
        var task = existing ?: DownloadTask(taskId, descriptor).also {
            catalog.saveTask(it)
            observer.emit(it.observation(DownloadResourceObservationKind.TaskCreated))
        }
        val stored = sink.inspect(DownloadSinkRequest(
            context.namespace, task.id, resourceId, descriptor.identity.assetId,
            descriptor.totalBytes, task.transferredBytes, descriptor.artifactKind,
        ))
        require(stored.partialBytes <= descriptor.totalBytes)
        if (task.status == DownloadTaskStatus.Downloading) task = task.transition(DownloadTaskEvent.Pause)
        task = task.copy(transferredBytes = if (stored.partialBytes < descriptor.totalBytes) stored.partialBytes else 0)
        task = task.transition(if (task.status == DownloadTaskStatus.Queued) DownloadTaskEvent.Start else DownloadTaskEvent.Resume)
        catalog.saveTask(task)
        observer.emit(task.observation(DownloadResourceObservationKind.Downloading))
        stored.completedReference?.let { reference ->
            val artifact = CompletedDownloadArtifact(descriptor, reference, descriptor.totalBytes, nowEpochMillis())
            task = runtime.transitionTask(context.namespace, task.id, DownloadTaskEvent.Complete(artifact))
            observer.emit(task.observation(DownloadResourceObservationKind.Completed, artifact = artifact))
            return@withLock DownloadResourceResult.Completed(artifact)
        }
        var received = task.transferredBytes
        try {
            val result = coroutineScope {
                val updates = Channel<Long>(Channel.CONFLATED)
                val persist = launch {
                    for (bytes in updates) {
                        if (bytes > task.transferredBytes) {
                            task = runtime.transitionTask(context.namespace, task.id, DownloadTaskEvent.BytesTransferred(bytes))
                        }
                    }
                }
                try {
                    gateway.transfer(
                        context, DownloadTransferRequest(
                            task.id, descriptor,
                            resumeFromBytes = if (descriptor.artifactKind == DownloadArtifactKind.SingleOriginalAsset) task.transferredBytes else 0,
                            preservePartialOnCancellation = true,
                        ), sink, DownloadProgressObserver { bytes, total ->
                            received = bytes
                            updates.trySend(bytes)
                            observer.emit(task.observation(DownloadResourceObservationKind.Progress, bytes, total))
                        },
                    )
                } finally {
                    updates.close()
                    persist.join()
                }
            }
            when (result) {
                is DownloadTransferResult.Success -> {
                    val artifact = CompletedDownloadArtifact(descriptor, result.transfer.localReference, result.transfer.verifiedBytes, nowEpochMillis())
                    task = runtime.transitionTask(context.namespace, task.id, DownloadTaskEvent.Complete(artifact))
                    observer.emit(task.observation(DownloadResourceObservationKind.Completed, artifact = artifact))
                    DownloadResourceResult.Completed(artifact)
                }
                is DownloadTransferResult.Failure -> {
                    // A failed transfer aborts its temporary file. Retry starts at zero.
                    task = task.copy(transferredBytes = 0).transition(DownloadTaskEvent.Fail(result.error.code, result.error.kind.isRetryableDownloadFailure()))
                    catalog.saveTask(task)
                    failure(resourceId, result.error, observer, task)
                }
            }
        } catch (cancelled: CancellationException) {
            withContext(NonCancellable) {
                // Persist the final acknowledged write, even if the conflated progress worker was cancelled.
                task = task.copy(transferredBytes = if (descriptor.artifactKind == DownloadArtifactKind.SingleOriginalAsset) received else 0)
                    .transition(DownloadTaskEvent.Pause)
                catalog.saveTask(task)
            }
            observer.emit(task.observation(DownloadResourceObservationKind.Paused))
            throw cancelled
        }
        } } finally { cancellation?.detach() }
    }

    private fun failure(resourceId: String, error: AppError, observer: DownloadResourceObserver?, task: DownloadTask? = null): DownloadResourceResult.Failure {
        observer.emit(DownloadResourceObservation(resourceId, DownloadResourceObservationKind.Failed, task = task, error = error))
        return DownloadResourceResult.Failure(error)
    }
}

private fun DownloadTask.observation(
    kind: DownloadResourceObservationKind,
    transferredBytes: Long = this.transferredBytes,
    totalBytes: Long = descriptor.totalBytes,
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
    AppErrorKind.StorageFailure,
)
