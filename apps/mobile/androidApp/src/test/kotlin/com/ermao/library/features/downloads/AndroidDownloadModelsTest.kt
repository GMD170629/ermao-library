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
    fun searchReturnsOnlyCompletedVerifiedExistingDownloadsGroupedByWork() {
        val records = listOf(
            record("task-1", "work-1", "三体", "刘慈欣", "第一卷", "/files/one", completed = true),
            record("task-2", "work-1", "三体", "刘慈欣", "第二卷", "/files/two", completed = true),
            record("task-3", "work-2", "流浪地球", "刘慈欣", "上册", "/files/missing", completed = true),
            record("task-4", "work-3", "Incomplete", "Author", "Volume", null, completed = false),
        )

        val result = groupReadableDownloads(records, "刘慈欣") { it.localReference != "/files/missing" }

        assertEquals(1, result.size)
        assertEquals("work-1", result.single().workId)
        assertEquals(listOf("第一卷", "第二卷"), result.single().volumes.map(AndroidDownloadRecord::volumeTitle))
    }

    @Test
    fun completedWorkPreservesVersionThenVolumeHierarchy() {
        val records = listOf(
            record("task-2", "work-1", "Book", "Author", "Volume 2", "two.bin", completed = true).copy(
                versionId = "version-implicit",
                versionSourceKey = "__implicit__",
                volumeSortOrder = 2,
            ),
            record("task-1", "work-1", "Book", "Author", "Volume 1", "one.bin", completed = true).copy(
                versionId = "version-implicit",
                versionSourceKey = "__implicit__",
                volumeSortOrder = 1,
            ),
            record("task-3", "work-1", "Book", "Author", "Kindle", "kindle.bin", completed = true).copy(
                versionId = "version-kindle",
                versionSourceKey = "kindle",
                versionSourceName = "Kindle",
            ),
        )

        val work = groupReadableDownloads(records, "") { true }.single()

        assertEquals(listOf("version-implicit", "version-kindle"), work.versions.map { it.versionId })
        assertEquals(listOf("Volume 1", "Volume 2"), work.versions.first().volumes.map { it.volumeTitle })
    }

    @Test
    fun catalogRecordCannotClaimCompletedWithoutVerifiedLocalReference() {
        assertFailsWith<IllegalArgumentException> {
            record("task", "work", "Title", "Author", "Volume", null, completed = true)
        }
    }

    private fun record(
        taskId: String,
        workId: String,
        title: String,
        author: String,
        volume: String,
        localReference: String?,
        completed: Boolean,
    ) = AndroidDownloadRecord(
        taskId = taskId,
        namespace = namespace,
        workId = workId,
        workTitle = title,
        author = author,
        coverUrl = "/api/works/$workId/cover",
        volumeId = "$taskId-volume",
        volumeTitle = volume,
        format = "EPUB",
        readerType = "reflowable",
        versionId = "version-$taskId",
        versionSourceKey = "__implicit__",
        sourceApiPath = "/api/volumes/$taskId-volume/file",
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
