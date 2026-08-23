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
    fun missingEpubOpensServerReaderImmediately() {
        assertEquals(
            DownloadReaderEntryAction.OpenServerReader,
            downloadReaderEntryAction("reflowable", "EPUB", null) { false },
        )
    }

    @Test
    fun verifiedEpubOpensCurrentLocalArtifact() {
        assertEquals(
            DownloadReaderEntryAction.OpenLocalArtifact,
            downloadReaderEntryAction("reflowable", "EPUB", completedRecord()) { true },
        )
    }

    @Test
    fun missingLocalFileFallsBackToServerReader() {
        assertEquals(
            DownloadReaderEntryAction.OpenServerReader,
            downloadReaderEntryAction("reflowable", "EPUB", completedRecord()) { false },
        )
    }

    @Test
    fun mobiFamilyUsesTheNativeDownloadAndReaderFlow() {
        listOf("MOBI", "AZW", "AZW3", "PRC").forEach { format ->
            assertEquals(
                DownloadReaderEntryAction.OpenServerReader,
                downloadReaderEntryAction("reflowable", format, null) { false },
            )
        }
    }

    @Test
    fun txtUsesNativeReaderWhileUnsupportedReflowableFormatsStayOnStreamingValidation() {
        assertEquals(
            DownloadReaderEntryAction.OpenServerReader,
            downloadReaderEntryAction("reflowable", "TXT", null) { false },
        )
        assertEquals(
            DownloadReaderEntryAction.ValidateUnsupportedAccess,
            downloadReaderEntryAction("reflowable", "FB2", null) { false },
        )
    }

    private fun completedRecord() = AndroidDownloadRecord(
        taskId = "task",
        namespace = AndroidDownloadNamespace("server", "user", 2),
        bookId = "book",
        bookTitle = "Book",
        author = "Author",
        coverUrl = "/api/books/book/cover",
        resourceId = "resource",
        resourceTitle = "Resource",
        format = "EPUB",
        readerType = "reflowable",
        assetId = "asset",
        sourceApiPath = "/api/resources/resource/asset",
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
