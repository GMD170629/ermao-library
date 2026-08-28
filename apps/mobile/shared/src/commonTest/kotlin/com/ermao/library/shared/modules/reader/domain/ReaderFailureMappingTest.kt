package com.ermao.library.shared.modules.reader.domain

import kotlin.test.Test
import kotlin.test.assertEquals

class ReaderFailureMappingTest {
    @Test
    fun `server failures are distinct from unavailable network`() {
        assertEquals(
            ReaderErrorCode.ServerUnavailable,
            readerErrorCodeForFailure("SERVER_FAILURE", recoverable = true),
        )
    }

    @Test
    fun `known online causes retain their precise error categories`() {
        val expected = mapOf(
            "UNAUTHORIZED" to ReaderErrorCode.Unauthorized,
            "FORBIDDEN" to ReaderErrorCode.Forbidden,
            "PUBLICATION_NOT_FOUND" to ReaderErrorCode.PublicationUnavailable,
            "PUBLICATION_RESOURCE_NOT_FOUND" to ReaderErrorCode.PublicationUnavailable,
            "NOT_FOUND" to ReaderErrorCode.PublicationUnavailable,
            "PUBLICATION_CORRUPT" to ReaderErrorCode.ParseFailed,
            "PUBLICATION_UNSUPPORTED" to ReaderErrorCode.UnsupportedFormat,
            "PUBLICATION_TXT_NUL_CHARACTER" to ReaderErrorCode.TxtNulCharacter,
            "PUBLICATION_TXT_ENCODING_UNSUPPORTED" to ReaderErrorCode.TxtEncodingUnsupported,
            "PUBLICATION_TXT_EMPTY" to ReaderErrorCode.TxtEmpty,
            "BINARY_CONTENT_TYPE_MISSING" to ReaderErrorCode.InvalidResponse,
            "BINARY_LENGTH_MISMATCH" to ReaderErrorCode.InvalidResponse,
            "REDIRECT_LOCATION_MISSING" to ReaderErrorCode.InvalidResponse,
            "PUBLICATION_MANIFEST_INVALID" to ReaderErrorCode.InvalidResponse,
            "PUBLICATION_POSITIONS_INVALID" to ReaderErrorCode.InvalidResponse,
            "REQUEST_TIMEOUT" to ReaderErrorCode.RequestTimeout,
            "TLS_FAILURE" to ReaderErrorCode.TlsFailure,
            "RATE_LIMITED" to ReaderErrorCode.RateLimited,
            "NETWORK_UNAVAILABLE" to ReaderErrorCode.NetworkUnavailable,
            "UNAVAILABLE" to ReaderErrorCode.ServerUnavailable,
            "PUBLICATION_ONLINE_LIMIT" to ReaderErrorCode.OnlineLimit,
            "PUBLICATION_RESOURCE_TOO_LARGE" to ReaderErrorCode.OnlineLimit,
            "PAYLOAD_TOO_LARGE" to ReaderErrorCode.OnlineLimit,
        )
        expected.forEach { (wireCode, readerCode) ->
            for (recoverable in listOf(false, true)) {
                assertEquals(readerCode, readerErrorCodeForFailure(wireCode, recoverable), wireCode)
            }
        }
    }

    @Test
    fun `unknown words do not manufacture a cause even when retryable`() {
        for (code in listOf("UNKNOWN_MISSING", "SOMETHING_NOT_FOUND", "UNEXPECTED_UNSUPPORTED", "UNRECOGNIZED_CORRUPT", "MYSTERY_FAILURE", "TRANSPORT_FAILURE")) {
            for (recoverable in listOf(false, true)) {
                assertEquals(ReaderErrorCode.ReaderEngineError, readerErrorCodeForFailure(code, recoverable), code)
            }
        }
    }

    @Test
    fun `all canonical reader codes round trip without substring guesses`() {
        ReaderErrorCode.entries.forEach { code ->
            assertEquals(code, readerErrorCodeForFailure(code.wireValue, recoverable = false))
        }
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
