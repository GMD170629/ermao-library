package com.ermao.library.shared.modules.reader.domain

import kotlin.test.Test
import kotlin.test.assertEquals

class ReaderFailureMappingTest {
    @Test
    fun `recoverable transport failures remain network errors`() {
        assertEquals(
            ReaderErrorCode.NetworkUnavailable,
            readerErrorCodeForFailure("SERVER_FAILURE", recoverable = true),
        )
    }

    @Test
    fun `invalid publication MIME remains a corrupt source error`() {
        assertEquals(
            ReaderErrorCode.CorruptFile,
            readerErrorCodeForFailure("READER_PUBLICATION_ASSET_INVALID", recoverable = false),
        )
    }

    @Test
    fun `unsupported source format remains explicit`() {
        assertEquals(
            ReaderErrorCode.UnsupportedFormat,
            readerErrorCodeForFailure("READER_BOOTSTRAP_UNSUPPORTED", recoverable = false),
        )
    }

    @Test
    fun `missing resource is not mislabeled as a parse failure`() {
        assertEquals(
            ReaderErrorCode.ResourceMissing,
            readerErrorCodeForFailure("READER_PUBLICATION_ASSET_MISSING", recoverable = false),
        )
    }

    @Test
    fun `comic archive failures retain their actionable stable codes`() {
        val expected = mapOf(
            "ARCHIVE_ENCRYPTED" to ReaderErrorCode.ComicArchiveEncrypted,
            "ARCHIVE_PART_MISSING" to ReaderErrorCode.ComicArchivePartMissing,
            "ARCHIVE_FORMAT_SETUP_FAILED" to ReaderErrorCode.ComicArchiveFormatUnsupported,
            "ARCHIVE_OPEN_FAILED" to ReaderErrorCode.ComicArchiveOpenFailed,
            "ARCHIVE_HEADER_INVALID" to ReaderErrorCode.ComicArchiveCorrupt,
            "ARCHIVE_EXPANDED_LIMIT_EXCEEDED" to ReaderErrorCode.ComicOutOfMemoryRisk,
            "COMIC_PAGE_DECODE_FAILED" to ReaderErrorCode.ComicPageDecodeFailed,
        )

        expected.forEach { (failureCode, readerCode) ->
            assertEquals(readerCode, readerErrorCodeForFailure(failureCode, recoverable = false))
        }
    }
}
