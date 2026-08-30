package com.ermao.library.features.reader

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.archive.infrastructure.ArchiveCore
import com.ermao.library.archive.infrastructure.ArchiveCoreException
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.CbzReadiumPublicationFactory
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.readerSafetyComicExpandedMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxCount
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ReaderRarInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val testContext: Context = instrumentation.context
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val publishedResourceIds = mutableListOf<String>()
    private val temporaryArchives = mutableListOf<File>()

    @After
    fun removeArtifacts() = runBlocking {
        publishedResourceIds.forEach { publicationStore.delete(it) }
        temporaryArchives.forEach(File::delete)
    }

    @Test
    fun pageBudgetBlocksOnlyOversizedImagesAndIgnoresLargeNonPageEntries() {
        val archiveFile = temporaryArchive("page-budget.cbz")
        val oversizedBytes = readerSafetyComicPageMaxBytes() + 1L
        ZipOutputStream(FileOutputStream(archiveFile)).use { archive ->
            archive.writeStoredEntry("metadata.bin", oversizedBytes)
            archive.writeStoredEntry("oversized.png", oversizedBytes)
            archive.writeStoredEntry("readable.png", 1L)
        }

        openArchive(archiveFile).use { archive ->
            assertEquals(listOf("readable.png"), archive.pages.map { it.path })
        }
    }

    @Test
    fun generatedCompressionRatioRejectsArchiveBombs() {
        val archiveFile = temporaryArchive("ratio-bomb.cbz")
        ZipOutputStream(FileOutputStream(archiveFile)).use { archive ->
            archive.putNextEntry(ZipEntry("payload.bin"))
            repeat(16) { archive.write(ByteArray(64 * 1024)) }
            archive.closeEntry()
            archive.putNextEntry(ZipEntry("readable.png"))
            archive.write(1)
            archive.closeEntry()
        }

        val failure = try {
            openArchive(archiveFile).close()
            null
        } catch (error: ArchiveCoreException) {
            error
        }
        assertEquals("ARCHIVE_COMPRESSION_RATIO_EXCEEDED", requireNotNull(failure).stableCode)
    }

    private fun openArchive(file: File): ArchiveCore = ArchiveCore.open(
        file,
        readerSafetyComicPageMaxCount().toInt(),
        readerSafetyComicPageMaxBytes(),
        readerSafetyComicExpandedMaxBytes(),
    )

    private fun temporaryArchive(name: String): File =
        File(context.cacheDir, "${UUID.randomUUID()}-$name").also(temporaryArchives::add)

    private fun ZipOutputStream.writeStoredEntry(path: String, size: Long) {
        val buffer = ByteArray(64 * 1024) { index -> ((index * 31 + 7) and 0xff).toByte() }
        val checksum = CRC32()
        var remaining = size
        while (remaining > 0L) {
            val count = minOf(buffer.size.toLong(), remaining).toInt()
            checksum.update(buffer, 0, count)
            remaining -= count
        }
        putNextEntry(
            ZipEntry(path).also { entry ->
                entry.method = ZipEntry.STORED
                entry.size = size
                entry.compressedSize = size
                entry.crc = checksum.value
            },
        )
        remaining = size
        while (remaining > 0L) {
            val count = minOf(buffer.size.toLong(), remaining).toInt()
            write(buffer, 0, count)
            remaining -= count
        }
        closeEntry()
    }

    @Test
    fun opensOriginalRar5AndCbrWithoutConversionOrUnpacking() = runBlocking {
        val fixtures = listOf(
            Fixture("reader-pages.rar", ReaderSourceFormat.Rar),
            Fixture("reader-pages.cbr", ReaderSourceFormat.Cbr),
        )

        fixtures.forEach { fixture ->
            val resourceId = "archive-reader-${UUID.randomUUID()}"
            publishedResourceIds += resourceId
            val source = testContext.assets.open(fixture.assetPath).use { input ->
                publicationStore.publishLocalPublication(
                    resourceId = resourceId,
                    displayTitle = fixture.assetPath.substringAfterLast('/'),
                    input = input,
                    sourceFormat = fixture.sourceFormat,
                )
            }
            val original = publicationStore.resolve(source)

            ArchiveCore.open(
                original,
                readerSafetyComicPageMaxCount().toInt(),
                readerSafetyComicPageMaxBytes(),
                readerSafetyComicExpandedMaxBytes(),
            ).use { archive ->
                assertEquals("libarchive 3.8.9", ArchiveCore.version)
                assertEquals(2, archive.pages.size)
                assertTrue(archive.readPage(0).isNotEmpty())
            }
            val pages = CbzReadiumPublicationFactory().indexPages(original)
            assertEquals(2, pages.size)
            assertEquals(pages.indices.map { "pages/$it" }, pages.map { it.resourceHref })
        }
    }

    private data class Fixture(
        val assetPath: String,
        val sourceFormat: ReaderSourceFormat,
    )
}
