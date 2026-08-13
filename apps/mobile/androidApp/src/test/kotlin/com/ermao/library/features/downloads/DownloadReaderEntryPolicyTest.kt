package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.DownloadReaderEntryAction
import com.ermao.library.features.downloads.model.downloadReaderEntryAction
import kotlin.test.assertEquals
import org.junit.Test

class DownloadReaderEntryPolicyTest {
    @Test
    fun missingEpubOpensPreparationImmediately() {
        assertEquals(
            DownloadReaderEntryAction.OpenPreparation,
            downloadReaderEntryAction("reflowable", "EPUB", null) { false },
        )
    }

    @Test
    fun verifiedEpubValidatesCurrentFingerprintWithoutPreparation() {
        assertEquals(
            DownloadReaderEntryAction.ValidateCurrentArtifact,
            downloadReaderEntryAction("reflowable", "EPUB", completedRecord()) { true },
        )
    }

    @Test
    fun missingLocalFileCannotBypassPreparation() {
        assertEquals(
            DownloadReaderEntryAction.OpenPreparation,
            downloadReaderEntryAction("reflowable", "EPUB", completedRecord()) { false },
        )
    }

    private fun completedRecord() = AndroidDownloadRecord(
        taskId = "task",
        namespace = AndroidDownloadNamespace("server", "user", 2),
        workId = "work",
        workTitle = "Book",
        author = "Author",
        coverUrl = "/api/works/work/cover",
        volumeId = "volume",
        volumeTitle = "Volume",
        format = "EPUB",
        readerType = "reflowable",
        contentFingerprint = "fingerprint",
        sourceApiPath = "/api/files/file",
        sourceMimeType = "application/epub+zip",
        expectedBytes = 8,
        transferredBytes = 8,
        status = AndroidDownloadStatus.Completed,
        localReference = "artifact.epub",
        verified = true,
        createdAtEpochMillis = 1,
        updatedAtEpochMillis = 2,
    )
}
