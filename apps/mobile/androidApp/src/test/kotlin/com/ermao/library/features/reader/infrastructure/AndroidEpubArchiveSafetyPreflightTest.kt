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
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveStructureFailure
import java.io.File
import java.io.RandomAccessFile
import java.nio.file.Files
import kotlinx.coroutines.test.runTest
import org.apache.commons.compress.archivers.zip.ZipArchiveEntry
import org.apache.commons.compress.archivers.zip.ZipArchiveOutputStream
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.fail

class AndroidEpubArchiveSafetyPreflightTest {
    @Test
    fun `accepts a bounded archive and verifies every entry CRC`() = runTest {
        withArchive(
            "mimetype" to "application/epub+zip",
            "META-INF/container.xml" to "<container/>",
            "OPS/chapter.xhtml" to "<html><body>safe</body></html>",
        ) { archive ->
            AndroidEpubArchiveSafetyPreflight.verify(archive)
        }
    }

    @Test
    fun `rejects path escape duplicate symlink encryption overlap and CRC facts with generated structure rule`() = runTest {
        val structureFailure = readerSafetyEpubArchiveStructureFailure()
        val safe = facts(path = "OPS/chapter.xhtml")
        val cases = listOf(
            listOf(facts(path = "../chapter.xhtml")),
            listOf(safe, safe.copy(localHeaderOffset = 128, dataOffset = 160)),
            listOf(facts(path = "OPS/link", isSymbolicLink = true)),
            listOf(facts(path = "OPS/secret", isEncrypted = true)),
            listOf(
                facts(path = "OPS/a", localHeaderOffset = 0, dataOffset = 30, compressedSize = 50),
                facts(path = "OPS/b", localHeaderOffset = 70, dataOffset = 100),
            ),
        )
        for (entries in cases) {
            assertSafetyFailure(structureFailure) {
                AndroidEpubArchiveSafetyPreflight.verifyMetadata(entries, archiveLength = 1_024)
            }
        }

        withArchive("OPS/chapter.xhtml" to "CRC-protected content") { archive ->
            corruptCentralDirectoryCrc(archive)
            assertSafetyFailure(structureFailure) {
                AndroidEpubArchiveSafetyPreflight.verify(archive)
            }
        }
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

    private fun corruptCentralDirectoryCrc(file: File) {
        RandomAccessFile(file, "rw").use { randomAccess ->
            val bytes = ByteArray(file.length().toInt())
            randomAccess.readFully(bytes)
            val directory = bytes.indexOfSignature(CENTRAL_DIRECTORY_SIGNATURE)
            check(directory >= 0) { "Central directory was not written" }
            randomAccess.seek((directory + CENTRAL_DIRECTORY_CRC_OFFSET).toLong())
            randomAccess.writeInt(0)
        }
    }

    private fun ByteArray.indexOfSignature(signature: ByteArray): Int =
        indices.firstOrNull { start ->
            start <= size - signature.size && signature.indices.all { offset -> this[start + offset] == signature[offset] }
        } ?: -1

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

    private companion object {
        val CENTRAL_DIRECTORY_SIGNATURE = byteArrayOf(0x50, 0x4B, 0x01, 0x02)
        const val CENTRAL_DIRECTORY_CRC_OFFSET = 16
    }
}
