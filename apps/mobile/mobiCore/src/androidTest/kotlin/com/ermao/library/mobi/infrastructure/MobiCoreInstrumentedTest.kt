package com.ermao.library.mobi.infrastructure

import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import org.junit.Assert.assertEquals
import kotlin.system.measureTimeMillis
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MobiCoreInstrumentedTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun corpusProducesQueryableResourcesReadingOrderAndToc() {
        val fixtureNames = context.assets.list("")
            .orEmpty()
            .filter {
                !it.startsWith("negative-") && (
                    it.endsWith(".mobi") || it.endsWith(".azw") ||
                        it.endsWith(".azw3") || it.endsWith(".prc")
                )
            }
            .sorted()
        assertTrue(fixtureNames.size >= 10)

        fixtureNames.forEach { fixtureName ->
            val fixture = copyAsset(fixtureName)
            MobiCoreBook.open(fixture).use { book ->
                val info = book.info()
                assertTrue(info.resourceCount > 0)
                assertTrue(info.readingOrderCount > 0)
                repeat(info.resourceCount) { resourceIndex ->
                    val resource = book.resource(resourceIndex)
                    assertTrue(resource.sourceName.isNotBlank())
                    assertTrue(resource.mediaType.isNotBlank())
                    val firstChunk = book.readResource(resourceIndex, 0L, 4096)
                    assertTrue(firstChunk.size <= 4096)
                    assertTrue(
                        book.readResource(resourceIndex, resource.decodedLength, 4096).isEmpty(),
                    )
                }
                repeat(info.readingOrderCount) { position ->
                    assertTrue(book.readingOrderResourceIndex(position) in 0 until info.resourceCount)
                }
                repeat(info.tocCount) { tocIndex ->
                    val toc = book.toc(tocIndex)
                    assertTrue(toc.parentIndex == null || toc.parentIndex < tocIndex)
                    assertTrue(
                        toc.targetResourceIndex == null || toc.targetResourceIndex < info.resourceCount,
                    )
                }
                assertNotNull(book.metadata(MobiCoreMetadataField.Title))
            }
        }
    }

    @Test
    fun hostAndAndroidProduceIdenticalAbiV1GoldenSnapshots() {
        listOf("01-basic-mobi6", "11-upstream-huff-cdic").forEach { fixtureBaseName ->
            val fixture = copyAsset("$fixtureBaseName.mobi")
            val actual = MobiCoreBook.open(fixture).use(::snapshot)
            val expected = context.assets.open("$fixtureBaseName.abi-v1.snapshot")
                .bufferedReader(Charsets.UTF_8)
                .use { it.readText() }
            assertEquals(expected, actual)
        }
    }

    @Test
    fun syntheticLargePublicationOpensIndexesReadsAndClosesWithoutOom() {
        val largeFixture = copyAsset("test.azw3", "synthetic-110m.azw3")
        RandomAccessFile(largeFixture, "rw").use { file ->
            file.setLength(110L * 1024L * 1024L)
        }
        val beforeRss = residentSetKilobytes()
        val openRssSamples = mutableListOf<Long>()
        val closedRssSamples = mutableListOf<Long>()
        val elapsed = measureTimeMillis {
            repeat(LARGE_FILE_LIFECYCLE_ITERATIONS) {
                MobiCoreBook.open(largeFixture).use { book ->
                    val info = book.info()
                    assertTrue(info.resourceCount > 0)
                    val readingResource = book.readingOrderResourceIndex(0)
                    assertTrue(book.readResource(readingResource, 0L, 4096).isNotEmpty())
                    openRssSamples += residentSetKilobytes()
                }
                Runtime.getRuntime().gc()
                Thread.sleep(50L)
                closedRssSamples += residentSetKilobytes()
            }
        }
        Log.i(
            "ErmaoMobiR5",
            "synthetic_110m iterations=$LARGE_FILE_LIFECYCLE_ITERATIONS " +
                "total_ms=$elapsed rss_before_kb=$beforeRss " +
                "rss_open_kb=$openRssSamples rss_closed_kb=$closedRssSamples",
        )
        assertTrue(elapsed > 0L)
        assertTrue(openRssSamples.all { it > 0L })
        assertTrue(closedRssSamples.all { it > 0L })
        assertTrue(closedRssSamples.last() <= closedRssSamples.first() + MAXIMUM_RSS_DRIFT_KB)
    }

    @Test
    fun closeIsIdempotentAndClosedHandleCannotBeRead() {
        val book = MobiCoreBook.open(copyAsset("01-basic-mobi6.mobi"))
        book.close()
        book.close()
        val failure = runCatching { book.info() }.exceptionOrNull()
        assertTrue(failure is IllegalStateException)
    }

    @Test
    fun negativeCorpusReturnsStableStatusCodes() {
        val expectations = mapOf(
            "negative-synthetic-drm-header.mobi" to MobiCoreStatus.DrmProtected,
            "negative-upstream-drm-v1.mobi" to MobiCoreStatus.DrmProtected,
            "negative-no-content.mobi" to MobiCoreStatus.NoContent,
            "negative-truncated.mobi" to MobiCoreStatus.Corrupt,
            "negative-corrupt-record-offset.mobi" to MobiCoreStatus.Corrupt,
            "negative-pseudo.mobi" to MobiCoreStatus.Unsupported,
            "negative-synthetic-kfx.kfx" to MobiCoreStatus.Unsupported,
            "negative-synthetic-azw4.azw4" to MobiCoreStatus.Unsupported,
        )
        expectations.forEach { (fixtureName, expectedStatus) ->
            val failure = runCatching { MobiCoreBook.open(copyAsset(fixtureName)) }.exceptionOrNull()
            assertTrue(failure is MobiCoreException)
            assertTrue((failure as MobiCoreException).status == expectedStatus)
        }
    }

    private fun copyAsset(name: String, outputName: String = name): File {
        val target = File(context.cacheDir, outputName)
        context.assets.open(name).use { input ->
            target.outputStream().use(input::copyTo)
        }
        return target
    }

    private fun residentSetKilobytes(): Long = File("/proc/self/status")
        .useLines { lines ->
            lines.firstOrNull { it.startsWith("VmRSS:") }
                ?.split(Regex("\\s+"))
                ?.getOrNull(1)
                ?.toLongOrNull()
                ?: -1L
        }

    private fun snapshot(book: MobiCoreBook): String = buildString {
        val info = book.info()
        appendLine("snapshot-version\t1")
        appendLine("abi\t${MobiCoreBook.abiVersion}")
        appendLine("parser\t${MobiCoreBook.parserIdentifier.hexEncoded()}")
        appendLine("normalization\t${MobiCoreBook.normalizationIdentifier.hexEncoded()}")
        appendLine(
            "book\t${info.format.snapshotCode}\t${info.readingDirection.snapshotCode}\t" +
                (info.coverResourceIndex?.toString() ?: MOBI_CORE_INDEX_NONE_TEXT),
        )
        MobiCoreMetadataField.entries.forEach { field ->
            appendLine("metadata\t${field.code}\t${book.metadata(field).nullableHexEncoded()}")
        }
        repeat(info.resourceCount) { resourceIndex ->
            val resource = book.resource(resourceIndex)
            val digest = MessageDigest.getInstance("SHA-256")
            var offset = 0L
            while (offset < resource.decodedLength) {
                val bytes = book.readResource(
                    resourceIndex,
                    offset,
                    minOf(MOBI_CORE_MAX_READ_BYTES.toLong(), resource.decodedLength - offset).toInt(),
                )
                check(bytes.isNotEmpty()) { "resource ended before its declared length" }
                digest.update(bytes)
                offset += bytes.size
            }
            appendLine(
                "resource\t$resourceIndex\t${resource.category.snapshotCode}\t" +
                    "${resource.sourceUid}\t${resource.decodedLength}\t" +
                    "${digest.digest().hexEncoded()}\t${resource.sourceName.hexEncoded()}\t" +
                    resource.mediaType.hexEncoded(),
            )
        }
        repeat(info.readingOrderCount) { position ->
            appendLine("reading\t$position\t${book.readingOrderResourceIndex(position)}")
        }
        repeat(info.tocCount) { tocIndex ->
            val toc = book.toc(tocIndex)
            appendLine(
                "toc\t$tocIndex\t${toc.parentIndex.snapshotIndex}\t" +
                    "${toc.targetResourceIndex.snapshotIndex}\t${toc.title.nullableHexEncoded()}\t" +
                    toc.fragment.nullableHexEncoded(),
            )
        }
        repeat(info.warningCount) { warningIndex ->
            val warning = book.warning(warningIndex)
            appendLine(
                "warning\t$warningIndex\t${warning.code}\t${warning.relatedIndex.snapshotIndex}",
            )
        }
    }

    private val MobiCoreFormat.snapshotCode: Int
        get() = ordinal + 1

    private val MobiCoreReadingDirection.snapshotCode: Int
        get() = ordinal

    private val MobiCoreResourceCategory.snapshotCode: Int
        get() = ordinal + 1

    private val Int?.snapshotIndex: String
        get() = this?.toString() ?: MOBI_CORE_INDEX_NONE_TEXT

    private fun String?.nullableHexEncoded(): String = this?.hexEncoded() ?: "-"

    private fun String.hexEncoded(): String = encodeToByteArray().hexEncoded()

    private fun ByteArray.hexEncoded(): String = joinToString(separator = "") { byte ->
        "%02x".format(byte.toInt() and 0xff)
    }

    private companion object {
        const val MOBI_CORE_INDEX_NONE_TEXT = "4294967295"
        const val LARGE_FILE_LIFECYCLE_ITERATIONS = 5
        const val MAXIMUM_RSS_DRIFT_KB = 8L * 1024L
    }
}
