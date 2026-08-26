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
    fun verifiedEpubOpensCurrentLocalArtifact() {
        assertEquals(
            DownloadReaderEntryAction.OpenLocalArtifact,
            downloadReaderEntryAction("reflowable", "EPUB", completedRecord()) { true },
        )
    }

    @Test
    fun everySupportedReflowableWithoutALocalArtifactOpensTheServerReader() {
        listOf("EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT", "FB2").forEach { format ->
            assertEquals(
                DownloadReaderEntryAction.OpenServerReader,
                downloadReaderEntryAction("reflowable", format, null) { false },
                format,
            )
            assertEquals(
                DownloadReaderEntryAction.OpenServerReader,
                downloadReaderEntryAction("reflowable", format, completedRecord(format)) { false },
                "invalid local $format",
            )
        }
    }

    @Test
    fun everySupportedComicWithoutALocalArtifactOpensTheServerReader() {
        listOf("CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR").forEach { format ->
            assertEquals(
                DownloadReaderEntryAction.OpenServerReader,
                downloadReaderEntryAction("comic", format, null) { false },
                format,
            )
        }
    }

    @Test
    fun legacyGenericKindleFormatIsNotAdvertisedAsReadable() {
        assertEquals(
            DownloadReaderEntryAction.ValidateUnsupportedAccess,
            downloadReaderEntryAction("reflowable", "KINDLE", null) { false },
        )
    }

    private fun completedRecord(format: String = "EPUB") = AndroidDownloadRecord(
        taskId = "task",
        namespace = AndroidDownloadNamespace("server", "user", 2),
        bookId = "book",
        bookTitle = "Book",
        author = "Author",
        coverUrl = "/api/books/book/cover",
        resourceId = "resource",
        resourceTitle = "Resource",
        format = format,
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
