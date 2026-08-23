package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.groupReadableDownloads
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import org.junit.Test

class AndroidDownloadModelsTest {
    private val namespace = AndroidDownloadNamespace("server", "user", 3)

    @Test
    fun searchReturnsOnlyCompletedVerifiedExistingDownloadsGroupedByBook() {
        val records = listOf(
            record("task-1", "book-1", "三体", "刘慈欣", "第一卷", "/files/one", completed = true),
            record("task-2", "book-1", "三体", "刘慈欣", "第二卷", "/files/two", completed = true),
            record("task-3", "book-2", "流浪地球", "刘慈欣", "上册", "/files/missing", completed = true),
            record("task-4", "book-3", "Incomplete", "Author", "Resource", null, completed = false),
        )

        val result = groupReadableDownloads(records, "刘慈欣") { it.localReference != "/files/missing" }

        assertEquals(1, result.size)
        assertEquals("book-1", result.single().bookId)
        assertEquals(listOf("第一卷", "第二卷"), result.single().resources.map { it.title })
    }

    @Test
    fun completedBookPreservesResourceOrderAndGroupsMultipleAssets() {
        val records = listOf(
            record("task-2", "book-1", "Book", "Author", "Resource 2", "two.bin", completed = true).copy(
                resourceSortOrder = 2,
                assetId = "asset-2",
            ),
            record("task-1", "book-1", "Book", "Author", "Resource 1", "one.bin", completed = true).copy(
                resourceSortOrder = 1,
                assetId = "asset-1",
            ),
            record("task-1b", "book-1", "Book", "Author", "Resource 1", "one-track.bin", completed = true).copy(
                resourceId = "resource-task-1",
                resourceSortOrder = 1,
                assetId = "asset-1b",
            ),
        )

        val book = groupReadableDownloads(records, "") { true }.single()

        assertEquals(listOf("resource-task-1", "resource-task-1", "resource-task-2"), book.resources.flatMap { resource ->
            resource.artifacts.map { it.resourceId }
        })
        assertEquals(listOf("Resource 1", "Resource 2"), book.resources.map { it.title })
        assertEquals(listOf("asset-1", "asset-1b"), book.resources.first().artifacts.map { it.assetId })
    }

    @Test
    fun rehomedResourceGroupsUnderTargetBook() {
        val moved = record("task-1", "book-source", "Source", "Author", "Resource", "one.bin", completed = true).copy(
            bookId = "book-target",
            bookTitle = "Target",
        )

        val book = groupReadableDownloads(listOf(moved), "") { true }.single()

        assertEquals("book-target", book.bookId)
        assertEquals(listOf("resource-task-1"), book.resources.map { it.resourceId })
    }

    @Test
    fun catalogRecordCannotClaimCompletedWithoutVerifiedLocalReference() {
        assertFailsWith<IllegalArgumentException> {
            record("task", "book", "Title", "Author", "Resource", null, completed = true)
        }
    }

    private fun record(
        taskId: String,
        bookId: String,
        title: String,
        author: String,
        resource: String,
        localReference: String?,
        completed: Boolean,
    ) = AndroidDownloadRecord(
        taskId = taskId,
        namespace = namespace,
        bookId = bookId,
        bookTitle = title,
        author = author,
        coverUrl = "/api/books/$bookId/cover",
        resourceId = "resource-$taskId",
        resourceTitle = resource,
        format = "EPUB",
        readerType = "reflowable",
        assetId = "asset-$taskId",
        sourceApiPath = "/api/resources/resource-$taskId/asset",
        sourceMimeType = "application/epub+zip",
        expectedBytes = 20,
        transferredBytes = if (completed) 20 else 0,
        status = if (completed) AndroidDownloadStatus.Completed else AndroidDownloadStatus.Downloading,
        localReference = localReference,
        verified = completed,
        createdAtEpochMillis = 1,
        updatedAtEpochMillis = 2,
    )
}
