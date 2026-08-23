package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.PdfRangeProbeResult
import com.ermao.library.shared.modules.reader.application.PdfRangeReadResult
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MAX_REQUEST_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.domain.RemoteByteRangeReaderSource
import java.nio.ByteBuffer
import java.nio.file.Files
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AndroidPdfRangeLoaderTest {
    @Test
    fun alignsAndMergesOnlyAdjacentMissingChunks() = runTest {
        withCache { cache, identity ->
            cache.writeAlignedRange(identity, 2L * CHUNK, ByteArray(CHUNK) { 9 })
            val server = RecordingServer()
            val loader = AndroidPdfRangeLoader(this, source(), identity, cache, server)

            loader.awaitRange(17, 5L * CHUNK - 17)

            assertEquals(
                listOf(PdfByteRange(0, 2L * CHUNK), PdfByteRange(3L * CHUNK, 5L * CHUNK)),
                server.ranges.sortedBy(PdfByteRange::begin),
            )
            assertTrue(server.ranges.all { it.endExclusive - it.begin <= PDF_RANGE_MAX_REQUEST_BYTES })
            assertContentEquals(ByteArray(8) { 9 }, cache.readCached(identity, 2L * CHUNK, 8))
        }
    }

    @Test
    fun boundsNetworkConcurrencyAndFeedsOnlyCachedBytesToPdfium() = runTest {
        withCache { cache, identity ->
            val server = RecordingServer(delayMillis = 20)
            val loader = AndroidPdfRangeLoader(this, source(), identity, cache, server)

            loader.awaitRange(0, 12L * CHUNK)

            assertEquals(3, server.ranges.size)
            assertEquals(2, server.maximumConcurrency.get())
            val byteSource = AndroidPdfiumByteSource(loader)
            val output = ByteBuffer.allocateDirect(16)
            assertTrue(byteSource.isRangeCached(0, 16))
            assertTrue(byteSource.readCachedBlock(0, output))
            output.flip()
            val actual = ByteArray(16)
            output.get(actual)
            assertContentEquals(ByteArray(16), actual)
        }
    }

    @Test
    fun authorizationVersionChangeRemovesThePreviousPrivateNamespace() = runTest {
        val root = Files.createTempDirectory("shuku-pdf-range-namespace-test").toFile()
        try {
            val cache = AndroidPdfRangeCache(root)
            val previous = PdfRangeCacheIdentity(namespace(1), "resource-1")
            val current = PdfRangeCacheIdentity(namespace(2), "resource-1")
            cache.writeAlignedRange(previous, 0, ByteArray(CHUNK) { 1 })

            cache.activateNamespace(current.namespace)
            cache.writeAlignedRange(current, 0, ByteArray(CHUNK) { 2 })

            assertEquals(null, cache.readCached(previous, 0, 1))
            assertContentEquals(byteArrayOf(2), cache.readCached(current, 0, 1))
        } finally {
            root.deleteRecursively()
        }
    }

    private suspend fun withCache(
        block: suspend (AndroidPdfRangeCache, PdfRangeCacheIdentity) -> Unit,
    ) {
        val root = Files.createTempDirectory("shuku-pdf-range-test").toFile()
        try {
            val identity = PdfRangeCacheIdentity(namespace(), "resource-1")
            block(AndroidPdfRangeCache(root), identity)
        } finally {
            root.deleteRecursively()
        }
    }

    private fun source() = RemoteByteRangeReaderSource(
        resourceId = "resource-1",
        displayTitle = "PDF",
        bookId = "book-1",
        assetId = "asset-1",
        namespace = namespace(),
        apiPath = "/api/resources/resource-1/asset",
        expectedSizeBytes = 12L * CHUNK,
    )

    private fun namespace(authorizationVersion: Long = 3) =
        ReaderSyncNamespace("server-1", "user-1", authorizationVersion)

    private class RecordingServer(private val delayMillis: Long = 0) : PdfRangeServerPort {
        val ranges = mutableListOf<PdfByteRange>()
        val maximumConcurrency = AtomicInteger()
        private val active = AtomicInteger()

        override suspend fun probe(source: RemoteByteRangeReaderSource): PdfRangeProbeResult =
            PdfRangeProbeResult.Available

        override suspend fun read(
            source: RemoteByteRangeReaderSource,
            range: PdfByteRange,
        ): PdfRangeReadResult {
            val current = active.incrementAndGet()
            maximumConcurrency.updateAndGet { maxOf(it, current) }
            try {
                if (delayMillis > 0) delay(delayMillis)
                synchronized(ranges) { ranges += range }
                return PdfRangeReadResult.Content(
                    range,
                    ByteArray((range.endExclusive - range.begin).toInt()) {
                        (range.begin / CHUNK).toByte()
                    },
                )
            } finally {
                active.decrementAndGet()
            }
        }
    }

    private companion object {
        const val CHUNK = PDF_RANGE_CHUNK_BYTES
    }
}
