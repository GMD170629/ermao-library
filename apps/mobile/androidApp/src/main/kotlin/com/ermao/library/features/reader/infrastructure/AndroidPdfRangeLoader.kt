package com.ermao.library.features.reader.infrastructure

import com.ermao.library.pdfium.ShukuPdfiumNative
import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MAX_CONCURRENT_REQUESTS
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MAX_REQUEST_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import java.nio.ByteBuffer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit

internal class AndroidPdfRangeFailure(
    val code: PdfReaderErrorCode,
    val recoverable: Boolean,
) : Exception(code.wireValue)

/** Owns one PDF session's bounded acquisition queue; PDFium callbacks only enqueue work. */
internal class AndroidPdfRangeLoader(
    private val scope: CoroutineScope,
    private val source: RemoteByteRangeReaderSource,
    private val identity: PdfRangeCacheIdentity,
    private val cache: AndroidPdfRangeCache,
    private val server: PdfRangeServerPort,
) {
    private val semaphore = Semaphore(PDF_RANGE_MAX_CONCURRENT_REQUESTS)
    private val jobsMutex = Mutex()
    private val jobs = mutableMapOf<PdfByteRange, Deferred<Unit>>()
    private val pendingLock = Any()
    private val pending = mutableSetOf<PdfByteRange>()

    suspend fun probe() {
        when (val result = server.probe(source)) {
            PdfRangeProbeResult.Available -> Unit
            is PdfRangeProbeResult.Failure -> throw AndroidPdfRangeFailure(result.code, result.recoverable)
        }
    }

    fun request(offset: Long, size: Long) {
        if (size <= 0 || offset < 0 || offset > source.expectedSizeBytes - size) return
        synchronized(pendingLock) {
            pending += missingRanges(offset, offset + size)
        }
    }

    suspend fun awaitRange(offset: Long, size: Long) {
        require(size > 0 && offset >= 0 && offset <= source.expectedSizeBytes - size)
        coroutineScope {
            missingRanges(offset, offset + size).map { range -> async { acquire(range) } }.awaitAll()
        }
    }

    suspend fun drainRequested(): Boolean {
        val requested = synchronized(pendingLock) {
            pending.toList().also { pending.clear() }
        }
        if (requested.isEmpty()) return false
        coroutineScope { requested.map { range -> async { acquire(range) } }.awaitAll() }
        return true
    }

    fun isCached(offset: Long, size: Int): Boolean =
        size > 0 && offset >= 0 && offset <= source.expectedSizeBytes - size &&
            cache.isCached(identity, offset, size)

    fun readCached(offset: Long, destination: ByteBuffer): Boolean {
        val count = destination.remaining()
        if (!isCached(offset, count)) return false
        val bytes = cache.readCached(identity, offset, count) ?: return false
        destination.put(bytes)
        return true
    }

    private suspend fun acquire(range: PdfByteRange) {
        if (isRangeCached(range)) return
        val (job, owner) = jobsMutex.withLock {
            jobs[range]?.let { return@withLock it to false }
            scope.async {
                semaphore.withPermit {
                    if (isRangeCached(range)) return@withPermit
                    when (val result = server.read(source, range)) {
                        is PdfRangeReadResult.Content -> cache.writeAlignedRange(
                            identity,
                            result.range.begin,
                            result.bytes,
                            protectedChunkIndices = range.chunkIndices(),
                        )
                        is PdfRangeReadResult.Failure -> throw AndroidPdfRangeFailure(
                            result.code,
                            result.recoverable,
                        )
                    }
                }
            }.also { jobs[range] = it } to true
        }
        try {
            job.await()
        } finally {
            if (owner) jobsMutex.withLock { jobs.remove(range, job) }
        }
    }

    private fun isRangeCached(range: PdfByteRange): Boolean {
        val size = (range.endExclusive - range.begin).toInt()
        return cache.isCached(identity, range.begin, size)
    }

    private fun missingRanges(begin: Long, endExclusive: Long): List<PdfByteRange> {
        val alignedBegin = begin / PDF_RANGE_CHUNK_BYTES * PDF_RANGE_CHUNK_BYTES
        val remainder = endExclusive % PDF_RANGE_CHUNK_BYTES
        val padding = if (remainder == 0L) {
            0L
        } else {
            minOf(source.expectedSizeBytes - endExclusive, PDF_RANGE_CHUNK_BYTES - remainder)
        }
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

    private fun PdfByteRange.chunkIndices(): Set<Long> =
        ((begin / PDF_RANGE_CHUNK_BYTES)..((endExclusive - 1) / PDF_RANGE_CHUNK_BYTES)).toSet()
}

internal class AndroidPdfiumByteSource(private val loader: AndroidPdfRangeLoader) :
    ShukuPdfiumNative.ByteSource {
    override fun isRangeCached(offset: Long, size: Long): Boolean =
        size in 1..Int.MAX_VALUE && loader.isCached(offset, size.toInt())

    override fun readCachedBlock(offset: Long, destination: ByteBuffer): Boolean =
        loader.readCached(offset, destination)

    override fun requestRange(offset: Long, size: Long) {
        loader.request(offset, size)
    }
}
