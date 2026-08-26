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
    suspend fun listArtifacts(namespace: DownloadNamespace): List<CompletedDownloadArtifact>
    suspend fun saveArtifact(artifact: CompletedDownloadArtifact)
    suspend fun deleteArtifact(namespace: DownloadNamespace, identity: DownloadIdentity)
    suspend fun listTasks(namespace: DownloadNamespace): List<DownloadTask>
    suspend fun saveTask(task: DownloadTask)
    suspend fun deleteTask(namespace: DownloadNamespace, taskId: String)
    suspend fun clearNamespace(namespace: DownloadNamespace)
}

data class DownloadSinkRequest(
    val namespace: DownloadNamespace,
    val taskId: String,
    val resourceId: String,
    val assetId: String,
    val expectedTotalBytes: Long,
    val resumeFromBytes: Long,
) {
    init {
        require(taskId.isNotBlank())
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
        require(expectedTotalBytes > 0)
        require(resumeFromBytes in 0 until expectedTotalBytes)
    }
}

interface DownloadByteSink {
    suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession
}

interface DownloadByteSinkSession {
    suspend fun write(bytes: ByteArray)
    suspend fun commit(expectedTotalBytes: Long): String
    suspend fun abort()
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
    suspend fun beginBundle(request: DownloadBundleSinkRequest): DownloadBundleByteSinkSession
}

interface DownloadBundleByteSinkSession {
    suspend fun beginMember(request: DownloadBundleMemberSinkRequest): DownloadByteSinkSession
    suspend fun commit(): String
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
    val ifRangeValidator: String? = null,
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
