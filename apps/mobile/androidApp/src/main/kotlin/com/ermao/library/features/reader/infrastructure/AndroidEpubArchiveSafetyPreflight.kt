package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.ReaderSafetyFailure
import com.ermao.library.shared.modules.reader.ReaderSafetyImplementationException
import com.ermao.library.shared.modules.reader.readerSafetyEngineAlgorithmUnsupported
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveCompressionRatioFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveCompressionRatioMax
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryBytesFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryCountFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveEntryMaxCount
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveExpandedBytesFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveExpandedMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveFatalFindings
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveStructureFailure
import com.ermao.library.shared.modules.reader.readerSafetyPlatformAlgorithmUnsupported
import java.io.File
import java.io.IOException
import java.util.zip.CRC32
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.apache.commons.compress.archivers.zip.ZipArchiveEntry
import org.apache.commons.compress.archivers.zip.ZipFile

/**
 * Reads the original EPUB as a ZIP without extracting or mutating it. Archive facts come from
 * Apache Commons Compress; policy limits and outcomes come exclusively from the generated contract.
 */
internal object AndroidEpubArchiveSafetyPreflight {
    suspend fun verify(file: File): Unit = withContext(Dispatchers.IO) {
        try {
            ZipFile.builder().setPath(file.toPath()).get().use { archive ->
                val entries = archive.entries.asSequence().toList()
                verifyMetadata(entries.map { entry -> entry.facts() }, file.length())
                verifyContents(archive, entries)
            }
        } catch (error: ReaderSafetyException) {
            throw error
        } catch (error: ReaderSafetyImplementationException) {
            throw error
        } catch (error: IOException) {
            throw ReaderSafetyException(readerSafetyEpubArchiveStructureFailure()).also {
                it.initCause(error)
            }
        } catch (error: IllegalArgumentException) {
            throw ReaderSafetyException(readerSafetyEpubArchiveStructureFailure()).also {
                it.initCause(error)
            }
        }
    }

    internal fun verifyMetadata(entries: List<EntryFacts>, archiveLength: Long) {
        val fatalFindings = readerSafetyEpubArchiveFatalFindings().toSet()
        fatalFindings.firstOrNull { finding ->
            when (finding) {
                "PATH_ESCAPE",
                "ABSOLUTE_PATH",
                "BACKSLASH_PATH",
                "NUL_PATH",
                "DOT_SEGMENT",
                "DUPLICATE_CANONICAL_ENTRY",
                "SYMLINK",
                "ENCRYPTED_ENTRY",
                "OVERLAPPING_ENTRY",
                "CRC_MISMATCH",
                -> false
                else -> true
            }
        }?.let {
            throw ReaderSafetyImplementationException(
                readerSafetyPlatformAlgorithmUnsupported(readerSafetyEpubArchiveStructureFailure().ruleId),
            )
        }

        if (entries.size.toLong() > readerSafetyEpubArchiveEntryMaxCount()) {
            reject(readerSafetyEpubArchiveEntryCountFailure())
        }

        val canonicalPaths = mutableSetOf<String>()
        var expandedBytes = 0L
        for (entry in entries) {
            val path = entry.path.removeSuffix("/")
            rejectFinding(fatalFindings, "ABSOLUTE_PATH", path.startsWith('/') || WINDOWS_DRIVE_PATH.matches(path))
            rejectFinding(fatalFindings, "BACKSLASH_PATH", '\\' in path)
            rejectFinding(fatalFindings, "NUL_PATH", '\u0000' in path)
            val segments = path.split('/')
            rejectFinding(
                fatalFindings,
                "DOT_SEGMENT",
                path.isEmpty() || segments.any { segment -> segment.isEmpty() || segment == "." || segment == ".." },
            )
            rejectFinding(fatalFindings, "PATH_ESCAPE", path == ".." || path.startsWith("../"))
            rejectFinding(fatalFindings, "DUPLICATE_CANONICAL_ENTRY", !canonicalPaths.add(path))
            rejectFinding(fatalFindings, "SYMLINK", entry.isSymbolicLink)
            rejectFinding(fatalFindings, "ENCRYPTED_ENTRY", entry.isEncrypted)

            if (entry.uncompressedSize < 0L || entry.compressedSize < 0L) {
                rejectFinding(fatalFindings, "CRC_MISMATCH", condition = true)
            }
            if (entry.uncompressedSize > readerSafetyEpubArchiveEntryMaxBytes()) {
                reject(readerSafetyEpubArchiveEntryBytesFailure())
            }
            if (exceedsCompressionRatio(entry.uncompressedSize, entry.compressedSize)) {
                reject(readerSafetyEpubArchiveCompressionRatioFailure())
            }
            expandedBytes = addOrReject(expandedBytes, entry.uncompressedSize)
            if (expandedBytes > readerSafetyEpubArchiveExpandedMaxBytes()) {
                reject(readerSafetyEpubArchiveExpandedBytesFailure())
            }

            if (entry.dataOffset > Long.MAX_VALUE - entry.compressedSize) {
                rejectFinding(fatalFindings, "OVERLAPPING_ENTRY", condition = true)
            }
            val dataEnd = entry.dataOffset + entry.compressedSize
            if (
                entry.localHeaderOffset < 0L ||
                entry.dataOffset < entry.localHeaderOffset ||
                dataEnd > archiveLength
            ) {
                rejectFinding(fatalFindings, "OVERLAPPING_ENTRY", condition = true)
            }
        }

        val physicalEntries = entries.sortedBy(EntryFacts::localHeaderOffset)
        physicalEntries.zipWithNext().firstOrNull { (current, next) ->
            next.localHeaderOffset < current.dataOffset + current.compressedSize
        }?.let {
            rejectFinding(fatalFindings, "OVERLAPPING_ENTRY", condition = true)
        }
    }

