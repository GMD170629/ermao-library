package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFailure
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource

sealed interface PdfRangeProbeResult {
    data object Available : PdfRangeProbeResult
    data class Failure(
        val code: PdfReaderErrorCode,
        val recoverable: Boolean,
        val safetyFailure: ReaderSafetyFailure? = null,
    ) : PdfRangeProbeResult
}

sealed interface PdfRangeReadResult {
    data class Content(val range: PdfByteRange, val bytes: ByteArray) : PdfRangeReadResult {
        init {
            require(bytes.size.toLong() == range.endExclusive - range.begin)
        }
    }

    data class Failure(
        val code: PdfReaderErrorCode,
        val recoverable: Boolean,
        val safetyFailure: ReaderSafetyFailure? = null,
    ) : PdfRangeReadResult
}

/**
 * Result of servicing the byte ranges requested by the native PDF engine.
 *
 * The native engine may request a span that cannot be retained in the bounded
 * session cache. That is a routing decision, not a protocol or safety error:
 * the platform must materialize the verified original through Downloads and
 * install it as the current PDFium session's local byte source.
 */
sealed interface PdfRangeDrainResult {
    data object NoPendingRequest : PdfRangeDrainResult
    data object RangesAvailable : PdfRangeDrainResult
    data object CompleteOriginalRequired : PdfRangeDrainResult
}

interface PdfRangeServerPort {
    suspend fun probe(source: RemoteByteRangeReaderSource): PdfRangeProbeResult
    suspend fun read(source: RemoteByteRangeReaderSource, range: PdfByteRange): PdfRangeReadResult
}
