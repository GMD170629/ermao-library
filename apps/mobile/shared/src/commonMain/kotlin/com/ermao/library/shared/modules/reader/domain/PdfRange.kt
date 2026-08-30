package com.ermao.library.shared.modules.reader.domain

val PDF_RANGE_CHUNK_BYTES: Int =
    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_RANGE_CHUNK_BYTES).toBoundedInt()
val PDF_RANGE_MAX_REQUEST_BYTES: Int =
    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_RANGE_REQUEST_MAX_BYTES).toBoundedInt()
val PDF_RANGE_MAX_CONCURRENT_REQUESTS: Int =
    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_RANGE_MAX_CONCURRENT).toBoundedInt()
val PDF_RANGE_MEMORY_CACHE_BYTES: Int =
    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_RANGE_MEMORY_CACHE_MAX_BYTES).toBoundedInt()

typealias PdfReaderErrorCode = ReaderErrorCode

data class PdfRangeCacheIdentity(
    val namespace: ReaderSyncNamespace,
    val resourceId: String,
) {
    init { require(resourceId.isNotBlank()) }

    val stableKey: String
        get() = lengthPrefixed(namespace.stableKey, resourceId)
}

data class PdfByteRange(val begin: Long, val endExclusive: Long) {
    init {
        require(begin >= 0 && endExclusive > begin)
        require(endExclusive - begin <= PDF_RANGE_MAX_REQUEST_BYTES)
    }
}

fun planPdfByteRanges(begin: Long, endExclusive: Long, length: Long): List<PdfByteRange> {
    require(begin >= 0 && endExclusive > begin && endExclusive <= length)
    val alignedBegin = begin / PDF_RANGE_CHUNK_BYTES * PDF_RANGE_CHUNK_BYTES
    val remainder = endExclusive % PDF_RANGE_CHUNK_BYTES
    val padding = if (remainder == 0L) 0L else minOf(length - endExclusive, PDF_RANGE_CHUNK_BYTES - remainder)
    val alignedEnd = endExclusive + padding
    return buildList {
        var cursor = alignedBegin
        while (cursor < alignedEnd) {
            val end = minOf(alignedEnd, cursor + PDF_RANGE_MAX_REQUEST_BYTES)
            add(PdfByteRange(cursor, end))
            cursor = end
        }
    }
}

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value -> append(value.length).append(':').append(value) }
}

private fun Long.toBoundedInt(): Int {
    require(this in 1..Int.MAX_VALUE.toLong())
    return toInt()
}
