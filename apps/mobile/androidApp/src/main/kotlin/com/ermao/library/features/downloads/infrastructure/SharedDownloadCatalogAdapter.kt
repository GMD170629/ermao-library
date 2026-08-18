package com.ermao.library.features.downloads.infrastructure

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadIdentity
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadSource
import com.ermao.library.shared.modules.downloads.DownloadTask
import com.ermao.library.shared.modules.downloads.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.downloadReaderType

class SharedDownloadCatalogAdapter(
    private val catalog: AndroidDownloadCatalog,
    private val files: AtomicDownloadFileSink,
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
) : DownloadCatalogRepository {
    override suspend fun listArtifacts(namespace: DownloadNamespace): List<CompletedDownloadArtifact> =
        catalog.records(namespace.toAndroid()).mapNotNull { record ->
            record.takeIf(AndroidDownloadRecord::isReadable)
                ?.takeIf { files.hasLocalArtifact(it.localReference) }
                ?.toArtifact()
        }

    override suspend fun saveArtifact(artifact: CompletedDownloadArtifact) {
        val namespace = artifact.identity.namespace.toAndroid()
        val existing = catalog.records(namespace).firstOrNull {
            it.volumeId == artifact.identity.volumeId
        }
        replaceRecord(
            artifact.toRecord(
                taskId = existing?.taskId ?: "artifact-${artifact.identity.volumeId}",
                createdAtEpochMillis = existing?.createdAtEpochMillis ?: artifact.completedAtEpochMillis,
            ),
        )
    }

    override suspend fun deleteArtifact(namespace: DownloadNamespace, volumeId: String) {
        catalog.records(namespace.toAndroid())
            .filter { it.volumeId == volumeId && it.isReadable }
            .forEach { record ->
                catalog.remove(record.namespace, record.taskId)
                record.localReference?.let(files::resolveLocalReference)?.deleteManagedFile()
            }
    }

    override suspend fun listTasks(namespace: DownloadNamespace): List<DownloadTask> =
        catalog.records(namespace.toAndroid()).map(AndroidDownloadRecord::toTask)

    override suspend fun saveTask(task: DownloadTask) {
        val namespace = task.descriptor.identity.namespace.toAndroid()
        val existing = catalog.record(namespace, task.id)
        val now = nowEpochMillis()
        replaceRecord(task.toRecord(existing?.createdAtEpochMillis ?: now, now))
    }

    override suspend fun deleteTask(namespace: DownloadNamespace, taskId: String) {
        catalog.remove(namespace.toAndroid(), taskId)?.localReference
            ?.let(files::resolveLocalReference)?.deleteManagedFile()
    }

    override suspend fun clearNamespace(namespace: DownloadNamespace) {
        catalog.clear(namespace.toAndroid()).forEach { record ->
            record.localReference?.let(files::resolveLocalReference)?.deleteManagedFile()
        }
    }

    private suspend fun replaceRecord(record: AndroidDownloadRecord) {
        catalog.upsert(record).forEach { replaced ->
            if (replaced.localReference != record.localReference) {
                replaced.localReference?.let(files::resolveLocalReference)?.deleteManagedFile()
            }
        }
    }
}

private fun java.io.File.deleteManagedFile() {
    if (exists() && !delete()) throw AndroidDownloadStorageException("Unable to delete managed download")
}

private fun DownloadNamespace.toAndroid() = AndroidDownloadNamespace(serverIdentity, userId, authorizationVersion)

private fun AndroidDownloadRecord.toTask(): DownloadTask = DownloadTask(
    id = taskId,
    descriptor = descriptor(),
    status = status.toShared(),
    transferredBytes = transferredBytes,
    failureCode = errorCode,
    artifact = takeIf(AndroidDownloadRecord::isReadable)?.toArtifact(),
)

private fun AndroidDownloadRecord.descriptor() = DownloadDescriptor(
    identity = DownloadIdentity(
        namespace = DownloadNamespace(namespace.serverIdentity, namespace.userId, namespace.authorizationVersion),
        workId = workId,
        volumeId = volumeId,
    ),
    workTitle = workTitle,
    workAuthor = author.takeIf(String::isNotBlank),
    coverApiPath = coverUrl.takeIf(String::isNotBlank),
    versionId = versionId,
    versionSourceKey = versionSourceKey,
    versionSourceName = versionSourceName,
    versionCompleted = versionCompleted,
    volumeTitle = volumeTitle,
    format = format,
    readerType = downloadReaderType(readerType),
    source = DownloadSource(sourceApiPath, sourceMimeType, expectedBytes),
    volumeIndex = volumeIndex,
    volumeSortOrder = volumeSortOrder,
)

