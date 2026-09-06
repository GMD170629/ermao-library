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
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveIntegrityFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveIntegrityFindings
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveStructureFailure
import com.ermao.library.shared.modules.reader.readerSafetyOptionalResourceFailure
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
 * Resource bytes remain lazy so a checksum/decoder failure can be attributed to the affected
 * resource by the protected Readium container instead of rejecting an otherwise readable book.
 */
internal object AndroidEpubArchiveSafetyPreflight {
    suspend fun verify(file: File): AndroidEpubArchiveSafetyResult = withContext(Dispatchers.IO) {
        try {
            ZipFile.builder().setPath(file.toPath()).get().use { archive ->
                val entries = archive.entries.asSequence().toList()
                verifyMetadata(entries.map { entry -> entry.facts() }, file.length())
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

    /** Verifies bytes returned by the protected Readium resource before sanitization. */
    internal fun verifyResourceBytes(
        expected: AndroidEpubArchiveResourceFacts,
        bytes: ByteArray,
    ) {
        val checksum = CRC32().apply { update(bytes) }
        if (
            expected.uncompressedSize != bytes.size.toLong() ||
            expected.crc32 == ZipArchiveEntry.CRC_UNKNOWN.toLong() ||
            checksum.value != expected.crc32
        ) {
            reject(readerSafetyOptionalResourceFailure())
        }
    }

    internal fun verifyMetadata(
        entries: List<EntryFacts>,
        archiveLength: Long,
    ): AndroidEpubArchiveSafetyResult {
        val fatalFindings = readerSafetyEpubArchiveFatalFindings().toSet()
        val integrityFindings = readerSafetyEpubArchiveIntegrityFindings().toSet()
        validateFindingConfiguration(fatalFindings, integrityFindings)

        if (entries.size.toLong() > readerSafetyEpubArchiveEntryMaxCount()) {
            reject(readerSafetyEpubArchiveEntryCountFailure())
        }

        val entriesByCanonicalPath = mutableMapOf<String, MutableList<EntryFacts>>()
        val expectedResources = mutableMapOf<String, AndroidEpubArchiveResourceFacts>()
        val quarantinedResources = mutableMapOf<String, ReaderSafetyFailure>()
        var expandedBytes = 0L
        for (entry in entries) {
            val rawPath = entry.path
            val path = rawPath.removeSuffix("/")
            rejectFinding(fatalFindings, integrityFindings, "NUL_PATH", '\u0000' in rawPath)
            rejectFinding(
                fatalFindings,
                integrityFindings,
                "ABSOLUTE_PATH",
                rawPath.startsWith('/') || rawPath.startsWith('\\') || WINDOWS_DRIVE_PATH.matches(rawPath),
            )
            rejectFinding(fatalFindings, integrityFindings, "SYMLINK", entry.isSymbolicLink)

            val canonical = canonicalArchivePath(path)
            rejectFinding(fatalFindings, integrityFindings, "PATH_ESCAPE", canonical == null)
            if (canonical != null && canonical.isNotEmpty() && !entry.isDirectory) {
                entriesByCanonicalPath.getOrPut(canonical) { mutableListOf() }.add(entry)
                expectedResources[canonical] = AndroidEpubArchiveResourceFacts(
                    uncompressedSize = entry.uncompressedSize,
                    crc32 = entry.crc32,
                )
                if (
                    "CRC_MISMATCH" in integrityFindings &&
                        entry.crc32 == ZipArchiveEntry.CRC_UNKNOWN.toLong()
                ) {
                    quarantinedResources[canonical] = readerSafetyOptionalResourceFailure()
                }
            }

            // DOT_SEGMENT and BACKSLASH_PATH are lexical facts only. They are normalized for
            // duplicate/path-escape detection and are not standalone rejection conditions.
            if (entry.uncompressedSize < 0L || entry.compressedSize < 0L) {
                if ("CRC_MISMATCH" in integrityFindings && canonical != null && canonical.isNotEmpty()) {
                    quarantinedResources[canonical] = readerSafetyOptionalResourceFailure()
                }
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

            val dataEnd = if (
                entry.dataOffset < 0L || entry.compressedSize < 0L ||
                entry.dataOffset > Long.MAX_VALUE - entry.compressedSize
            ) {
                null
            } else {
                entry.dataOffset + entry.compressedSize
            }
            if (
                dataEnd == null ||
                    entry.localHeaderOffset < 0L ||
                    entry.dataOffset < entry.localHeaderOffset ||
                    dataEnd > archiveLength
            ) {
                quarantineIntegrityEntry(
                    entry,
                    canonical,
                    integrityFindings,
                    quarantinedResources,
                )
            }
        }

        entriesByCanonicalPath
            .filterValues { it.size > 1 }
            .forEach { (canonical, _) ->
                if ("DUPLICATE_CANONICAL_ENTRY" in integrityFindings) {
                    quarantinedResources[canonical] = readerSafetyEpubArchiveIntegrityFailure()
                }
            }

        val physicalEntries = entries.sortedBy(EntryFacts::localHeaderOffset)
        physicalEntries.zipWithNext().filter { (current, next) ->
            val currentEnd = if (
                current.dataOffset >= 0L && current.compressedSize >= 0L &&
                current.dataOffset <= Long.MAX_VALUE - current.compressedSize
            ) {
                current.dataOffset + current.compressedSize
            } else {
                Long.MIN_VALUE
            }
            currentEnd != Long.MIN_VALUE && next.localHeaderOffset < currentEnd
        }.forEach { (current, next) ->
            if ("OVERLAPPING_ENTRY" in integrityFindings) {
                quarantineIntegrityEntry(
                    current,
                    canonicalArchivePath(current.path.removeSuffix("/")),
                    integrityFindings,
                    quarantinedResources,
                )
                quarantineIntegrityEntry(
                    next,
                    canonicalArchivePath(next.path.removeSuffix("/")),
                    integrityFindings,
                    quarantinedResources,
                )
            }
        }
        return AndroidEpubArchiveSafetyResult(
            quarantinedResources = quarantinedResources,
            expectedResources = expectedResources,
        )
    }

    private fun quarantineIntegrityEntry(
        entry: EntryFacts,
        canonical: String?,
        integrityFindings: Set<String>,
        quarantinedResources: MutableMap<String, ReaderSafetyFailure>,
    ) {
        if (
            canonical != null && canonical.isNotEmpty() && !entry.isDirectory &&
                "OVERLAPPING_ENTRY" in integrityFindings
        ) {
            quarantinedResources[canonical] = readerSafetyEpubArchiveIntegrityFailure()
        }
    }

    private fun validateFindingConfiguration(fatalFindings: Set<String>, integrityFindings: Set<String>) {
        val supportedFatal = setOf("PATH_ESCAPE", "ABSOLUTE_PATH", "NUL_PATH", "SYMLINK")
        fatalFindings.firstOrNull { it !in supportedFatal }?.let {
            throw ReaderSafetyImplementationException(
                readerSafetyPlatformAlgorithmUnsupported(readerSafetyEpubArchiveStructureFailure().ruleId),
            )
        }
        val supportedIntegrity = setOf("DUPLICATE_CANONICAL_ENTRY", "OVERLAPPING_ENTRY", "CRC_MISMATCH")
        integrityFindings.firstOrNull { it !in supportedIntegrity }?.let {
            throw ReaderSafetyImplementationException(
                readerSafetyEngineAlgorithmUnsupported(readerSafetyEpubArchiveIntegrityFailure().ruleId),
            )
        }
    }

    private fun canonicalArchivePath(path: String): String? {
        val segments = path.replace('\\', '/').split('/')
        val canonical = ArrayDeque<String>()
        for (segment in segments) {
            when (segment) {
                "", "." -> Unit
                ".." -> if (canonical.isEmpty()) return null else canonical.removeLast()
                else -> canonical.addLast(segment)
            }
        }
        return canonical.joinToString("/")
    }

    private fun rejectFinding(
        fatalFindings: Set<String>,
        integrityFindings: Set<String>,
        finding: String,
        condition: Boolean,
    ) {
        if (!condition) return
        when {
            finding in fatalFindings -> reject(readerSafetyEpubArchiveStructureFailure())
            finding in integrityFindings -> reject(readerSafetyEpubArchiveIntegrityFailure())
        }
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
        val crc32: Long = ZipArchiveEntry.CRC_UNKNOWN.toLong(),
        val isDirectory: Boolean = false,
    )

    internal data class AndroidEpubArchiveResourceFacts(
        val uncompressedSize: Long,
        val crc32: Long,
    )

    internal data class AndroidEpubArchiveSafetyResult(
        val quarantinedResources: Map<String, ReaderSafetyFailure>,
        val expectedResources: Map<String, AndroidEpubArchiveResourceFacts>,
    ) {
        fun quarantineFor(path: String): ReaderSafetyFailure? =
            canonicalArchivePath(path)?.let(quarantinedResources::get)

        fun expectedFor(path: String): AndroidEpubArchiveResourceFacts? =
            canonicalArchivePath(path)?.let(expectedResources::get)
    }

    private fun ZipArchiveEntry.facts(): EntryFacts = EntryFacts(
        path = name,
        isSymbolicLink = isUnixSymlink,
        isEncrypted = generalPurposeBit.usesEncryption(),
        uncompressedSize = size,
        compressedSize = compressedSize,
        localHeaderOffset = localHeaderOffset,
        dataOffset = dataOffset,
        crc32 = crc,
        isDirectory = isDirectory,
    )

    internal fun canonicalPath(path: String): String? = canonicalArchivePath(path)

    private val WINDOWS_DRIVE_PATH = Regex("^[A-Za-z]:")
}
