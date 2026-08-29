package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadArtifactKind
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class DownloadRequestContext(
    val profile: ServerProfile,
    val namespace: DownloadNamespace,
) {
    init {
        require(profile.serverIdentity == namespace.serverIdentity)
    }
}

interface DownloadCatalogRepository {
    @Throws(Exception::class)
    suspend fun listArtifacts(namespace: DownloadNamespace): List<CompletedDownloadArtifact>
    @Throws(Exception::class)
    suspend fun deleteArtifact(namespace: DownloadNamespace, identity: DownloadIdentity)
    @Throws(Exception::class)
    suspend fun listTasks(namespace: DownloadNamespace): List<DownloadTask>
    @Throws(Exception::class)
    suspend fun findTask(descriptor: DownloadDescriptor): DownloadTask? = listTasks(descriptor.identity.namespace)
        .firstOrNull { it.matchesDescriptor(descriptor) }
    @Throws(Exception::class)
    /** Atomically persists the task and its optional completed artifact in one catalog record. */
    suspend fun saveTask(task: DownloadTask)
    @Throws(Exception::class)
    suspend fun deleteTask(namespace: DownloadNamespace, taskId: String)
    @Throws(Exception::class)
    suspend fun clearNamespace(namespace: DownloadNamespace)
}

data class DownloadSinkRequest(
    val namespace: DownloadNamespace,
    val taskId: String,
    val resourceId: String,
    val assetId: String,
    val expectedTotalBytes: Long,
    val resumeFromBytes: Long,
    val artifactKind: DownloadArtifactKind = DownloadArtifactKind.SingleOriginalAsset,
) {
    init {
        require(taskId.isNotBlank())
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
        require(expectedTotalBytes > 0)
        require(resumeFromBytes in 0..expectedTotalBytes)
    }
}

data class DownloadStoredBytes(val partialBytes: Long, val completedReference: String? = null) {
    init { require(partialBytes >= 0); require(completedReference == null || completedReference.isNotBlank()) }
}

interface DownloadByteSink {
    /** Reconcile durable bytes after interruption, including publication before catalog commit. */
    @Throws(Exception::class)
    suspend fun inspect(request: DownloadSinkRequest): DownloadStoredBytes = DownloadStoredBytes(request.resumeFromBytes)
    /** Removes task-owned partial and published bytes before an exact task is rebuilt. */
    @Throws(Exception::class)
    suspend fun discard(request: DownloadSinkRequest) = Unit
    @Throws(Exception::class)
    suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession
}

interface DownloadByteSinkSession {
    @Throws(Exception::class)
    suspend fun write(bytes: ByteArray)
    @Throws(Exception::class)
    suspend fun commit(expectedTotalBytes: Long): String
    @Throws(Exception::class)
    suspend fun abort()
    @Throws(Exception::class)
    suspend fun pause() = abort()
}

data class DownloadBundleSinkRequest(
    val namespace: DownloadNamespace,
    val taskId: String,
    val resourceId: String,
    val artifactId: String,
    val artifactKind: DownloadArtifactKind,
    val memberCount: Int,
    val expectedTotalBytes: Long,
) {
    init {
        require(taskId.isNotBlank())
        require(resourceId.isNotBlank())
        require(artifactId.isNotBlank())
        require(artifactKind == DownloadArtifactKind.OriginalPageSet)
        require(memberCount > 0)
        require(expectedTotalBytes > 0)
    }
}

data class DownloadBundleMemberSinkRequest(
    val assetId: String,
    val sequenceIndex: Int,
    val mimeType: String,
    val expectedBytes: Long,
) {
    init {
        require(assetId.isNotBlank())
        require(sequenceIndex >= 0)
        require(mimeType.isNotBlank())
        require(expectedBytes > 0)
    }
}

interface DownloadBundleByteSink {
    @Throws(Exception::class)
    suspend fun beginBundle(request: DownloadBundleSinkRequest): DownloadBundleByteSinkSession
}

interface DownloadBundleByteSinkSession {
    @Throws(Exception::class)
    suspend fun beginMember(request: DownloadBundleMemberSinkRequest): DownloadByteSinkSession
    @Throws(Exception::class)
    suspend fun commit(): String
    @Throws(Exception::class)
    suspend fun abort()
}

data class DownloadBootstrap(
    val descriptor: DownloadDescriptor,
)

sealed interface DownloadBootstrapResult {
    data class Success(val bootstrap: DownloadBootstrap) : DownloadBootstrapResult
    data class Failure(val error: AppError) : DownloadBootstrapResult
}

interface DownloadBootstrapGateway {
    suspend fun load(
        context: DownloadRequestContext,
        resourceId: String,
    ): DownloadBootstrapResult
}

data class DownloadTransferRequest(
    val taskId: String,
    val descriptor: DownloadDescriptor,
    val resumeFromBytes: Long = 0,
    val preservePartialOnCancellation: Boolean = false,
) {
    init {
        require(taskId.isNotBlank())
        require(descriptor.isDownloadable) { "Download descriptor is streaming-only" }
        require(resumeFromBytes in 0 until descriptor.totalBytes)
        require(resumeFromBytes == 0L || descriptor.artifactKind == DownloadArtifactKind.SingleOriginalAsset) {
            "Page-set downloads restart as an atomic bundle"
        }
    }
}

fun interface DownloadProgressObserver {
    fun onProgress(transferredBytes: Long, totalBytes: Long)
}

data class CompletedTransfer(
    val localReference: String,
    val verifiedBytes: Long,
    val etag: String?,
    val lastModified: String?,
)

sealed interface DownloadTransferResult {
    data class Success(val transfer: CompletedTransfer) : DownloadTransferResult
    data class Failure(val error: AppError) : DownloadTransferResult
}

interface DownloadTransferGateway {
    suspend fun transfer(
        context: DownloadRequestContext,
        request: DownloadTransferRequest,
        sink: DownloadByteSink,
        progressObserver: DownloadProgressObserver? = null,
    ): DownloadTransferResult
}

interface DownloadsGateway : DownloadBootstrapGateway, DownloadTransferGateway
