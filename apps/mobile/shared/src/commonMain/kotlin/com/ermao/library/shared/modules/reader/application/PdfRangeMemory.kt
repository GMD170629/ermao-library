package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MAX_REQUEST_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MEMORY_CACHE_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

/** Session-only bytes shared by native PDF renderers. No filesystem representation exists. */
class PdfRangeMemory {
    private data class State(
        val identity: PdfRangeCacheIdentity? = null,
        val unit: Int? = null,
        val chunks: Map<Long, ByteArray> = emptyMap(),
    )
    private val state = MutableStateFlow(State())

    fun isCached(identity: PdfRangeCacheIdentity, offset: Long, count: Int): Boolean =
        slices(state.value, identity, offset, count) != null

    fun readCached(identity: PdfRangeCacheIdentity, offset: Long, count: Int): ByteArray? {
        val current = state.value
        val spans = slices(current, identity, offset, count) ?: return null
        val result = ByteArray(count)
        var written = 0
        for ((index, start, size) in spans) {
            val bytes = current.chunks[index] ?: return null
            bytes.copyInto(result, written, start, start + size)
            written += size
        }
        state.update { latest ->
            if (latest.identity != identity) latest else latest.copy(chunks = latest.chunks.toMutableMap().apply {
                for (span in spans) remove(span.index)?.let { put(span.index, it) }
            })
        }
        return result
    }

    @Throws(IllegalArgumentException::class)
    fun writeAlignedRange(identity: PdfRangeCacheIdentity, begin: Long, bytes: ByteArray) {
        require(begin >= 0 && begin % PDF_RANGE_CHUNK_BYTES == 0L)
        require(bytes.size in 1..PDF_RANGE_MAX_REQUEST_BYTES)
        state.update { current ->
            val chunks = if (current.identity == identity) current.chunks.toMutableMap() else linkedMapOf()
            var consumed = 0
            while (consumed < bytes.size) {
                val count = minOf(PDF_RANGE_CHUNK_BYTES, bytes.size - consumed)
                val index = (begin + consumed) / PDF_RANGE_CHUNK_BYTES
                chunks.remove(index)
                chunks[index] = bytes.copyOfRange(consumed, consumed + count)
                consumed += count
            }
            var size = chunks.values.sumOf { it.size }
            while (size > PDF_RANGE_MEMORY_CACHE_BYTES) {
                size -= requireNotNull(chunks.remove(chunks.keys.first())).size
            }
            State(identity, current.unit, chunks)
        }
    }

    fun activateUnit(pageIndex: Int) {
        state.update { if (it.unit == pageIndex) it else it.copy(unit = pageIndex, chunks = emptyMap()) }
    }

    fun activateNamespace(namespace: ReaderSyncNamespace) {
        state.update { if (it.identity?.namespace == namespace) it else State() }
    }

    fun clear() { state.value = State() }

    private data class Slice(val index: Long, val start: Int, val size: Int)

    private fun slices(current: State, identity: PdfRangeCacheIdentity, offset: Long, count: Int): List<Slice>? {
        if (current.identity != identity || offset < 0 || count <= 0 ||
            count > PDF_RANGE_MEMORY_CACHE_BYTES || offset > Long.MAX_VALUE - count) return null
        val spans = mutableListOf<Slice>()
        var cursor = offset
        var remaining = count
        while (remaining > 0) {
            val index = cursor / PDF_RANGE_CHUNK_BYTES
            val start = (cursor % PDF_RANGE_CHUNK_BYTES).toInt()
            val chunk = current.chunks[index] ?: return null
            val size = minOf(remaining, chunk.size - start)
            if (size <= 0) return null
            spans += Slice(index, start, size)
            cursor += size
            remaining -= size
        }
        return spans
    }
}
