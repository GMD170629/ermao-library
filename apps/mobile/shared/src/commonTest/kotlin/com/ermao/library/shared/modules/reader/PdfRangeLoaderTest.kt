package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.PdfRangeFailure
import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class PdfRangeLoaderTest {
    private val namespace = ReaderSyncNamespace("server", "user", 1)
    private val source = RemoteByteRangeReaderSource("resource", "PDF", "book", "asset", namespace,
        "/api/assets/asset/file", 32L * 1024 * 1024)
    private val identity = PdfRangeCacheIdentity(namespace, "resource")

    @Test
    fun concurrentRequestsCoalesceAndChangingPageDropsPreviousBytes(): Unit = runBlocking {
        val server = RecordingServer()
        val loader = PdfRangeLoader(source, identity, PdfRangeMemory(), server)
        loader.activateUnit(0)
        (0..5).map { async { loader.awaitRange(1, 10) } }.awaitAll()
        assertEquals(listOf(PdfByteRange(0, PDF_RANGE_CHUNK_BYTES.toLong())), server.ranges)
        assertTrue(loader.isCached(1, 10))
        loader.activateUnit(1)
        assertFalse(loader.isCached(1, 10))
        loader.awaitRange(1, 10)
        assertEquals(2, server.ranges.size)
        loader.close()
        assertFalse(loader.isCached(1, 10))
    }

    @Test
    fun invalidOrExcessiveNativeHintsNeverReachTheServer(): Unit = runBlocking {
        for ((offset, length) in listOf(-1L to 1L, 0L to 9L * 1024 * 1024, Long.MAX_VALUE to 1L)) {
            val server = RecordingServer()
            val loader = PdfRangeLoader(source, identity, PdfRangeMemory(), server)
            try {
                loader.request(offset, length)
                assertFailsWith<PdfRangeFailure> { loader.drainRequested() }
                assertTrue(server.ranges.isEmpty())
            } finally { loader.close() }
        }
    }

    @Test
    fun closingCancelsInFlightTransferWithoutRetainingBytes(): Unit = runBlocking {
        val entered = CompletableDeferred<Unit>()
        val stopped = CompletableDeferred<Unit>()
        val server = object : PdfRangeServerPort {
            override suspend fun probe(source: RemoteByteRangeReaderSource) = PdfRangeProbeResult.Available
            override suspend fun read(source: RemoteByteRangeReaderSource, range: PdfByteRange): PdfRangeReadResult {
                entered.complete(Unit)
                try { awaitCancellation() } finally { stopped.complete(Unit) }
            }
        }
        val loader = PdfRangeLoader(source, identity, PdfRangeMemory(), server)
        val request = async { loader.awaitRange(0, 1024) }
        entered.await()
        loader.close()
        stopped.await()
        request.join()
        assertTrue(request.isCancelled)
        assertFalse(loader.isCached(0, 1))
    }

    private class RecordingServer : PdfRangeServerPort {
        val ranges = mutableListOf<PdfByteRange>()
        override suspend fun probe(source: RemoteByteRangeReaderSource) = PdfRangeProbeResult.Available
        override suspend fun read(source: RemoteByteRangeReaderSource, range: PdfByteRange): PdfRangeReadResult {
            ranges += range
            delay(1)
            return PdfRangeReadResult.Content(range, ByteArray((range.endExclusive - range.begin).toInt()))
        }
    }
}
