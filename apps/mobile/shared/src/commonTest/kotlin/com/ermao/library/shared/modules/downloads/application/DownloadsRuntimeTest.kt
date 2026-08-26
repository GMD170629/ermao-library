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
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals

class DownloadsRuntimeTest {
    @Test
    fun completingTaskPublishesBookResourceAssetOnlyAfterExplicitCompletion() = runBlocking {
        val repository = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(repository)
        val task = DownloadTask("task", descriptor())
        runtime.saveTask(task)

        runtime.transitionTask(namespace, "task", DownloadTaskEvent.Start)
        runtime.transitionTask(namespace, "task", DownloadTaskEvent.BytesTransferred(10))
        assertEquals(emptyList(), runtime.downloadedBooks(namespace))

        val completed = runtime.transitionTask(
            namespace,
            "task",
            DownloadTaskEvent.Complete(artifact()),
        )
        assertEquals(DownloadTaskStatus.Completed, completed.status)
        val book = runtime.downloadedBooks(namespace).single()
        assertEquals("book", book.bookId)
        assertEquals(listOf("resource"), book.resources.map { it.resourceId })
        assertEquals(listOf("asset"), book.artifacts.map { it.identity.assetId })
    }

    private val namespace = DownloadNamespace("server", "user", 1)

    private fun descriptor() = DownloadDescriptor(
        identity = DownloadIdentity(namespace, "book", "resource", "asset"),
        bookTitle = "Book",
        bookAuthor = "Author",
        coverApiPath = "/api/books/book/cover",
        resourceTitle = "Resource",
        format = "epub",
        readerType = DownloadReaderType.Reflowable,
        source = DownloadSource("/api/assets/asset", "application/epub+zip", 10),
    )

    private fun artifact() = CompletedDownloadArtifact(descriptor(), "local://asset", 10, 1)
}