    private fun verifyContents(archive: ZipFile, entries: List<ZipArchiveEntry>) {
        val fatalFindings = readerSafetyEpubArchiveFatalFindings().toSet()
        var expandedBytes = 0L
        val buffer = ByteArray(STREAM_BUFFER_BYTES)
        for (entry in entries) {
            if (entry.isDirectory) continue
            if (!archive.canReadEntryData(entry)) {
                throw ReaderSafetyImplementationException(
                    readerSafetyEngineAlgorithmUnsupported(readerSafetyEpubArchiveStructureFailure().ruleId),
                )
            }
            var entryBytes = 0L
            val checksum = CRC32()
            archive.getInputStream(entry).use { input ->
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    if (read == 0) continue
                    entryBytes = addOrReject(entryBytes, read.toLong())
                    expandedBytes = addOrReject(expandedBytes, read.toLong())
                    if (entryBytes > readerSafetyEpubArchiveEntryMaxBytes()) {
                        reject(readerSafetyEpubArchiveEntryBytesFailure())
                    }
                    if (expandedBytes > readerSafetyEpubArchiveExpandedMaxBytes()) {
                        reject(readerSafetyEpubArchiveExpandedBytesFailure())
                    }
                    checksum.update(buffer, 0, read)
                }
            }
            rejectFinding(
                fatalFindings,
                "CRC_MISMATCH",
                entryBytes != entry.size ||
                    entry.crc == ZipArchiveEntry.CRC_UNKNOWN.toLong() ||
                    checksum.value != entry.crc,
            )
        }
    }

    private fun rejectFinding(fatalFindings: Set<String>, finding: String, condition: Boolean) {
        if (condition && finding in fatalFindings) reject(readerSafetyEpubArchiveStructureFailure())
    }

    private fun exceedsCompressionRatio(uncompressedSize: Long, compressedSize: Long): Boolean {
        if (uncompressedSize <= 0L) return false
        if (compressedSize <= 0L) return true
        val maximumRatio = readerSafetyEpubArchiveCompressionRatioMax()
        val quotient = uncompressedSize / compressedSize
        return quotient > maximumRatio ||
            (quotient == maximumRatio && uncompressedSize % compressedSize != 0L)
    }

    private fun addOrReject(left: Long, right: Long): Long {
        if (left < 0L || right < 0L || left > Long.MAX_VALUE - right) {
            reject(readerSafetyEpubArchiveExpandedBytesFailure())
        }
        return left + right
    }

    private fun reject(failure: ReaderSafetyFailure): Nothing = throw ReaderSafetyException(failure)

    internal data class EntryFacts(
        val path: String,
        val isSymbolicLink: Boolean,
        val isEncrypted: Boolean,
        val uncompressedSize: Long,
        val compressedSize: Long,
        val localHeaderOffset: Long,
        val dataOffset: Long,
    )

    private fun ZipArchiveEntry.facts(): EntryFacts = EntryFacts(
        path = name,
        isSymbolicLink = isUnixSymlink,
        isEncrypted = generalPurposeBit.usesEncryption(),
        uncompressedSize = size,
        compressedSize = compressedSize,
        localHeaderOffset = localHeaderOffset,
        dataOffset = dataOffset,
    )

    private val WINDOWS_DRIVE_PATH = Regex("^[A-Za-z]:")
    private const val STREAM_BUFFER_BYTES = 64 * 1024
}
