package com.ermao.library.features.reader.infrastructure

import android.content.Context
import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSource
import com.ermao.library.shared.modules.reader.PublicationDownloadSink
import com.ermao.library.shared.modules.reader.PublicationDownloadSinkFactory
import com.ermao.library.shared.modules.reader.ReaderPublicationDownload
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.zip.ZipFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal class AndroidReaderPublicationStore(context: Context) {
    private val publicationRoot = File(context.filesDir, PUBLICATION_DIRECTORY)

    suspend fun publishLocalEpub(
        sourceId: String,
        displayTitle: String,
        input: InputStream,
        workId: String? = null,
        volumeId: String? = null,
    ): LocalReaderSource = withContext(Dispatchers.IO) {
        require(sourceId.isNotBlank() && sourceId.length <= MAX_SOURCE_ID_LENGTH) {
            "Reader source id is invalid"
        }
        require(displayTitle.isNotBlank() && displayTitle.length <= MAX_TITLE_LENGTH) {
            "Reader title is invalid"
        }
        publicationRoot.mkdirs()
        require(publicationRoot.isDirectory) { "Reader publication root is unavailable" }

        val target = targetFile(sourceId)
        val temporary = File(publicationRoot, ".${target.name}.${System.nanoTime()}.tmp")
        val digest = MessageDigest.getInstance("SHA-256")
        var written = 0L
        try {
            FileOutputStream(temporary).use { output ->
                val buffer = ByteArray(COPY_BUFFER_BYTES)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    written += count
                    require(written <= MAX_PUBLICATION_BYTES) { "Reader publication exceeds the size limit" }
                    digest.update(buffer, 0, count)
                    output.write(buffer, 0, count)
                }
                output.fd.sync()
            }
            require(written > 0) { "Reader publication is empty" }
            atomicReplace(temporary, target)
        } finally {
            temporary.delete()
        }

        LocalReaderSource(
            sourceId = sourceId,
            displayTitle = displayTitle,
            format = ReaderFormat.Epub,
            contentFingerprint = ContentFingerprint(
                originalFileHash = digest.digestToFingerprint(),
                parserVersion = READIUM_PARSER_VERSION,
                normalizationVersion = EPUB_NORMALIZATION_VERSION,
            ),
            workId = workId,
            volumeId = volumeId,
        )
    }

    fun downloadSinkFactory(): PublicationDownloadSinkFactory = PublicationDownloadSinkFactory { download ->
        withContext(Dispatchers.IO) {
            require(download.mimeType.lowercase() in EPUB_MIME_TYPES) { "Reader publication MIME type is invalid" }
            require(download.expectedSizeBytes in 1..MAX_PUBLICATION_BYTES) {
                "Reader publication declared size is invalid"
            }
            publicationRoot.mkdirs()
            require(publicationRoot.isDirectory) { "Reader publication root is unavailable" }
            val target = targetFile(download.sourceId)
            val temporary = File(publicationRoot, ".${target.name}.${System.nanoTime()}.download")
            DownloadSink(download, temporary, target)
        }
    }

    fun resolve(source: LocalReaderSource): File {
        require(source.format == ReaderFormat.Epub) { "Only EPUB sources are supported in R2" }
        val target = targetFile(source.sourceId)
        val rootPath = publicationRoot.canonicalFile.toPath()
        val targetPath = target.canonicalFile.toPath()
        require(targetPath.startsWith(rootPath)) { "Reader publication escaped the managed root" }
        require(target.isFile && !Files.isSymbolicLink(targetPath)) { "Reader publication is missing" }
        require(target.length() in 1..MAX_PUBLICATION_BYTES) { "Reader publication size is invalid" }
        return target
    }

    suspend fun resolveVerified(source: LocalReaderSource): File = withContext(Dispatchers.IO) {
        val target = resolve(source)
        val digest = MessageDigest.getInstance("SHA-256")
        target.inputStream().use { input ->
            val buffer = ByteArray(COPY_BUFFER_BYTES)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        require(digest.digestToFingerprint() == source.contentFingerprint.originalFileHash) {
            "Reader publication fingerprint does not match the launch contract"
        }
        target
    }

    suspend fun delete(sourceId: String): Unit = withContext(Dispatchers.IO) {
        require(sourceId.isNotBlank()) { "Reader source id is blank" }
        Files.deleteIfExists(targetFile(sourceId).toPath())
    }

    private fun targetFile(sourceId: String): File = File(publicationRoot, sha256(sourceId) + EPUB_SUFFIX)

    private fun atomicReplace(temporary: File, target: File) {
        try {
            Files.move(
                temporary.toPath(),
                target.toPath(),
                StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }

    private inner class DownloadSink(
        private val download: ReaderPublicationDownload,
        private val temporary: File,
        private val target: File,
    ) : PublicationDownloadSink {
        private val digest = MessageDigest.getInstance("SHA-256")
        private var output: FileOutputStream? = FileOutputStream(temporary)
        private var writtenBytes = 0L
        private var completed = false

        override suspend fun write(bytes: ByteArray, count: Int) = withContext(Dispatchers.IO) {
            check(!completed) { "Reader publication sink is closed" }
            require(count in 1..bytes.size) { "Reader publication chunk is invalid" }
            val nextSize = writtenBytes + count
            require(nextSize <= download.expectedSizeBytes) { "Reader publication exceeds declared size" }
            digest.update(bytes, 0, count)
            checkNotNull(output).write(bytes, 0, count)
            writtenBytes = nextSize
        }

        override suspend fun commit(): ReaderSource = withContext(Dispatchers.IO) {
            check(!completed) { "Reader publication sink is closed" }
            completed = true
            try {
                check(writtenBytes == download.expectedSizeBytes) { "Reader publication size does not match bootstrap" }
                checkNotNull(output).apply {
                    fd.sync()
                    close()
                }
                output = null
                val computedHash = digest.digestToFingerprint()
                download.expectedOriginalFileHash?.let { expectedHash ->
                    check(computedHash.equals(expectedHash, ignoreCase = true)) {
                        "Reader publication hash does not match bootstrap"
                    }
                }
                validateEpubArchive(temporary)
                atomicReplace(temporary, target)
                LocalReaderSource(
                    sourceId = download.sourceId,
                    displayTitle = download.displayTitle,
                    format = ReaderFormat.Epub,
                    contentFingerprint = ContentFingerprint(
                        computedHash,
                        READIUM_PARSER_VERSION,
                        EPUB_NORMALIZATION_VERSION,
                    ),
                    workId = download.workId,
                    volumeId = download.volumeId,
                )
            } finally {
                output?.close()
                output = null
                temporary.delete()
            }
        }

        override suspend fun abort(): Unit = withContext(Dispatchers.IO) {
            if (completed) return@withContext
            completed = true
            output?.close()
            output = null
            temporary.delete()
        }
    }

    private fun validateEpubArchive(file: File) {
        ZipFile(file).use { archive ->
            val mimeEntry = archive.getEntry("mimetype") ?: error("EPUB mimetype entry is missing")
            require(!mimeEntry.isDirectory && mimeEntry.size in 1..MAXIMUM_MIMETYPE_BYTES) {
                "EPUB mimetype entry is invalid"
            }
            val mimeValue = archive.getInputStream(mimeEntry).bufferedReader(Charsets.US_ASCII).use { it.readText() }
            require(mimeValue.trim() == EPUB_MIME_TYPE) { "EPUB mimetype entry is invalid" }
            require(archive.getEntry("META-INF/container.xml")?.isDirectory == false) {
                "EPUB container descriptor is missing"
            }
        }
    }

    companion object {
        const val READIUM_PARSER_VERSION = "readium-kotlin:3.3.0"
        const val EPUB_NORMALIZATION_VERSION = "epub-native-sanitized-v1"
        private const val PUBLICATION_DIRECTORY = "reader-publications"
        private const val EPUB_SUFFIX = ".epub"
        private const val COPY_BUFFER_BYTES = 64 * 1024
        private const val MAX_SOURCE_ID_LENGTH = 256
        private const val MAX_TITLE_LENGTH = 512
        private const val MAX_PUBLICATION_BYTES = 512L * 1024 * 1024
        private const val MAXIMUM_MIMETYPE_BYTES = 64L
        private const val EPUB_MIME_TYPE = "application/epub+zip"
        private val EPUB_MIME_TYPES = setOf(EPUB_MIME_TYPE, "application/octet-stream")
    }
}
