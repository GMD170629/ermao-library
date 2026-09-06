package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.ReaderSafetyFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveCompressionRatioFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveCompressionRatioMax
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryBytesFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryCountFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryMaxCount
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveExpandedBytesFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveExpandedMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveIntegrityFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveStructureFailure
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.test.runTest
import org.apache.commons.compress.archivers.zip.ZipArchiveEntry
import org.apache.commons.compress.archivers.zip.ZipArchiveOutputStream
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

class AndroidEpubArchiveSafetyPreflightTest {
    @Test
    fun `accepts a bounded archive without eagerly reading resource bytes`() = runTest {
        withArchive(
            "mimetype" to "application/epub+zip",
            "META-INF/container.xml" to "<container/>",
            "OPS/chapter.xhtml" to "<html><body>safe</body></html>",
        ) { archive ->
            AndroidEpubArchiveSafetyPreflight.verify(archive)
        }
    }

    @Test
    fun `classifies fatal paths and archive integrity with their generated rules`() = runTest {
        val structureFailure = readerSafetyEpubArchiveStructureFailure()
        val integrityFailure = readerSafetyEpubArchiveIntegrityFailure()
        val safe = facts(path = "OPS/chapter.xhtml")
        for (entries in listOf(
            listOf(facts(path = "../chapter.xhtml")),
            listOf(facts(path = "OPS/link", isSymbolicLink = true)),
        )) {
            assertSafetyFailure(structureFailure) {
                AndroidEpubArchiveSafetyPreflight.verifyMetadata(entries, archiveLength = 1_024)
            }
        }

        val duplicate = AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(safe, safe.copy(path = "OPS/./chapter.xhtml")),
            archiveLength = 1_024,
        )
        assertEquals(integrityFailure, duplicate.quarantinedResources["OPS/chapter.xhtml"])

        val overlap = AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(
                facts(path = "OPS/a", localHeaderOffset = 0, dataOffset = 30, compressedSize = 50),
                facts(path = "OPS/b", localHeaderOffset = 70, dataOffset = 100),
            ),
            archiveLength = 1_024,
        )
        assertEquals(integrityFailure, overlap.quarantinedResources["OPS/a"])
        assertEquals(integrityFailure, overlap.quarantinedResources["OPS/b"])
        AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(facts(path = "OPS\\chapter.xhtml", isEncrypted = true)),
            archiveLength = 1_024,
        )
        AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(facts(path = "OPS/./single.xhtml")),
            archiveLength = 1_024,
        )
        AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(facts(path = "OPS/chapter.xhtml", uncompressedSize = 0L, compressedSize = 0L)),
            archiveLength = 1_024,
        )
    }

    @Test
    fun `does not treat checksum metadata as a whole publication rejection`() = runTest {
        AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(facts(path = "OPS/optional.xhtml")),
            archiveLength = 1_024,
        )
    }

    @Test
    fun `normalizes backslash paths for duplicate detection and path escape`() = runTest {
        val integrityFailure = readerSafetyEpubArchiveIntegrityFailure()
        val result = AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(facts(path = "OPS\\chapter.xhtml"), facts(path = "OPS/chapter.xhtml")),
            archiveLength = 1_024,
        )
        assertEquals(integrityFailure, result.quarantinedResources["OPS/chapter.xhtml"])
        val normalized = AndroidEpubArchiveSafetyPreflight.verifyMetadata(
            listOf(facts(path = "OPS\\..\\chapter.xhtml")),
            archiveLength = 1_024,
        )
        assertTrue(normalized.expectedResources.containsKey("chapter.xhtml"))
    }

    @Test
    fun `uses generated entry count entry size expanded size and compression ratio limits`() = runTest {
        val countLimit = readerSafetyEpubArchiveEntryMaxCount()
        assertSafetyFailure(readerSafetyEpubArchiveEntryCountFailure()) {
            AndroidEpubArchiveSafetyPreflight.verifyMetadata(
                List((countLimit + 1L).toInt()) { index -> facts(path = "OPS/$index") },
                archiveLength = Long.MAX_VALUE,
            )
        }

        assertSafetyFailure(readerSafetyEpubArchiveEntryBytesFailure()) {
            AndroidEpubArchiveSafetyPreflight.verifyMetadata(
                listOf(facts(uncompressedSize = readerSafetyEpubArchiveEntryMaxBytes() + 1L)),
                archiveLength = Long.MAX_VALUE,
            )
        }

        val expandedEntrySize = readerSafetyEpubArchiveEntryMaxBytes()
        val expandedEntryCount = readerSafetyEpubArchiveExpandedMaxBytes() / expandedEntrySize + 1L
        assertSafetyFailure(readerSafetyEpubArchiveExpandedBytesFailure()) {
            AndroidEpubArchiveSafetyPreflight.verifyMetadata(
                List(expandedEntryCount.toInt()) { index ->
                    facts(
                        path = "OPS/expanded-$index",
                        uncompressedSize = expandedEntrySize,
                        compressedSize = expandedEntrySize,
                    )
                },
                archiveLength = Long.MAX_VALUE,
            )
        }

        assertSafetyFailure(readerSafetyEpubArchiveCompressionRatioFailure()) {
            AndroidEpubArchiveSafetyPreflight.verifyMetadata(
                listOf(
                    facts(
                        uncompressedSize = readerSafetyEpubArchiveCompressionRatioMax() + 1L,
                        compressedSize = 1L,
                    ),
                ),
                archiveLength = Long.MAX_VALUE,
            )
        }
    }

    private suspend fun assertSafetyFailure(
        expected: ReaderSafetyFailure,
        action: suspend () -> Unit,
    ) {
        val failure = try {
            action()
            fail("Expected ReaderSafetyException")
        } catch (error: ReaderSafetyException) {
            error.failure
        }
        assertEquals(expected.ruleId, failure.ruleId)
        assertEquals(expected.errorCode, failure.errorCode)
    }

    private suspend fun withArchive(
        vararg entries: Pair<String, String>,
        action: suspend (File) -> Unit,
    ) {
        val file = Files.createTempFile("reader-safety-", ".epub").toFile()
        try {
            ZipArchiveOutputStream(file).use { output ->
                for ((path, content) in entries) {
                    val bytes = content.encodeToByteArray()
                    output.putArchiveEntry(ZipArchiveEntry(path))
                    output.write(bytes)
                    output.closeArchiveEntry()
                }
            }
            action(file)
        } finally {
            file.delete()
        }
    }

    private fun facts(
        path: String = "OPS/chapter.xhtml",
        isSymbolicLink: Boolean = false,
        isEncrypted: Boolean = false,
        uncompressedSize: Long = 16L,
        compressedSize: Long = uncompressedSize,
        localHeaderOffset: Long = 0L,
        dataOffset: Long = 30L,
    ) = AndroidEpubArchiveSafetyPreflight.EntryFacts(
        path = path,
        isSymbolicLink = isSymbolicLink,
        isEncrypted = isEncrypted,
        uncompressedSize = uncompressedSize,
        compressedSize = compressedSize,
        localHeaderOffset = localHeaderOffset,
        dataOffset = dataOffset,
    )

}
