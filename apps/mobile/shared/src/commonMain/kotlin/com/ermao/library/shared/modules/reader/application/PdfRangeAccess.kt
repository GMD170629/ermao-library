package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource

sealed interface PdfRangeProbeResult {
    data object Available : PdfRangeProbeResult
    data class Failure(val code: PdfReaderErrorCode, val recoverable: Boolean) : PdfRangeProbeResult
}

sealed interface PdfRangeReadResult {
    data class Content(val range: PdfByteRange, val bytes: ByteArray) : PdfRangeReadResult {
        init {
            require(bytes.size.toLong() == range.endExclusive - range.begin)
        }
    }

    data class Failure(val code: PdfReaderErrorCode, val recoverable: Boolean) : PdfRangeReadResult
}

interface PdfRangeServerPort {
    suspend fun probe(source: RemoteByteRangeReaderSource): PdfRangeProbeResult
    suspend fun read(source: RemoteByteRangeReaderSource, range: PdfByteRange): PdfRangeReadResult
}
