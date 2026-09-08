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
import com.ermao.library.shared.modules.downloads.DownloadManagementAction
import com.ermao.library.shared.modules.downloads.DownloadManagementItem
import com.ermao.library.shared.modules.downloads.DownloadManagementOutcome
import com.ermao.library.shared.modules.downloads.DownloadManagementPolicy
import com.ermao.library.shared.modules.downloads.DownloadManagementResult
import com.ermao.library.shared.modules.downloads.DownloadManagementResource
import com.ermao.library.shared.modules.downloads.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.pauseDownloadTask
import com.ermao.library.features.downloads.infrastructure.toShared
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadStorageException
import kotlinx.coroutines.CancellationException
import java.io.IOException
import java.util.UUID
import java.util.logging.Logger
import kotlinx.coroutines.Job
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
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
    private val transferDispatcher: CoroutineDispatcher = Dispatchers.IO,
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
    private val mutableActiveResourceIds = MutableStateFlow<Set<String>>(emptySet())
    /** Live transfer ownership, supplied to the shared management policy. */
    val activeResourceIds: StateFlow<Set<String>> = mutableActiveResourceIds.asStateFlow()
    private val activeTransfers = mutableMapOf<String, Job>()
    private val readerOwnedTransfers = mutableSetOf<String>()
    /**
     * The catalog observer can emit on every transfer progress update. Keep the
     * last catalog facts so local files are validated only when the completed
     * record itself changes; action execution still performs a fresh validation.
     */
    private var lastObservedCatalogRecords: Map<String, AndroidDownloadRecord> = emptyMap()

    fun readerLaunchCoordinator() = com.ermao.library.shared.modules.reader.ReaderLaunchCoordinator(sharedCatalog, gateway)
    val requestContext: DownloadRequestContext get() = context
    fun isActive(resourceId: String): Boolean = activeTransfers[resourceId]?.isActive == true

    init {
        viewModelScope.launch {
            androidCatalog.observe(namespace).collect { records ->
                val latestByResource = records
                    .groupBy(AndroidDownloadRecord::resourceId)
                    .mapValues { (_, assets) -> assets.maxBy(AndroidDownloadRecord::updatedAtEpochMillis) }
                val previousCatalogRecords = lastObservedCatalogRecords
                val previousProjectedRecords = mutableRecordsByResource.value
                val projected = withContext(transferDispatcher) {
                    latestByResource.mapValues { (resourceId, record) ->
                        val previous = previousCatalogRecords[resourceId]
                        val recordChanged = previous != record
                        if (!recordChanged) {
                            // Reuse the prior projection so a missing completed
                            // artifact remains InvalidLocal until the catalog row
                            // changes or an action explicitly revalidates it.
                            previousProjectedRecords[resourceId] ?: record
                        } else if (
                            record.status == com.ermao.library.features.downloads.model.AndroidDownloadStatus.Completed &&
                            record.verified &&
                            !sink.hasLocalArtifact(record.localReference, record.expectedBytes)
                        ) {
                            // Preserve a durable completed row when its file has
                            // disappeared; the shared policy will project it as
                            // InvalidLocal and offer Retry instead of Open.
                            record.copy(
                                verified = false,
                                errorCode = record.errorCode ?: "DOWNLOAD_LOCAL_FILE_INVALID",
                            )
                        } else {
                            record
                        }
                    }
                }
                lastObservedCatalogRecords = latestByResource
                mutableRecordsByResource.value = projected
            }
        }
        viewModelScope.launch {
            withContext(transferDispatcher) {
                containTaskFailure("recovery") { runtime.recoverInterrupted(context.namespace) }
            }
        }
    }

    fun requestDownload(resourceId: String) {
        enqueueDownload(resourceId, null, readerOwned = false)
    }

    fun requestDownload(resourceId: String, expectedDescriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor?) {
        enqueueDownload(resourceId, expectedDescriptor, readerOwned = false)
    }

    /** Starts or rejoins a Reader-owned transfer across Activity recreation. */
    fun requestReaderDownload(
        resourceId: String,
        expectedDescriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor,
    ): Boolean = enqueueDownload(resourceId, expectedDescriptor, readerOwned = true)

    /**
     * Re-checks the currently visible panel scope when it opens. The catalog
     * has no revision when a user deletes a managed file externally, so an
     * unchanged observer snapshot alone cannot surface InvalidLocal.
     */
    fun refreshLocalArtifactFacts(resourceIds: Set<String>) {
        val requestedIds = resourceIds.filter(String::isNotBlank).toSet()
        if (requestedIds.isEmpty()) return
        viewModelScope.launch {
            val refreshed = withContext(transferDispatcher) {
                androidCatalog.records(namespace)
                    .filter { it.resourceId in requestedIds }
                    .groupBy(AndroidDownloadRecord::resourceId)
                    .mapValues { (_, assets) ->
                        assets.maxBy(AndroidDownloadRecord::updatedAtEpochMillis).let { record ->
                            if (
                                record.status == com.ermao.library.features.downloads.model.AndroidDownloadStatus.Completed &&
                                record.verified &&
                                !sink.hasLocalArtifact(record.localReference, record.expectedBytes)
                            ) {
                                record.copy(
                                    verified = false,
                                    errorCode = record.errorCode ?: "DOWNLOAD_LOCAL_FILE_INVALID",
                                )
                            } else {
                                record
                            }
                        }
                    }
            }
            if (refreshed.isNotEmpty()) {
                mutableRecordsByResource.value = mutableRecordsByResource.value + refreshed
            }
        }
    }

    private fun enqueueDownload(
        resourceId: String,
        expectedDescriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor?,
        readerOwned: Boolean,
    ): Boolean {
        if (resourceId.isBlank()) return false
        if (activeTransfers[resourceId]?.isActive == true) return resourceId in readerOwnedTransfers
        if (readerOwned) readerOwnedTransfers += resourceId
        launchDownload(resourceId, expectedDescriptor)
        return readerOwned
    }

    /** Accepts one transfer request and returns whether a new live job was installed. */
    private fun acceptDownload(
        resourceId: String,
        expectedDescriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor? = null,
    ): Boolean {
        if (resourceId.isBlank() || activeTransfers[resourceId]?.isActive == true) return false
        launchDownload(resourceId, expectedDescriptor)
        return activeTransfers[resourceId]?.isActive == true
    }

    private fun launchDownload(
        resourceId: String,
        expectedDescriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor?,
    ) {
        mutableFailureByResource.value -= resourceId
        val job = viewModelScope.launch {
            withContext(transferDispatcher) {
                containTaskFailure(resourceId) {
                    when (val result = runtime.ensure(context, resourceId, UUID.randomUUID().toString(), sink,
                        expectedDescriptor = expectedDescriptor)) {
                        is DownloadResourceFailure -> saveBootstrapFailure(resourceId, result.error.code)
                        else -> Unit
                    }
                }
            }
        }
        activeTransfers[resourceId] = job
        mutableActiveResourceIds.value = activeTransfers
            .filterValues { it.isActive }
            .keys
            .toSet()
        job.invokeOnCompletion {
            activeTransfers.remove(resourceId, job)
            readerOwnedTransfers.remove(resourceId)
            mutableActiveResourceIds.value = activeTransfers
                .filterValues { it.isActive }
                .keys
                .toSet()
        }
    }

    /**
     * Executes one management action against the latest catalog snapshot.
     * Download, Resume and Retry are accepted when a transfer job is installed;
     * Pause and Remove complete only after the job has joined and local storage
     * has been updated.
     */
    suspend fun executeManagementAction(
        action: DownloadManagementAction,
        resourceId: String,
        available: Boolean = true,
    ): DownloadManagementResult = executeManagementActions(
        action = action,
        selectedResourceIds = setOf(resourceId),
        availableResourceIds = if (available) setOf(resourceId) else emptySet(),
    ).single()

    suspend fun executeManagementActions(
        action: DownloadManagementAction,
        selectedResourceIds: Set<String>,
        availableResourceIds: Set<String> = selectedResourceIds,
    ): List<DownloadManagementResult> {
        if (selectedResourceIds.isEmpty()) return emptyList()
        return selectedResourceIds.sorted().map { resourceId ->
            try {
                // Re-read and re-project before every item. A preceding action
                // may have changed the task or active transfer, so a batch must
                // never execute from one stale eligibility snapshot.
                val record = latestRecord(resourceId)
                val resource = projectManagementResource(resourceId, record, resourceId in availableResourceIds)
                val applicable = DownloadManagementPolicy.applicable(action, setOf(resourceId), listOf(resource))
                if (applicable.isEmpty()) {
                    DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Skipped)
                } else {
                    executeApplicableAction(action, resourceId)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                val code = failureCode(error)
                mutableFailureByResource.value += resourceId to code
                LOGGER.severe("event=download_management_projection_failed resource=$resourceId action=$action code=$code")
                DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Failed, code)
            }
        }
    }

    /** Callback adapter for Compose callers; the actual operation remains awaitable in tests. */
    fun performManagementAction(
        action: DownloadManagementAction,
        selectedResourceIds: Set<String>,
        availableResourceIds: Set<String> = selectedResourceIds,
        onComplete: (List<DownloadManagementResult>) -> Unit,
    ) {
        viewModelScope.launch {
            val result = try {
                executeManagementActions(action, selectedResourceIds, availableResourceIds)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                selectedResourceIds.sorted().map { resourceId ->
                    val code = failureCode(error)
                    mutableFailureByResource.value += resourceId to code
                    DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Failed, code)
                }
            }
            onComplete(result)
        }
    }

    private suspend fun executeApplicableAction(
        action: DownloadManagementAction,
        resourceId: String,
    ): DownloadManagementResult = try {
        when (action) {
            DownloadManagementAction.Download,
            DownloadManagementAction.Resume,
            DownloadManagementAction.Retry,
            -> if (acceptDownload(resourceId)) {
                DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Accepted)
            } else {
                DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Skipped)
            }
            DownloadManagementAction.Pause -> {
                if (pauseDownloadAndJoin(resourceId)) {
                    DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Completed)
                } else {
                    DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Skipped)
                }
            }
            DownloadManagementAction.Remove -> {
                if (removeDownloadAndJoin(resourceId)) {
                    DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Completed)
                } else {
                    DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Skipped)
                }
            }
            DownloadManagementAction.Open ->
                DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Completed)
        }
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (error: Exception) {
        val code = failureCode(error)
        mutableFailureByResource.value += resourceId to code
        LOGGER.severe("event=download_management_failed resource=$resourceId action=$action code=$code")
        DownloadManagementResult(resourceId, action, DownloadManagementOutcome.Failed, code)
    }

    private suspend fun pauseDownloadAndJoin(resourceId: String): Boolean {
        activeTransfers[resourceId]?.let { job ->
            job.cancel()
            job.cancelAndJoin()
        }
        val task = withContext(transferDispatcher) {
            sharedCatalog.listTasks(context.namespace)
                .filter { it.descriptor.identity.resourceId == resourceId }
                .firstOrNull()
        } ?: return false
        return when (task.status) {
            DownloadTaskStatus.Queued,
            DownloadTaskStatus.Downloading,
            -> {
                withContext(transferDispatcher) { sharedCatalog.saveTask(pauseDownloadTask(task)) }
                true
            }
            DownloadTaskStatus.Paused,
            DownloadTaskStatus.WaitingForWifi,
            -> true
            else -> false
        }
    }

    private suspend fun removeDownloadAndJoin(resourceId: String): Boolean {
        activeTransfers[resourceId]?.let { job ->
            job.cancel()
            job.cancelAndJoin()
        }
        val tasks = withContext(transferDispatcher) {
            sharedCatalog.listTasks(context.namespace)
                .filter { it.descriptor.identity.resourceId == resourceId }
        }
        if (tasks.isEmpty()) return false
        withContext(transferDispatcher) {
            tasks.forEach { sharedCatalog.deleteTask(context.namespace, it.id) }
        }
        return true
    }

    private fun hasVerifiedLocalArtifact(record: AndroidDownloadRecord): Boolean =
        record.verified && sink.hasLocalArtifact(record.localReference, record.expectedBytes)

    private suspend fun latestRecord(resourceId: String): AndroidDownloadRecord? = withContext(transferDispatcher) {
        androidCatalog.records(namespace)
            .asSequence()
            .filter { it.resourceId == resourceId }
            .maxByOrNull(AndroidDownloadRecord::updatedAtEpochMillis)
    }

    private suspend fun projectManagementResource(
        resourceId: String,
        record: AndroidDownloadRecord?,
        available: Boolean,
    ): DownloadManagementResource {
        val verified = withContext(transferDispatcher) {
            record?.let(::hasVerifiedLocalArtifact) == true
        }
        val resource = DownloadManagementPolicy.project(
            DownloadManagementItem(
                resourceId = resourceId,
                status = record?.status?.toShared(),
                verified = verified,
                active = isActive(resourceId),
                available = available,
                failureCode = record?.errorCode,
            ),
        )
        if (
            record?.status == com.ermao.library.features.downloads.model.AndroidDownloadStatus.Completed &&
            record.verified &&
            !verified
        ) {
            val invalidRecord = record.copy(
                verified = false,
                errorCode = record.errorCode ?: "DOWNLOAD_LOCAL_FILE_INVALID",
            )
            mutableRecordsByResource.value = mutableRecordsByResource.value + (resourceId to invalidRecord)
        }
        return resource
    }

    private fun failureCode(error: Throwable): String = when (error) {
        is AndroidDownloadStorageException,
        is IOException,
        -> "DOWNLOAD_STORAGE_FAILURE"
        else -> "DOWNLOAD_TASK_FAILED"
    }

    fun cancelDownload(resourceId: String) { activeTransfers[resourceId]?.cancel() }

    fun cancelReaderDownload(resourceId: String) {
        if (readerOwnedTransfers.remove(resourceId)) activeTransfers[resourceId]?.cancel()
    }

    fun cancelAll() {
        readerOwnedTransfers.clear()
        activeTransfers.values.forEach(Job::cancel)
    }

    override fun onCleared() {
        cancelAll()
        gateway.close()
        super.onCleared()
    }

    fun removeDownload(record: AndroidDownloadRecord) {
        viewModelScope.launch {
            activeTransfers[record.resourceId]?.let { job ->
                job.cancel()
                job.cancelAndJoin()
            }
            withContext(transferDispatcher) {
                // The downloads center removes the exact task the user chose.
                // Resource-level management intentionally removes every asset
                // belonging to a resource, but this legacy entry point must
                // preserve its task identity contract.
                sharedCatalog.deleteTask(context.namespace, record.taskId)
            }
        }
    }

    fun removeBook(bookId: String) {
        if (bookId.isBlank()) return
        viewModelScope.launch {
            val tasks = sharedCatalog.listTasks(context.namespace).filter { it.descriptor.identity.bookId == bookId }
            tasks.forEach { task ->
                activeTransfers[task.descriptor.identity.resourceId]?.let { job ->
                    job.cancel()
                    job.cancelAndJoin()
                }
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
        mutableActiveResourceIds.value = emptySet()
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
