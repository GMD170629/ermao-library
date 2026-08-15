package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
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
    suspend fun deleteArtifact(namespace: DownloadNamespace, volumeId: String)
    suspend fun listTasks(namespace: DownloadNamespace): List<DownloadTask>
    suspend fun saveTask(task: DownloadTask)
    suspend fun deleteTask(namespace: DownloadNamespace, taskId: String)
    suspend fun clearNamespace(namespace: DownloadNamespace)
}

data class DownloadSinkRequest(
    val namespace: DownloadNamespace,
    val taskId: String,
    val volumeId: String,
    val expectedTotalBytes: Long,
    val resumeFromBytes: Long,
) {
    init {
        require(taskId.isNotBlank())
        require(volumeId.isNotBlank())
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
        volumeId: String,
    ): DownloadBootstrapResult
}

data class DownloadTransferRequest(
    val taskId: String,
    val descriptor: DownloadDescriptor,
    val resumeFromBytes: Long = 0,
) {
    init {
        require(taskId.isNotBlank())
        require(resumeFromBytes in 0 until descriptor.source.totalBytes)
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
