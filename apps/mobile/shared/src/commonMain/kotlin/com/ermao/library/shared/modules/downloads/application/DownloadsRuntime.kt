package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
import com.ermao.library.shared.modules.downloads.domain.DownloadedBook
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.completedDownloadsByBook
import com.ermao.library.shared.modules.downloads.domain.transition

class DownloadsRuntime(
    private val catalog: DownloadCatalogRepository,
) {
    suspend fun downloadedBooks(
        namespace: DownloadNamespace,
        query: String = "",
    ): List<DownloadedBook> = completedDownloadsByBook(
        namespace,
        catalog.listArtifacts(namespace),
        query,
    )

    suspend fun saveTask(task: DownloadTask) {
        catalog.saveTask(task)
    }

    suspend fun transitionTask(
        namespace: DownloadNamespace,
        taskId: String,
        event: DownloadTaskEvent,
    ): DownloadTask {
        val current = catalog.listTasks(namespace).firstOrNull { it.id == taskId }
            ?: error("DOWNLOAD_TASK_NOT_FOUND")
        val next = current.transition(event)
        catalog.saveTask(next)
        if (next.artifact != null) catalog.saveArtifact(next.artifact)
        return next
    }

    suspend fun removeArtifact(namespace: DownloadNamespace, identity: DownloadIdentity) {
        catalog.deleteArtifact(namespace, identity)
    }

    suspend fun artifact(
        namespace: DownloadNamespace,
        resourceId: String,
    ): CompletedDownloadArtifact? = catalog.listArtifacts(namespace).firstOrNull {
        it.identity.resourceId == resourceId
    }
}

class InMemoryDownloadCatalogRepository : DownloadCatalogRepository {
    private val artifacts = mutableMapOf<String, CompletedDownloadArtifact>()
    private val tasks = mutableMapOf<String, DownloadTask>()

    override suspend fun listArtifacts(namespace: DownloadNamespace): List<CompletedDownloadArtifact> =
        artifacts.values.filter { it.identity.namespace == namespace }

    override suspend fun saveArtifact(artifact: CompletedDownloadArtifact) {
        artifacts[artifactKey(artifact.identity)] = artifact
    }

    override suspend fun deleteArtifact(namespace: DownloadNamespace, identity: DownloadIdentity) {
        artifacts.remove(artifactKey(identity))
    }

    override suspend fun listTasks(namespace: DownloadNamespace): List<DownloadTask> =
        tasks.values.filter { it.descriptor.identity.namespace == namespace }

    override suspend fun saveTask(task: DownloadTask) {
        tasks[taskKey(task.descriptor.identity.namespace, task.id)] = task
    }

    override suspend fun deleteTask(namespace: DownloadNamespace, taskId: String) {
        tasks.remove(taskKey(namespace, taskId))
    }

    override suspend fun clearNamespace(namespace: DownloadNamespace) {
        artifacts.entries.removeAll { it.value.identity.namespace == namespace }
        tasks.entries.removeAll { it.value.descriptor.identity.namespace == namespace }
    }

    private fun artifactKey(identity: DownloadIdentity) = "${identity.namespace.stableKey}:artifact:${identity.bookId}:${identity.resourceId}:${identity.assetId}"
    private fun taskKey(namespace: DownloadNamespace, taskId: String) = "${namespace.stableKey}:task:$taskId"
}
