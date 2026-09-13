package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.groupDownloads
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import org.junit.Test

class AndroidDownloadModelsTest {
    private val namespace = AndroidDownloadNamespace("server", "user", 3)

    @Test
    fun libraryIncludesEveryStateWithoutChangingReaderEligibility() {
        val done = record("done", "book", "三体", "刘慈欣", "第一卷", "/files/one", true)
        val running = record("running", "book", "三体", "刘慈欣", "第二卷", null, false)
        val failed = record("failed", "failed-book", "Failed book", "Author", "第三卷", null, false)
            .copy(status = AndroidDownloadStatus.FailedRetryable)
        val invalid = done.copy(taskId = "invalid", resourceId = "invalid", verified = false)
        val all = listOf(done, running, failed, invalid)
        val books = groupDownloads(all, "")
        assertEquals(2, books.size)
        assertEquals(4, books.sumOf { it.artifacts.size })
        assertEquals(listOf("failed-book"), groupDownloads(all, "第三卷").map { it.bookId })
        assertEquals(listOf("book"), groupDownloads(all, " 刘慈欣 ").map { it.bookId })
        assertEquals(1, books.flatMap { it.artifacts }.count { it.isReadable })
        assertEquals(2, groupDownloads(all.map { if (it == running) done.copy(taskId = running.taskId, resourceId = running.resourceId) else it }, "").size)
    }

    @Test
    fun searchMatchesAuthorAndPreservesBooksWithMissingLocalFiles() {
        val records = listOf(
            record("task-1", "book-1", "三体", "刘慈欣", "第一卷", "/files/one", completed = true),
            record("task-2", "book-1", "三体", "刘慈欣", "第二卷", "/files/two", completed = true),
            record("task-3", "book-2", "流浪地球", "刘慈欣", "上册", "/files/missing", completed = true),
            record("task-4", "book-3", "Incomplete", "Author", "Resource", null, completed = false),
        )

        val result = groupDownloads(records, "刘慈欣")

        assertEquals(setOf("book-1", "book-2"), result.map { it.bookId }.toSet())
        assertEquals(listOf("第一卷", "第二卷"), result.first { it.bookId == "book-1" }.resources.map { it.title })
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

        val book = groupDownloads(records, "").single()

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

        val book = groupDownloads(listOf(moved), "").single()

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
