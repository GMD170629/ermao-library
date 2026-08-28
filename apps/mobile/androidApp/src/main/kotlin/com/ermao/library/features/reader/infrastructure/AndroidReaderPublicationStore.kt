package com.ermao.library.features.reader.infrastructure

import android.content.Context
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.zip.ZipFile
import com.ermao.library.mobi.infrastructure.MobiReadiumPublicationFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal class AndroidReaderPublicationStore(
    context: Context,
    namespace: ReaderSyncNamespace? = null,
    private val completedPublication: AndroidCompletedPublication? = null,
) {
    private val obsoleteRangeCache = File(context.cacheDir, "reader/pdf-range-v3")
    private val cacheRoot = context.cacheDir.canonicalFile
    private val publicationRoot = namespace?.let { value ->
        File(
            File(File(context.filesDir, PUBLICATION_DIRECTORY), sha256(readerAccountStorageKey(value))),
            sha256(value.stableKey),
        )
    } ?: File(File(context.filesDir, PUBLICATION_DIRECTORY), "unscoped")

    init {
        removeLegacyHashedPublicationArtifacts(publicationRoot)
    }

    /** Removes only a server/asset-attributed automatic replica, never Downloads or local imports. */
    suspend fun removeAutomaticReplica(resourceId: String, assetId: String) = withContext(Dispatchers.IO) {
        removeAutomaticReaderReplica(publicationRoot, resourceId, assetId)
        if (obsoleteRangeCache.exists()) {
            require(obsoleteRangeCache.canonicalFile.toPath().startsWith(cacheRoot.toPath()))
            Files.walkFileTree(obsoleteRangeCache.toPath(), object : java.nio.file.SimpleFileVisitor<java.nio.file.Path>() {
                override fun visitFile(path: java.nio.file.Path, attributes: java.nio.file.attribute.BasicFileAttributes): java.nio.file.FileVisitResult {
                    Files.delete(path)
                    return java.nio.file.FileVisitResult.CONTINUE
                }
                override fun postVisitDirectory(path: java.nio.file.Path, error: java.io.IOException?): java.nio.file.FileVisitResult {
                    if (error != null) throw error
                    Files.delete(path)
                    return java.nio.file.FileVisitResult.CONTINUE
                }
            })
        }
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

    fun resolve(source: LocalReaderSource): File {
        completedPublication?.takeIf { it.source == source }?.let { return it.file }
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
            ReaderSourceFormat.ImageDir,
            ReaderSourceFormat.AudiobookDir,
            -> throw IllegalArgumentException("Reader source format is not a local publication")
            ReaderSourceFormat.Fb2 -> Fb2ReadiumPublicationFactory().open(file, file.nameWithoutExtension).close()
            ReaderSourceFormat.Txt -> validateText(file)
            ReaderSourceFormat.Cbz,
            ReaderSourceFormat.Zip,
            ReaderSourceFormat.Cbr,
            ReaderSourceFormat.Rar,
            -> validateComicArchive(file)
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
        CbzReadiumPublicationFactory().indexPages(file)
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
        private const val PUBLICATION_DIRECTORY = "reader-publications-v3"
        private const val COPY_BUFFER_BYTES = 64 * 1024
        private const val MAX_RESOURCE_ID_LENGTH = 256
        private const val MAX_TITLE_LENGTH = 512
        private const val MAX_PUBLICATION_BYTES = 512L * 1024 * 1024
        private const val MAXIMUM_MIMETYPE_BYTES = 64L
        private const val MAX_TEXT_BYTES = 64L * 1024 * 1024
        private const val EPUB_MIME_TYPE = "application/epub+zip"
        private val PDF_HEADER = "%PDF-".toByteArray(Charsets.US_ASCII)
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

internal data class AndroidCompletedPublication(val source: LocalReaderSource, val file: File)

internal fun removeAutomaticReaderReplica(root: File, resourceId: String, assetId: String) {
    require(resourceId.isNotBlank() && assetId.isNotBlank())
    if (!root.exists() || root.name == "unscoped") return
    require(!Files.isSymbolicLink(root.toPath()))
    val stem = sha256("$resourceId\u0000$assetId")
    val targets = ReaderSourceFormat.entries.map { "$stem.${it.wireValue}" }.toSet()
    root.listFiles()?.forEach { file ->
        val isReplica = file.name in targets
        val isPartial = file.name.endsWith(".download") && targets.any { file.name.startsWith(".$it.") }
        if (isReplica || isPartial) {
            require(file.canonicalFile.parentFile == root.canonicalFile && !Files.isSymbolicLink(file.toPath()))
            Files.deleteIfExists(file.toPath())
        }
    }
}
