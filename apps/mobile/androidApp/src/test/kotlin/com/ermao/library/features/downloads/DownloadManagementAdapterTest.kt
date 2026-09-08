package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.shared.modules.downloads.DownloadManagementAction
import com.ermao.library.shared.modules.downloads.DownloadManagementPolicy
import com.ermao.library.shared.modules.downloads.DownloadManagementStatus
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.junit.Test

class DownloadManagementAdapterTest {
    private val namespace = AndroidDownloadNamespace("server", "user", 3)

    @Test
    fun adapterProjectsStatusMatrixAndActions() {
        val cases = listOf(
            Case(null, active = false, available = true,
                status = DownloadManagementStatus.NotDownloaded,
                actions = setOf(DownloadManagementAction.Download)),
            Case(null, active = true, available = true,
                status = DownloadManagementStatus.Downloading,
                actions = setOf(DownloadManagementAction.Pause, DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.Queued, active = false, available = true,
                status = DownloadManagementStatus.Queued,
                actions = setOf(DownloadManagementAction.Pause, DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.Downloading, active = true, available = true,
                status = DownloadManagementStatus.Downloading,
                actions = setOf(DownloadManagementAction.Pause, DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.Paused, active = false, available = true,
                status = DownloadManagementStatus.Paused,
                actions = setOf(DownloadManagementAction.Resume, DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.FailedRetryable, active = false, available = true,
                status = DownloadManagementStatus.FailedRetryable,
                actions = setOf(DownloadManagementAction.Retry, DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.FailedTerminal, active = false, available = true,
                status = DownloadManagementStatus.FailedTerminal,
                actions = setOf(DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.Completed, active = false, available = true,
                verified = true,
                status = DownloadManagementStatus.Completed,
                actions = setOf(DownloadManagementAction.Open, DownloadManagementAction.Remove)),
            Case(AndroidDownloadStatus.Completed, active = false, available = false,
                verified = true,
                status = DownloadManagementStatus.Completed,
                actions = setOf(DownloadManagementAction.Open, DownloadManagementAction.Remove)),
        )

        cases.forEach { expected ->
            val actual = DownloadManagementPolicy.project(
                downloadManagementItem(
                    resourceId = "resource",
                    record = expected.recordStatus?.let { recordFor(it) },
                    active = expected.active,
                    available = expected.available,
                    verified = expected.verified,
                ),
            )

            assertEquals(expected.status, actual.status)
            assertEquals(expected.actions, actual.actions)
        }
    }

    @Test
    fun invalidCompletedRecordRemainsRetryableAndRetainsRemove() {
        val actual = DownloadManagementPolicy.project(
            downloadManagementItem(
                resourceId = "resource",
                record = recordFor(AndroidDownloadStatus.Completed).copy(
                    verified = false,
                    errorCode = "DOWNLOAD_LOCAL_FILE_INVALID",
                ),
                active = false,
                available = true,
            ),
        )

        assertEquals(DownloadManagementStatus.InvalidLocal, actual.status)
        assertEquals(
            setOf(DownloadManagementAction.Retry, DownloadManagementAction.Remove),
            actual.actions,
        )
    }

    @Test
    fun activeOwnershipOverridesStalePausedStatus() {
        val actual = DownloadManagementPolicy.project(
            downloadManagementItem(
                resourceId = "resource",
                record = recordFor(AndroidDownloadStatus.Paused),
                active = true,
                available = true,
            ),
        )

        assertEquals(DownloadManagementStatus.Downloading, actual.status)
        assertTrue(DownloadManagementAction.Pause in actual.actions)
        assertTrue(DownloadManagementAction.Resume !in actual.actions)
    }

    @Test
    fun unavailableResourceCannotDownloadResumeOrRetry() {
        val cases = listOf(
            null to DownloadManagementStatus.Unavailable,
            AndroidDownloadStatus.Paused to DownloadManagementStatus.Paused,
            AndroidDownloadStatus.FailedRetryable to DownloadManagementStatus.FailedRetryable,
            AndroidDownloadStatus.Completed to DownloadManagementStatus.InvalidLocal,
        )

        cases.forEach { (status, expectedStatus) ->
            val actual = DownloadManagementPolicy.project(
                downloadManagementItem(
                    resourceId = "resource",
                    record = status?.let {
                        recordFor(it).let { record ->
                            if (it == AndroidDownloadStatus.Completed) {
                                record.copy(verified = false, errorCode = "DOWNLOAD_LOCAL_FILE_INVALID")
                            } else record
                        }
                    },
                    active = false,
                    available = false,
                ),
            )

            assertEquals(expectedStatus, actual.status)
            assertTrue(DownloadManagementAction.Download !in actual.actions)
            assertTrue(DownloadManagementAction.Resume !in actual.actions)
            assertTrue(DownloadManagementAction.Retry !in actual.actions)
        }
    }

    private data class Case(
        val recordStatus: AndroidDownloadStatus?,
        val active: Boolean,
        val available: Boolean,
        val status: DownloadManagementStatus,
        val actions: Set<DownloadManagementAction>,
        val verified: Boolean = recordStatus == AndroidDownloadStatus.Completed,
    )

    private fun recordFor(status: AndroidDownloadStatus) = AndroidDownloadRecord(
        taskId = "task-$status",
        namespace = namespace,
        bookId = "book",
        bookTitle = "Book",
        author = "Author",
        coverUrl = "/api/books/book/cover",
        resourceId = "resource",
        resourceTitle = "Resource",
        format = "EPUB",
        readerType = "reflowable",
        assetId = "asset-$status",
        sourceApiPath = "/api/resources/resource/asset",
        sourceMimeType = "application/epub+zip",
        expectedBytes = 10,
        transferredBytes = if (status == AndroidDownloadStatus.Completed) 10 else 0,
        status = status,
        localReference = if (status == AndroidDownloadStatus.Completed) "artifacts/$status.bin" else null,
        verified = status == AndroidDownloadStatus.Completed,
        createdAtEpochMillis = 1,
        updatedAtEpochMillis = 2,
    )
}
