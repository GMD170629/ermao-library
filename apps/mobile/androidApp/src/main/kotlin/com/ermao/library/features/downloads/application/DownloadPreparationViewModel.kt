package com.ermao.library.features.downloads.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrapFailure
import com.ermao.library.shared.modules.downloads.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadByteSink
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadProgressObserver
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadTask
import com.ermao.library.shared.modules.downloads.DownloadTransferFailure
import com.ermao.library.shared.modules.downloads.DownloadTransferGateway
import com.ermao.library.shared.modules.downloads.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.DownloadTransferSuccess
import com.ermao.library.shared.modules.downloads.DownloadsRuntime
import com.ermao.library.shared.modules.downloads.ReaderAccessRequest
import com.ermao.library.shared.modules.downloads.ReaderLocalArtifact
import com.ermao.library.shared.modules.downloads.ReaderNeedsDownload
import com.ermao.library.shared.modules.downloads.ReaderRemoteStream
import com.ermao.library.shared.modules.downloads.ReaderUnavailable
import com.ermao.library.shared.modules.downloads.downloadBytesTransferredEvent
import com.ermao.library.shared.modules.downloads.downloadCompleteEvent
import com.ermao.library.shared.modules.downloads.downloadFailEvent
import com.ermao.library.shared.modules.downloads.downloadStartEvent
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface DownloadPreparationUiState {
    data object CheckingExisting : DownloadPreparationUiState
    data object CreatingTask : DownloadPreparationUiState
    data class Downloading(val transferredBytes: Long, val totalBytes: Long) : DownloadPreparationUiState
    data class Failed(val errorCode: String) : DownloadPreparationUiState
    data object Completed : DownloadPreparationUiState
}

data class PreparedDownloadArtifact(
    val bookId: String,
    val resourceId: String,
    val assetId: String,
    val localReference: String,
    val expectedBytes: Long,
    val format: String,
)

class DownloadPreparationViewModel(
    private val resourceId: String,
    private val context: DownloadRequestContext,
    private val catalog: DownloadCatalogRepository,
    private val sink: DownloadByteSink,
    private val bootstrapGateway: DownloadBootstrapGateway,
    private val transferGateway: DownloadTransferGateway,
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val runtime = DownloadsRuntime(catalog)
    private val mutableUiState = MutableStateFlow<DownloadPreparationUiState>(
        DownloadPreparationUiState.CheckingExisting,
    )
    val uiState: StateFlow<DownloadPreparationUiState> = mutableUiState.asStateFlow()
    private val completedArtifacts = Channel<PreparedDownloadArtifact>(Channel.BUFFERED)
    val completed = completedArtifacts.receiveAsFlow()
    private var preparationJob: Job? = null

    init {
        start()
    }

    fun retry() {
        if (preparationJob?.isActive == true) return
        mutableUiState.value = DownloadPreparationUiState.CheckingExisting
        start()
    }

    fun cancel(onCancelled: () -> Unit) {
        viewModelScope.launch {
            preparationJob?.cancelAndJoin()
            onCancelled()
        }
    }

    private fun start() {
        preparationJob = viewModelScope.launch {
            val descriptor = when (val bootstrap = bootstrapGateway.load(context, resourceId)) {
                is DownloadBootstrapSuccess -> bootstrap.bootstrap.descriptor
                is DownloadBootstrapFailure -> {
                    mutableUiState.value = DownloadPreparationUiState.Failed(bootstrap.error.code)
                    return@launch
                }
            }
            when (val decision = runtime.readerAccess(
                ReaderAccessRequest(
                    namespace = context.namespace,
                    resourceId = descriptor.identity.resourceId,
                    readerType = descriptor.readerType,
                    isOnline = true,
                    isDownloadable = descriptor.isDownloadable,
                ),
            )) {
                is ReaderLocalArtifact -> publishCompletion(decision.artifact)
                is ReaderUnavailable -> mutableUiState.value = DownloadPreparationUiState.Failed(decision.reasonCode)
                else -> if (decision == ReaderNeedsDownload && descriptor.isDownloadable) {
                    download(descriptor)
                } else {
                    mutableUiState.value = DownloadPreparationUiState.Failed(
                        if (descriptor.isDownloadable) "DOWNLOAD_NOT_REQUIRED_FOR_STREAM" else "DOWNLOAD_NOT_AVAILABLE_OFFLINE",
                    )
                }
            }
        }
    }

    private suspend fun download(descriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor) {
        mutableUiState.value = DownloadPreparationUiState.CreatingTask
        val task = DownloadTask(UUID.randomUUID().toString(), descriptor)
        var progressUpdates: Channel<Long>? = null
        var progressJob: Job? = null
        try {
            runtime.saveTask(task)
            runtime.transitionTask(context.namespace, task.id, downloadStartEvent())
            mutableUiState.value = DownloadPreparationUiState.Downloading(0, descriptor.source.totalBytes)
            progressUpdates = Channel(Channel.CONFLATED)
            progressJob = viewModelScope.launch {
                var persistedBytes = 0L
                for (transferredBytes in progressUpdates) {
                    if (transferredBytes <= persistedBytes || transferredBytes >= descriptor.source.totalBytes) continue
                    mutableUiState.value = DownloadPreparationUiState.Downloading(
                        transferredBytes,
                        descriptor.source.totalBytes,
                    )
                    runtime.transitionTask(
                        context.namespace,
                        task.id,
                        downloadBytesTransferredEvent(transferredBytes),
                    )
                    persistedBytes = transferredBytes
                }
            }
            when (val result = transferGateway.transfer(
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
                    runtime.transitionTask(context.namespace, task.id, downloadCompleteEvent(artifact))
                    publishCompletion(artifact)
                }
                is DownloadTransferFailure -> {
                    progressUpdates.close()
                    progressJob.join()
                    runtime.transitionTask(
                        context.namespace,
                        task.id,
                        downloadFailEvent(result.error.code, true),
                    )
                    mutableUiState.value = DownloadPreparationUiState.Failed(result.error.code)
                }
            }
        } catch (cancelled: CancellationException) {
            progressUpdates?.close()
            progressJob?.cancelAndJoin()
            withContext(NonCancellable) { catalog.deleteTask(context.namespace, task.id) }
            throw cancelled
        } catch (_: Exception) {
            progressUpdates?.close()
            progressJob?.cancelAndJoin()
            withContext(NonCancellable) {
                runCatching {
                    runtime.transitionTask(
                        context.namespace,
                        task.id,
                        downloadFailEvent("DOWNLOAD_FAILED", true),
                    )
                }
            }
            mutableUiState.value = DownloadPreparationUiState.Failed("DOWNLOAD_FAILED")
        }
    }

    private suspend fun publishCompletion(artifact: CompletedDownloadArtifact) {
        mutableUiState.value = DownloadPreparationUiState.Completed
        completedArtifacts.send(
            PreparedDownloadArtifact(
                bookId = artifact.identity.bookId,
                resourceId = artifact.identity.resourceId,
                assetId = artifact.identity.assetId,
                localReference = artifact.localReference,
                expectedBytes = artifact.verifiedBytes,
                format = artifact.descriptor.format,
            ),
        )
    }

    companion object {
        fun factory(
            resourceId: String,
            context: DownloadRequestContext,
            catalog: DownloadCatalogRepository,
            sink: DownloadByteSink,
            bootstrapGateway: DownloadBootstrapGateway,
            transferGateway: DownloadTransferGateway,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                DownloadPreparationViewModel(resourceId, context, catalog, sink, bootstrapGateway, transferGateway)
            }
        }
    }
}
