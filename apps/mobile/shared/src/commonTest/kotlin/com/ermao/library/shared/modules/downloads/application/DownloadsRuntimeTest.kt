package com.ermao.library.shared.modules.downloads.application

import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
import com.ermao.library.shared.modules.downloads.domain.DownloadSource
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision
import com.ermao.library.shared.modules.downloads.domain.ReaderAccessRequest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.runBlocking

class DownloadsRuntimeTest {
    @Test
    fun rehomesCompletedArtifactWithoutChangingItsLocalFile() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(catalog)
        val artifact = artifact()
        catalog.saveArtifact(artifact)

        val moved = runtime.rehomeCompletedArtifact(
            namespace = artifact.identity.namespace,
            volumeId = artifact.identity.volumeId,
            targetWorkId = "work-b",
            targetVersionId = "version-b",
            targetVersionSourceKey = "kindle",
            targetVersionSourceName = "Kindle",
            targetWorkTitle = "Moved work",
            targetWorkAuthor = "Author B",
            targetCoverApiPath = "/api/works/work-b/cover",
            targetVersionCompleted = true,
        )

        assertEquals("work-b", moved?.identity?.workId)
        assertEquals("version-b", moved?.descriptor?.versionId)
        assertEquals("kindle", moved?.descriptor?.versionSourceKey)
        assertEquals("Kindle", moved?.descriptor?.versionSourceName)
        assertEquals(true, moved?.descriptor?.versionCompleted)
        assertEquals(artifact.localReference, moved?.localReference)
        assertEquals(listOf(moved), catalog.listArtifacts(artifact.identity.namespace))
    }

    @Test
    fun completingTaskPublishesArtifactOnlyAfterExplicitCompletion() = runBlocking {
        val repository = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(repository)
        val task = DownloadTask("task", descriptor())
        runtime.saveTask(task)

        runtime.transitionTask(namespace, "task", DownloadTaskEvent.Start)
        runtime.transitionTask(namespace, "task", DownloadTaskEvent.BytesTransferred(10))
        assertEquals(emptyList(), runtime.downloadedWorks(namespace))

        val completed = runtime.transitionTask(
            namespace,
            "task",
            DownloadTaskEvent.Complete(artifact()),
        )
        assertEquals(DownloadTaskStatus.Completed, completed.status)
        assertEquals(listOf("work"), runtime.downloadedWorks(namespace).map { it.workId })
        assertIs<ReaderAccessDecision.LocalArtifact>(
            runtime.readerAccess(
                ReaderAccessRequest(namespace, "volume", DownloadReaderType.Reflowable, false),
            ),
        )
        Unit
    }

    private val namespace = DownloadNamespace("server", "user", 1)

    private fun descriptor() = DownloadDescriptor(
        DownloadIdentity(namespace, "work", "volume"),
        "Book",
        "Author",
        "/api/works/work/cover",
        "Volume",
        "EPUB",
        DownloadReaderType.Reflowable,
        DownloadSource("/api/volumes/volume/file", "application/epub+zip", 10),
        versionId = "version",
        versionSourceKey = "__implicit__",
        versionSourceName = null,
        versionCompleted = false,
    )

    private fun artifact() = CompletedDownloadArtifact(descriptor(), "local://volume", 10, 1)
}
