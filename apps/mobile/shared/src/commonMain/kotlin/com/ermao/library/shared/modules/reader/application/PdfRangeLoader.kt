package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MAX_REQUEST_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MEMORY_CACHE_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFailure
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class PdfRangeFailure(
    val code: PdfReaderErrorCode,
    val recoverable: Boolean,
    val safetyFailure: ReaderSafetyFailure? = null,
) : Exception(code.wireValue)

/** Both native engines share acquisition, coalescing, bounds, cancellation and session memory. */
class PdfRangeLoader(
    private val source: RemoteByteRangeReaderSource,
    private val identity: PdfRangeCacheIdentity,
    private val cache: PdfRangeMemory,
    private val server: PdfRangeServerPort,
) {
    private val cacheEpoch = cache.currentEpoch()
    private data class EngineRange(val begin: Long, val endExclusive: Long)
    private data class Pending(
        val unit: Int? = null,
        val generation: Long = 0,
        val ranges: Set<PdfByteRange> = emptySet(),
        val engineCoverage: List<EngineRange> = emptyList(),
        val materializationRequired: Boolean = false,
        val invalid: Boolean = false,
        val closed: Boolean = false,
    )
    private val pending = MutableStateFlow(Pending())
    private val active = MutableStateFlow<Set<Job>>(emptySet())
    private val acquisition = Mutex()

    @Throws(Exception::class)
    suspend fun probe() = owned {
        when (val result = server.probe(source)) {
            PdfRangeProbeResult.Available -> Unit
            is PdfRangeProbeResult.Failure ->
                throw PdfRangeFailure(result.code, result.recoverable, result.safetyFailure)
        }
    }

    fun request(offset: Long, size: Long) {
        if (!isValidEngineRange(offset, size)) {
            pending.update { if (it.closed) it else it.copy(invalid = true) }
            return
        }
        val endExclusive = offset + size
        val requiresCompleteOriginalBySpan =
            size > PDF_RANGE_MEMORY_CACHE_BYTES ||
                (offset == 0L && size == source.expectedSizeBytes)
        val ranges = if (requiresCompleteOriginalBySpan) {
            emptyList()
        } else {
            missingRanges(offset, endExclusive)
        }
        pending.update {
            if (it.closed || it.materializationRequired) it else {
                val coverage = mergeEngineRanges(it.engineCoverage + EngineRange(offset, endExclusive))
                val requiresCompleteOriginal =
                    requiresCompleteOriginalBySpan ||
                        coversWholeFile(coverage) ||
                        unionLength(ranges + it.ranges) > PDF_RANGE_MEMORY_CACHE_BYTES
                if (requiresCompleteOriginal) {
                    it.copy(
                        engineCoverage = coverage,
                        ranges = emptySet(),
                        materializationRequired = true,
                    )
                } else {
                    it.copy(engineCoverage = coverage, ranges = it.ranges + ranges)
                }
            }
        }
    }

    @Throws(Exception::class)
    suspend fun awaitRange(offset: Long, size: Long) = owned {
        require(isValidEngineRange(offset, size) && size <= PDF_RANGE_MEMORY_CACHE_BYTES)
        for (range in missingRanges(offset, offset + size)) acquire(range)
    }

    @Throws(Exception::class)
    suspend fun drainRequested(): PdfRangeDrainResult = owned {
        var requested: Pending
        do {
            requested = pending.value
        } while (!pending.compareAndSet(requested, requested.copy(ranges = emptySet())))
        if (requested.invalid) throw pdfRangePolicyFailure()
        if (requested.materializationRequired) return@owned PdfRangeDrainResult.CompleteOriginalRequired
        if (requested.ranges.isEmpty()) return@owned PdfRangeDrainResult.NoPendingRequest
        for (range in requested.ranges) acquire(range)
        if (pending.value.materializationRequired) {
            PdfRangeDrainResult.CompleteOriginalRequired
        } else {
            PdfRangeDrainResult.RangesAvailable
        }
    }

    fun activateUnit(pageIndex: Int) {
        require(pageIndex >= 0)
        val previous = pending.value
        if (previous.unit == pageIndex || previous.closed) return
        pending.update { it.copy(unit = pageIndex, generation = it.generation + 1, ranges = emptySet()) }
        active.value.forEach { it.cancel() }
        cache.activateUnit(pageIndex)
    }
    fun isCached(offset: Long, size: Int): Boolean = cache.isCached(identity, offset, size)
    fun readCached(offset: Long, count: Int): ByteArray? = cache.readCached(identity, offset, count)
    fun close() {
        pending.value = Pending(closed = true)
        active.value.forEach { it.cancel() }
        cache.clear()
    }

    private suspend fun <T> owned(action: suspend () -> T): T = coroutineScope {
        val job = coroutineContext.job
        active.update { it + job }
        try {
            check(!pending.value.closed) { "PDF session is closed" }
            action()
        } finally { active.update { it - job } }
    }

    private suspend fun acquire(range: PdfByteRange) = acquisition.withLock {
        if (cache.isCached(identity, range.begin, (range.endExclusive - range.begin).toInt())) return@withLock
        val generation = pending.value.generation
        when (val result = server.read(source, range)) {
            is PdfRangeReadResult.Content -> {
                coroutineContext.ensureActive()
                if (pending.value.closed ||
                    pending.value.generation != generation ||
                    pending.value.materializationRequired
                ) return@withLock
                if (result.range != range || result.bytes.size.toLong() != range.endExclusive - range.begin) {
                    throw pdfRangePolicyFailure()
                }
                cache.writeAlignedRange(identity, range.begin, result.bytes, expectedEpoch = cacheEpoch)
            }
            is PdfRangeReadResult.Failure ->
                throw PdfRangeFailure(result.code, result.recoverable, result.safetyFailure)
        }
    }

    private fun isValidEngineRange(offset: Long, size: Long): Boolean =
        source.expectedSizeBytes > 0 &&
            offset >= 0 &&
            size > 0 &&
            offset <= source.expectedSizeBytes &&
            size <= source.expectedSizeBytes - offset

    private fun coversWholeFile(ranges: List<EngineRange>): Boolean =
        ranges.firstOrNull()?.begin == 0L &&
            ranges.firstOrNull()?.endExclusive == source.expectedSizeBytes

    private fun mergeEngineRanges(ranges: List<EngineRange>): List<EngineRange> {
        if (ranges.isEmpty()) return emptyList()
        val merged = mutableListOf<EngineRange>()
        for (range in ranges.sortedWith(compareBy(EngineRange::begin, EngineRange::endExclusive))) {
            val previous = merged.lastOrNull()
            if (previous == null || range.begin > previous.endExclusive) {
                merged += range
            } else if (range.endExclusive > previous.endExclusive) {
                merged[merged.lastIndex] = previous.copy(endExclusive = range.endExclusive)
            }
        }
        return merged
    }

    private fun unionLength(ranges: Collection<PdfByteRange>): Long {
        var total = 0L
        for (range in mergeTransportRanges(ranges)) {
            val length = range.endExclusive - range.begin
            total = if (Long.MAX_VALUE - total < length) Long.MAX_VALUE else total + length
        }
        return total
    }

    private fun mergeTransportRanges(ranges: Collection<PdfByteRange>): List<PdfByteRange> {
        if (ranges.isEmpty()) return emptyList()
        val merged = mutableListOf<PdfByteRange>()
        for (range in ranges.sortedWith(compareBy(PdfByteRange::begin, PdfByteRange::endExclusive))) {
            val previous = merged.lastOrNull()
            if (previous == null || range.begin > previous.endExclusive) {
                merged += range
            } else if (range.endExclusive > previous.endExclusive) {
                merged[merged.lastIndex] = PdfByteRange(previous.begin, range.endExclusive)
            }
        }
        return merged
    }

    private fun missingRanges(begin: Long, endExclusive: Long): List<PdfByteRange> {
        val alignedBegin = begin / PDF_RANGE_CHUNK_BYTES * PDF_RANGE_CHUNK_BYTES
        val remainder = endExclusive % PDF_RANGE_CHUNK_BYTES
        val padding = if (remainder == 0L) 0L else minOf(source.expectedSizeBytes - endExclusive, PDF_RANGE_CHUNK_BYTES - remainder)
        val alignedEnd = endExclusive + padding
        val result = mutableListOf<PdfByteRange>()
        var groupBegin: Long? = null
        var cursor = alignedBegin
        while (cursor < alignedEnd) {
            val chunkEnd = minOf(alignedEnd, cursor + PDF_RANGE_CHUNK_BYTES)
            val cached = cache.isCached(identity, cursor, (chunkEnd - cursor).toInt())
            if (!cached && groupBegin == null) groupBegin = cursor
            val groupIsFull = groupBegin != null && chunkEnd - groupBegin >= PDF_RANGE_MAX_REQUEST_BYTES
            if ((cached || groupIsFull) && groupBegin != null) {
                val groupEnd = if (cached) cursor else chunkEnd
                if (groupEnd > groupBegin) result += PdfByteRange(groupBegin, groupEnd)
                groupBegin = null
            }
            cursor = chunkEnd
        }
        groupBegin?.let { result += PdfByteRange(it, alignedEnd) }
        return result
    }
}

private fun pdfRangePolicyFailure(): PdfRangeFailure = PdfRangeFailure(
    code = PdfReaderErrorCode.RangeInvalid,
    recoverable = false,
    safetyFailure = ReaderSafetyFacade().failureFor(ReaderSafetyRuleId.PDF_RANGE_PROTOCOL),
)