private fun AndroidDownloadRecord.toArtifact() = CompletedDownloadArtifact(
    descriptor = descriptor(),
    localReference = checkNotNull(localReference),
    verifiedBytes = expectedBytes,
    completedAtEpochMillis = updatedAtEpochMillis,
    lastOpenedAtEpochMillis = lastOpenedAtEpochMillis,
)

private fun DownloadTask.toRecord(createdAtEpochMillis: Long, updatedAtEpochMillis: Long): AndroidDownloadRecord {
    val descriptor = descriptor
    return AndroidDownloadRecord(
        taskId = id,
        namespace = descriptor.identity.namespace.toAndroid(),
        workId = descriptor.identity.workId,
        workTitle = descriptor.workTitle,
        author = descriptor.workAuthor.orEmpty(),
        coverUrl = descriptor.coverApiPath.orEmpty(),
        versionId = descriptor.versionId,
        versionSourceKey = descriptor.versionSourceKey,
        versionSourceName = descriptor.versionSourceName,
        versionCompleted = descriptor.versionCompleted,
        volumeId = descriptor.identity.volumeId,
        volumeTitle = descriptor.volumeTitle,
        format = descriptor.format,
        readerType = descriptor.readerType.name.lowercase(),
        sourceApiPath = descriptor.source.apiPath,
        sourceMimeType = descriptor.source.mimeType,
        expectedBytes = descriptor.source.totalBytes,
        transferredBytes = transferredBytes,
        status = status.toAndroid(),
        localReference = artifact?.localReference,
        verified = artifact != null,
        errorCode = failureCode,
        createdAtEpochMillis = createdAtEpochMillis,
        updatedAtEpochMillis = updatedAtEpochMillis,
        lastOpenedAtEpochMillis = artifact?.lastOpenedAtEpochMillis,
        volumeIndex = descriptor.volumeIndex,
        volumeSortOrder = descriptor.volumeSortOrder,
    )
}

private fun CompletedDownloadArtifact.toRecord(taskId: String, createdAtEpochMillis: Long): AndroidDownloadRecord =
    DownloadTask(
        id = taskId,
        descriptor = descriptor,
        status = DownloadTaskStatus.Completed,
        transferredBytes = verifiedBytes,
        artifact = this,
    ).toRecord(createdAtEpochMillis, completedAtEpochMillis)

private fun AndroidDownloadStatus.toShared(): DownloadTaskStatus = when (this) {
    AndroidDownloadStatus.Queued -> DownloadTaskStatus.Queued
    AndroidDownloadStatus.Downloading, AndroidDownloadStatus.Verifying -> DownloadTaskStatus.Downloading
    AndroidDownloadStatus.Paused -> DownloadTaskStatus.Paused
    AndroidDownloadStatus.Completed -> DownloadTaskStatus.Completed
    AndroidDownloadStatus.FailedRetryable -> DownloadTaskStatus.FailedRetryable
    AndroidDownloadStatus.FailedTerminal -> DownloadTaskStatus.FailedTerminal
}

private fun DownloadTaskStatus.toAndroid(): AndroidDownloadStatus = when (this) {
    DownloadTaskStatus.Queued -> AndroidDownloadStatus.Queued
    DownloadTaskStatus.Downloading -> AndroidDownloadStatus.Downloading
    DownloadTaskStatus.Paused, DownloadTaskStatus.WaitingForWifi -> AndroidDownloadStatus.Paused
    DownloadTaskStatus.InsufficientSpace, DownloadTaskStatus.FailedRetryable -> AndroidDownloadStatus.FailedRetryable
    DownloadTaskStatus.FailedTerminal, DownloadTaskStatus.Cancelled -> AndroidDownloadStatus.FailedTerminal
    DownloadTaskStatus.Completed -> AndroidDownloadStatus.Completed
}
