package com.ermao.library.features.reader.infrastructure

import android.content.Context
import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
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
import java.util.Locale
import java.util.zip.ZipFile
import com.ermao.library.mobi.infrastructure.MobiReadiumPublicationFactory
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
    ): LocalReaderSource = publishLocalPublication(
        sourceId = sourceId,
        displayTitle = displayTitle,
        input = input,
        sourceFormat = ReaderSourceFormat.Epub,
        publicationFingerprint = null,
        workId = workId,
        volumeId = volumeId,
    )

    suspend fun publishLocalPublication(
        sourceId: String,
        displayTitle: String,
        input: InputStream,
        sourceFormat: ReaderSourceFormat,
        publicationFingerprint: com.ermao.library.shared.modules.reader.PublicationFingerprint?,
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

        val target = targetFile(sourceId, sourceFormat)
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
            validatePublication(temporary, sourceFormat, publicationFingerprint)
            atomicReplace(temporary, target)
        } finally {
            temporary.delete()
        }

        LocalReaderSource(
            sourceId = sourceId,
            displayTitle = displayTitle,
            format = sourceFormat.readerFormat,
            contentFingerprint = ContentFingerprint(
                originalFileHash = digest.digestToFingerprint(),
                parserVersion = publicationFingerprint?.parser ?: sourceFormat.defaultParser,
                normalizationVersion = publicationFingerprint?.normalization ?: sourceFormat.defaultNormalization,
            ),
            workId = workId,
            volumeId = volumeId,
            sourceFormat = sourceFormat,
        )
    }

    fun downloadSinkFactory(): PublicationDownloadSinkFactory = PublicationDownloadSinkFactory { download ->
        withContext(Dispatchers.IO) {
            require(download.sourceFormat.acceptsMimeType(download.mimeType)) { "Reader publication MIME type is invalid" }
            require(download.expectedSizeBytes in 1..MAX_PUBLICATION_BYTES) {
                "Reader publication declared size is invalid"
            }
            publicationRoot.mkdirs()
            require(publicationRoot.isDirectory) { "Reader publication root is unavailable" }
            val target = targetFile(download.sourceId, download.sourceFormat)
            val temporary = File(publicationRoot, ".${target.name}.${System.nanoTime()}.download")
            DownloadSink(download, temporary, target)
        }
    }

    fun resolve(source: LocalReaderSource): File {
        require(source.format in SUPPORTED_LOCAL_FORMATS) { "Unsupported Reader source" }
        val sourceFormat = source.sourceFormat ?: when (source.format) {
            ReaderFormat.Epub -> ReaderSourceFormat.Epub
            else -> error("Reader source container format is missing")
        }
        val target = targetFile(source.sourceId, sourceFormat)
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
        ReaderSourceFormat.entries.forEach { Files.deleteIfExists(targetFile(sourceId, it).toPath()) }
    }

    private fun targetFile(sourceId: String, sourceFormat: ReaderSourceFormat): File =
        File(publicationRoot, sha256(sourceId) + "." + sourceFormat.wireValue)

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
                validatePublication(temporary, download.sourceFormat, download.publicationFingerprint)
                atomicReplace(temporary, target)
                LocalReaderSource(
                    sourceId = download.sourceId,
                    displayTitle = download.displayTitle,
                    format = download.sourceFormat.readerFormat,
                    contentFingerprint = ContentFingerprint(
                        computedHash,
                        download.publicationFingerprint.parser,
                        download.publicationFingerprint.normalization,
                    ),
                    workId = download.workId,
                    volumeId = download.volumeId,
                    sourceFormat = download.sourceFormat,
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

    private fun validatePublication(
        file: File,
        sourceFormat: ReaderSourceFormat,
        expected: com.ermao.library.shared.modules.reader.PublicationFingerprint?,
    ) {
        when (sourceFormat) {
            ReaderSourceFormat.Epub -> validateEpubArchive(file)
            ReaderSourceFormat.Txt -> validateText(file)
            ReaderSourceFormat.Cbz -> validateComicArchive(file)
            ReaderSourceFormat.Pdf -> validatePdf(file)
            ReaderSourceFormat.Mobi,
            ReaderSourceFormat.Azw,
            ReaderSourceFormat.Azw3,
            ReaderSourceFormat.Prc,
            -> MobiReadiumPublicationFactory().open(file).use { opened ->
                expected?.let {
                    require(("sha256:" + opened.originalFileHash).equals(it.originalFileHash, ignoreCase = true))
                    require(opened.parser == it.parser && opened.normalization == it.normalization) {
                        "MOBI parser identity does not match bootstrap"
                    }
                }
            }
        }
    }

    private fun validateText(file: File) {
        require(file.length() <= MAX_TEXT_BYTES) { "TXT publication exceeds the size limit" }
        StrictTxtDecoder.decode(file.readBytes())
    }

    private fun validateComicArchive(file: File) {
        ZipFile(file).use { archive ->
            val seen = mutableSetOf<String>()
            var imageCount = 0
            var expandedBytes = 0L
            val entries = archive.entries().asSequence().toList()
            require(entries.size in 1..MAX_COMIC_ENTRIES) { "CBZ entry count is invalid" }
            entries.forEach { entry ->
                val name = entry.name
                require(name.isNotBlank() && !name.startsWith('/') && '\\' !in name) {
                    "CBZ entry path is unsafe"
                }
                require(name.split('/').none { it.isBlank() || it == "." || it == ".." }) {
                    "CBZ entry path is unsafe"
                }
                require(seen.add(name.lowercase(Locale.ROOT))) { "CBZ contains duplicate entry names" }
                require(entry.method != java.util.zip.ZipEntry.STORED || entry.compressedSize == entry.size) {
                    "CBZ stored entry metadata is invalid"
                }
                if (!entry.isDirectory) {
                    require(entry.size in 0..MAX_COMIC_ENTRY_BYTES) { "CBZ entry exceeds the size limit" }
                    expandedBytes += entry.size
                    require(expandedBytes <= MAX_COMIC_EXPANDED_BYTES) { "CBZ expands beyond the size limit" }
                    if (name.substringAfterLast('.', "").lowercase(Locale.ROOT) in COMIC_IMAGE_EXTENSIONS) {
                        imageCount += 1
                    }
                }
            }
            require(imageCount > 0) { "CBZ has no supported image pages" }
        }
    }

    private fun validatePdf(file: File) {
        file.inputStream().use { input ->
            val header = ByteArray(PDF_HEADER.size)
            require(input.read(header) == header.size && header.contentEquals(PDF_HEADER)) {
                "PDF signature is invalid"
            }
        }
    }

    companion object {
        const val EPUB_PARSER_VERSION = "epub-package:1"
        const val EPUB_NORMALIZATION_VERSION = "shuku-epub-raw-v1"
        @Deprecated("Use EPUB_PARSER_VERSION")
        const val READIUM_PARSER_VERSION = EPUB_PARSER_VERSION
        private const val PUBLICATION_DIRECTORY = "reader-publications"
        private const val COPY_BUFFER_BYTES = 64 * 1024
        private const val MAX_SOURCE_ID_LENGTH = 256
        private const val MAX_TITLE_LENGTH = 512
        private const val MAX_PUBLICATION_BYTES = 512L * 1024 * 1024
        private const val MAXIMUM_MIMETYPE_BYTES = 64L
        private const val MAX_TEXT_BYTES = 64L * 1024 * 1024
        private const val MAX_COMIC_ENTRIES = 10_000
        private const val MAX_COMIC_ENTRY_BYTES = 128L * 1024 * 1024
        private const val MAX_COMIC_EXPANDED_BYTES = 2L * 1024 * 1024 * 1024
        private const val EPUB_MIME_TYPE = "application/epub+zip"
        private val PDF_HEADER = "%PDF-".toByteArray(Charsets.US_ASCII)
        private val COMIC_IMAGE_EXTENSIONS = setOf("jpg", "jpeg", "png", "gif", "webp")
        private val SUPPORTED_LOCAL_FORMATS = setOf(
            ReaderFormat.Epub,
            ReaderFormat.Mobi,
            ReaderFormat.Text,
            ReaderFormat.Comic,
            ReaderFormat.Pdf,
        )
    }
}

private val ReaderSourceFormat.defaultParser: String
    get() = when (this) {
        ReaderSourceFormat.Epub -> "epub-package:1"
        ReaderSourceFormat.Txt -> "shuku-txt-parser-v1"
        ReaderSourceFormat.Cbz -> "archive-images:natural-order-v1"
        ReaderSourceFormat.Pdf -> "pdf:source-v1"
        else -> "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add"
    }

private val ReaderSourceFormat.defaultNormalization: String
    get() = when (this) {
        ReaderSourceFormat.Epub -> "shuku-epub-raw-v1"
        ReaderSourceFormat.Txt -> "shuku-txt-publication-v1"
        ReaderSourceFormat.Cbz -> "shuku-comic-pages-v1"
        ReaderSourceFormat.Pdf -> "shuku-pdf-pages-v1"
        else -> "ermao-mobi-core-v1"
    }
