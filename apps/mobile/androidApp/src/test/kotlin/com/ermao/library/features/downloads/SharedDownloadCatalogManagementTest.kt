package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadStorageException
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.infrastructure.SharedDownloadCatalogAdapter
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.DownloadTaskStatus
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlinx.coroutines.test.runTest
import org.junit.Test

class SharedDownloadCatalogManagementTest {
    private val namespace = DownloadNamespace("server", "user", 1)
    private val androidNamespace = AndroidDownloadNamespace("server", "user", 1)

    @Test
    fun unverifiedCompletedRecordProjectsInvalidTaskWithoutLosingTheRecord() = runTest {
        val root = Files.createTempDirectory("management-invalid").toFile()
        try {
            val catalog = AndroidDownloadCatalog(root)
            val record = record().copy(status = AndroidDownloadStatus.Completed, transferredBytes = 4)
            catalog.upsert(record)
            val adapter = SharedDownloadCatalogAdapter(catalog, AtomicDownloadFileSink(root))
            val task = adapter.listTasks(namespace).single()
            assertEquals(DownloadTaskStatus.FailedTerminal, task.status)
            assertEquals("DOWNLOAD_LOCAL_FILE_INVALID", task.failureCode)
            assertNull(task.artifact)
            assertNotNull(catalog.record(androidNamespace, record.taskId))
        } finally { root.deleteRecursively() }
    }

    @Test
    fun removalDiscardsResumableBytesBeforeDroppingTheTask() = runTest {
        val root = Files.createTempDirectory("management-remove").toFile()
        try {
            val catalog = AndroidDownloadCatalog(root)
            val sink = AtomicDownloadFileSink(root)
            val record = record()
            val request = DownloadSinkRequest(namespace, record.taskId, record.resourceId, record.assetId, 4, 0)
            val session = sink.begin(request)
            session.write(byteArrayOf(1, 2))
            session.pause()
            assertEquals(2L, sink.inspect(request).partialBytes)
            catalog.upsert(record)
            SharedDownloadCatalogAdapter(catalog, sink).deleteTask(namespace, record.taskId)
            assertNull(catalog.record(androidNamespace, record.taskId))
            assertEquals(0L, sink.inspect(request).partialBytes)
            assertFalse(root.walkTopDown().any { it.isFile && it.name.endsWith(".part") })
        } finally { root.deleteRecursively() }
    }

    @Test
    fun deletingOneTaskPreservesAnotherVersionOfTheSameResource() = runTest {
        val root = Files.createTempDirectory("management-version").toFile()
        try {
            val catalog = AndroidDownloadCatalog(root)
            val old = record().copy(localReference = "old.bin")
            val other = record().copy(taskId = "other-task", assetId = "other-asset", localReference = "other.bin")
            root.resolve("old.bin").writeText("old")
            root.resolve("other.bin").writeText("keep")
            catalog.upsert(old)
            catalog.upsert(other)
            SharedDownloadCatalogAdapter(catalog, AtomicDownloadFileSink(root)).deleteTask(namespace, old.taskId)
            assertNull(catalog.record(androidNamespace, old.taskId))
            assertEquals(other, catalog.record(androidNamespace, other.taskId))
            assertEquals("keep", root.resolve("other.bin").readText())
        } finally { root.deleteRecursively() }
    }

    @Test
    fun removalFailureKeepsTaskAndDoesNotTouchFilesOutsideDownloadRoot() = runTest {
        val parent = Files.createTempDirectory("management-remove-failure").toFile()
        try {
            val root = parent.resolve("downloads").apply { mkdirs() }
            val unrelated = parent.resolve("reader-history").apply { writeText("preserved") }
            val catalog = AndroidDownloadCatalog(root)
            val record = record().copy(localReference = "../reader-history")
            catalog.upsert(record)
            val adapter = SharedDownloadCatalogAdapter(catalog, AtomicDownloadFileSink(root))
            assertFailsWith<AndroidDownloadStorageException> { adapter.deleteTask(namespace, record.taskId) }
            assertNotNull(catalog.record(androidNamespace, record.taskId))
            assertEquals("preserved", unrelated.readText())
        } finally { parent.deleteRecursively() }
    }

    private fun record() = AndroidDownloadRecord(
        taskId = "task", namespace = androidNamespace, bookId = "book", bookTitle = "Book",
        author = "Author", coverUrl = "", resourceId = "resource", resourceTitle = "Resource",
        format = "EPUB", readerType = "reflowable", assetId = "asset", sourceApiPath = "/api/assets/asset",
        sourceMimeType = "application/epub+zip", expectedBytes = 4, status = AndroidDownloadStatus.Paused,
        createdAtEpochMillis = 1, updatedAtEpochMillis = 2,
    )
}
