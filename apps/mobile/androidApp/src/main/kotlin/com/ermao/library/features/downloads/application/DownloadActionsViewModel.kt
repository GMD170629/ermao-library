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
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadResourceRuntime
import com.ermao.library.shared.modules.downloads.DownloadResourceFailure
import com.ermao.library.shared.modules.downloads.KtorDownloadsGateway
import com.ermao.library.shared.modules.downloads.DownloadBatchPolicy
import com.ermao.library.features.downloads.infrastructure.toShared
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadStorageException
import kotlinx.coroutines.CancellationException
import java.io.IOException
import com.ermao.library.shared.modules.downloads.DownloadBatchResult
import java.util.UUID
import java.util.logging.Logger
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class DownloadActionsViewModel(
    private val androidCatalog: AndroidDownloadCatalog,
    private val sharedCatalog: DownloadCatalogRepository,
    private val sink: AtomicDownloadFileSink,
    private val gateway: KtorDownloadsGateway,
    private val context: DownloadRequestContext,
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
) : ViewModel() {
    private val runtime = DownloadResourceRuntime(sharedCatalog, gateway, nowEpochMillis)
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

    fun readerLaunchCoordinator() = com.ermao.library.shared.modules.reader.ReaderLaunchCoordinator(sharedCatalog, gateway)
    val requestContext: DownloadRequestContext get() = context
    fun isActive(resourceId: String): Boolean = activeTransfers[resourceId]?.isActive == true

    init {
        viewModelScope.launch {
            androidCatalog.observe(namespace).collect { records ->
                mutableRecordsByResource.value = records
                    .groupBy(AndroidDownloadRecord::resourceId)
                    .mapValues { (_, assets) -> assets.maxBy(AndroidDownloadRecord::updatedAtEpochMillis) }
            }
        }
        viewModelScope.launch { containTaskFailure("recovery") { runtime.recoverInterrupted(context.namespace) } }
    }

    fun requestDownload(resourceId: String) = requestDownload(resourceId, null)

    fun requestDownload(resourceId: String, expectedDescriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor?) {
        if (resourceId.isBlank() || activeTransfers[resourceId]?.isActive == true) return
        mutableFailureByResource.value -= resourceId
        val job = viewModelScope.launch {
            containTaskFailure(resourceId) {
                when (val result = runtime.download(context, resourceId, UUID.randomUUID().toString(), sink, expectedDescriptor = expectedDescriptor)) {
                    is DownloadResourceFailure -> saveBootstrapFailure(resourceId, result.error.code)
                    else -> Unit
                }
            }
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
        val result = DownloadBatchResult(resourceIds.sorted().map { resourceId ->
            val record = records[resourceId]
            DownloadBatchPolicy.decide(resourceId, record?.status?.toShared(), record?.errorCode,
                activeTransfers[resourceId]?.isActive == true)
        })
        result.requestedResourceIds.forEach(::requestDownload)
        onComplete(result)
    }

    fun cancelDownload(resourceId: String) { activeTransfers[resourceId]?.cancel() }

    fun cancelAll() {
        activeTransfers.values.forEach(Job::cancel)
    }

    override fun onCleared() {
        cancelAll()
        gateway.close()
        super.onCleared()
    }

    fun removeDownload(record: AndroidDownloadRecord) {
        viewModelScope.launch {
            activeTransfers[record.resourceId]?.cancelAndJoin()
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

    /** Native task boundary contains adapter failures; the shared catalog remains recoverable. */
    private suspend fun containTaskFailure(resourceId: String, action: suspend () -> Unit) {
        try { action() }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (error: Exception) {
            val code = if (error is IOException || error is AndroidDownloadStorageException) {
                "DOWNLOAD_STORAGE_FAILURE"
            } else "DOWNLOAD_TASK_FAILED"
            LOGGER.severe("event=download_task_failed resource=$resourceId code=$code")
            mutableFailureByResource.value += resourceId to code
        }
    }

    private suspend fun saveBootstrapFailure(resourceId: String, code: String) {
        mutableFailureByResource.value += resourceId to code
    }

    companion object {
        private val LOGGER = Logger.getLogger("Downloads")

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
