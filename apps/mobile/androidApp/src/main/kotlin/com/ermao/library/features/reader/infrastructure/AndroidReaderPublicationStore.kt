package com.ermao.library.features.reader.infrastructure

import android.content.Context
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.LocalReaderSourceResolver
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderSource
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.PublicationDownloadSink
import com.ermao.library.shared.modules.reader.PublicationDownloadSinkFactory
import com.ermao.library.shared.modules.reader.ReaderPublicationDownload
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.Locale
import java.util.zip.ZipFile
import com.ermao.library.mobi.infrastructure.MobiReadiumPublicationFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal class AndroidReaderPublicationStore(
    context: Context,
    namespace: ReaderSyncNamespace? = null,
) {
    private val publicationRoot = namespace?.let { value ->
        File(
            File(File(context.filesDir, PUBLICATION_DIRECTORY), sha256(readerAccountStorageKey(value))),
            sha256(value.stableKey),
        )
    } ?: File(File(context.filesDir, PUBLICATION_DIRECTORY), "unscoped")

    init {
        removeLegacyHashedPublicationArtifacts(publicationRoot)
    }

    suspend fun publishLocalEpub(
        resourceId: String,
        displayTitle: String,
        input: InputStream,
        bookId: String? = null,
        assetId: String? = null,
    ): LocalReaderSource = publishLocalPublication(
        resourceId = resourceId,
        displayTitle = displayTitle,
        input = input,
        sourceFormat = ReaderSourceFormat.Epub,
        bookId = bookId,
        assetId = assetId,
    )

    suspend fun publishLocalPublication(
        resourceId: String,
        displayTitle: String,
        input: InputStream,
        sourceFormat: ReaderSourceFormat,
        bookId: String? = null,
        assetId: String? = null,
    ): LocalReaderSource = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank() && resourceId.length <= MAX_RESOURCE_ID_LENGTH) {
            "Reader resource id is invalid"
        }
        require(displayTitle.isNotBlank() && displayTitle.length <= MAX_TITLE_LENGTH) {
            "Reader title is invalid"
        }
        publicationRoot.mkdirs()
        require(publicationRoot.isDirectory) { "Reader publication root is unavailable" }

        val target = targetFile(resourceId, assetId, sourceFormat)
        val temporary = File(publicationRoot, ".${target.name}.${System.nanoTime()}.tmp")
        var written = 0L
        try {
            FileOutputStream(temporary).use { output ->
                val buffer = ByteArray(COPY_BUFFER_BYTES)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    written += count
                    require(written <= MAX_PUBLICATION_BYTES) { "Reader publication exceeds the size limit" }
                    output.write(buffer, 0, count)
                }
                output.fd.sync()
            }
            require(written > 0) { "Reader publication is empty" }
            validatePublication(temporary, sourceFormat)
            atomicReplace(temporary, target)
        } finally {
            temporary.delete()
        }

        LocalReaderSource(
            resourceId = resourceId,
            displayTitle = displayTitle,
            format = sourceFormat.readerFormat,
            bookId = bookId,
            assetId = assetId,
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
            val target = targetFile(download.resourceId, download.assetId, download.sourceFormat)
            val temporary = File(publicationRoot, ".${target.name}.${System.nanoTime()}.download")
            DownloadSink(download, temporary, target)
        }
    }

    fun localSourceResolver(): LocalReaderSourceResolver = LocalReaderSourceResolver { download ->
        val source = LocalReaderSource(
            resourceId = download.resourceId,
            displayTitle = download.displayTitle,
            format = download.sourceFormat.readerFormat,
            bookId = download.bookId,
            assetId = download.assetId,
            sourceFormat = download.sourceFormat,
        )
        runCatching {
            resolve(source)
            source
        }.getOrNull()
    }

    fun resolve(source: LocalReaderSource): File {
        require(source.format in SUPPORTED_LOCAL_FORMATS) { "Unsupported Reader source" }
        val sourceFormat = source.sourceFormat ?: when (source.format) {
            ReaderFormat.Epub -> ReaderSourceFormat.Epub
            else -> error("Reader source container format is missing")
        }
        val target = targetFile(source.resourceId, source.assetId, sourceFormat)
        val rootPath = publicationRoot.canonicalFile.toPath()
        val targetPath = target.canonicalFile.toPath()
        require(targetPath.startsWith(rootPath)) { "Reader publication escaped the managed root" }
        require(target.isFile && !Files.isSymbolicLink(targetPath)) { "Reader publication is missing" }
        require(target.length() in 1..MAX_PUBLICATION_BYTES) { "Reader publication size is invalid" }
        return target
    }

    suspend fun resolveVerified(source: LocalReaderSource): File = withContext(Dispatchers.IO) {
        val target = resolve(source)
        val sourceFormat = source.sourceFormat ?: ReaderSourceFormat.Epub
        validatePublication(target, sourceFormat)
        target
    }

    suspend fun delete(resourceId: String, assetId: String? = null): Unit = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank()) { "Reader resource id is blank" }
        ReaderSourceFormat.entries.forEach {
            Files.deleteIfExists(targetFile(resourceId, assetId, it).toPath())
        }
    }

    private fun targetFile(resourceId: String, assetId: String?, sourceFormat: ReaderSourceFormat): File =
        File(publicationRoot, sha256("$resourceId\u0000${assetId.orEmpty()}") + "." + sourceFormat.wireValue)

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
        private var output: FileOutputStream? = FileOutputStream(temporary)
        private var writtenBytes = 0L
        private var completed = false

        override suspend fun write(bytes: ByteArray, count: Int) = withContext(Dispatchers.IO) {
            check(!completed) { "Reader publication sink is closed" }
            require(count in 1..bytes.size) { "Reader publication chunk is invalid" }
            val nextSize = writtenBytes + count
            require(nextSize <= MAX_PUBLICATION_BYTES) { "Reader publication exceeds the size limit" }
            checkNotNull(output).write(bytes, 0, count)
            writtenBytes = nextSize
        }

        override suspend fun commit(): ReaderSource = withContext(Dispatchers.IO) {
            check(!completed) { "Reader publication sink is closed" }
            completed = true
            try {
                checkNotNull(output).apply {
                    fd.sync()
                    close()
                }
                output = null
                require(writtenBytes == download.expectedSizeBytes) {
                    "Reader publication length does not match the launch contract"
                }
                validatePublication(temporary, download.sourceFormat)
                atomicReplace(temporary, target)
                LocalReaderSource(
                    resourceId = download.resourceId,
                    displayTitle = download.displayTitle,
                    format = download.sourceFormat.readerFormat,
                    bookId = download.bookId,
                    assetId = download.assetId,
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
    ) {
        when (sourceFormat) {
            ReaderSourceFormat.Epub -> validateEpubArchive(file)
            ReaderSourceFormat.Txt -> validateText(file)
            ReaderSourceFormat.Cbz,
            ReaderSourceFormat.Zip,
            -> validateComicArchive(file)
            ReaderSourceFormat.Cbr,
            ReaderSourceFormat.Rar,
            -> throw IllegalArgumentException("RAR comic archives are available through server page streaming only")
            ReaderSourceFormat.Pdf -> validatePdf(file)
            ReaderSourceFormat.Mobi,
            ReaderSourceFormat.Azw,
            ReaderSourceFormat.Azw3,
            ReaderSourceFormat.Prc,
            -> MobiReadiumPublicationFactory().open(file).close()
            ReaderSourceFormat.Audio,
            ReaderSourceFormat.Audiobook,
            ReaderSourceFormat.M4b,
            ReaderSourceFormat.M4a,
            ReaderSourceFormat.Mp3,
            ReaderSourceFormat.Flac,
            ReaderSourceFormat.Ogg,
            ReaderSourceFormat.Opus,
            ReaderSourceFormat.Wav,
            -> throw IllegalArgumentException("Audio publications are opened by the native audio reader")
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
                require(isSafeComicArchiveEntryPath(name, entry.isDirectory)) { "CBZ entry path is unsafe" }
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
        const val EPUB_NORMALIZATION_VERSION = "shuku-epub-locator-dom-v2"
        @Deprecated("Use EPUB_PARSER_VERSION")
        const val READIUM_PARSER_VERSION = EPUB_PARSER_VERSION
        private const val PUBLICATION_DIRECTORY = "reader-publications-v3"
        private const val COPY_BUFFER_BYTES = 64 * 1024
        private const val MAX_RESOURCE_ID_LENGTH = 256
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

        internal fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) {
            val directory = File(
                File(context.filesDir, PUBLICATION_DIRECTORY),
                sha256(readerAccountStorageKey(namespace)),
            )
            if (directory.exists()) check(directory.deleteRecursively()) { "Unable to clear Reader publications" }
        }
    }
}

internal fun removeLegacyHashedPublicationArtifacts(publicationRoot: File) {
    publicationRoot.listFiles { file -> file.isFile && file.name.endsWith(".sha256") }
        ?.forEach { sidecar ->
            File(sidecar.parentFile, sidecar.name.removeSuffix(".sha256")).delete()
            sidecar.delete()
        }
}

internal fun isSafeComicArchiveEntryPath(name: String, isDirectory: Boolean): Boolean {
    if (name.isBlank() || name.startsWith('/') || '\\' in name) return false
    val path = if (isDirectory) name.removeSuffix("/") else name
    return path.isNotBlank() && path.split('/').none { it.isBlank() || it == "." || it == ".." }
}
