package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
import com.ermao.library.shared.modules.downloads.domain.DownloadedWork
import com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision
import com.ermao.library.shared.modules.downloads.domain.ReaderAccessPolicy
import com.ermao.library.shared.modules.downloads.domain.ReaderAccessRequest
import com.ermao.library.shared.modules.downloads.domain.completedDownloadsByWork
import com.ermao.library.shared.modules.downloads.domain.transition

class DownloadsRuntime(
    private val catalog: DownloadCatalogRepository,
    private val readerAccessPolicy: ReaderAccessPolicy = ReaderAccessPolicy(),
) {
    suspend fun downloadedWorks(
        namespace: DownloadNamespace,
        query: String = "",
    ): List<DownloadedWork> = completedDownloadsByWork(
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

    suspend fun removeArtifact(namespace: DownloadNamespace, volumeId: String) {
        require(volumeId.isNotBlank())
        catalog.deleteArtifact(namespace, volumeId)
    }

    suspend fun readerAccess(request: ReaderAccessRequest): ReaderAccessDecision =
        readerAccessPolicy.decide(request, catalog.listArtifacts(request.namespace))

    suspend fun artifact(
        namespace: DownloadNamespace,
        volumeId: String,
    ): CompletedDownloadArtifact? = catalog.listArtifacts(namespace).firstOrNull {
        it.identity.volumeId == volumeId
    }
}

class InMemoryDownloadCatalogRepository : DownloadCatalogRepository {
    private val artifacts = mutableMapOf<String, CompletedDownloadArtifact>()
    private val tasks = mutableMapOf<String, DownloadTask>()

    override suspend fun listArtifacts(namespace: DownloadNamespace): List<CompletedDownloadArtifact> =
        artifacts.values.filter { it.identity.namespace == namespace }

    override suspend fun saveArtifact(artifact: CompletedDownloadArtifact) {
        artifacts[artifactKey(artifact.identity.namespace, artifact.identity.volumeId)] = artifact
    }

    override suspend fun deleteArtifact(namespace: DownloadNamespace, volumeId: String) {
        artifacts.remove(artifactKey(namespace, volumeId))
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

    private fun artifactKey(namespace: DownloadNamespace, volumeId: String) = "${namespace.stableKey}:artifact:$volumeId"
    private fun taskKey(namespace: DownloadNamespace, taskId: String) = "${namespace.stableKey}:task:$taskId"
}
