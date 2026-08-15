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
    )

    private fun artifact() = CompletedDownloadArtifact(descriptor(), "local://volume", 10, 1)
}
