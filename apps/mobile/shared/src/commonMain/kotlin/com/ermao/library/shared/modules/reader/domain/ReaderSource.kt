package com.ermao.library.shared.modules.reader.domain

enum class ReaderFormat(val wireValue: String) {
    Epub("epub"),
    Mobi("mobi"),
    Text("text"),
    Pdf("pdf"),
    Comic("comic"),
    Audio("audio"),
}

enum class ReaderSourceFormat(
    val wireValue: String,
    val readerFormat: ReaderFormat,
    val fileKind: String,
    val allowedMimeTypes: Set<String>,
) {
    Epub(
        wireValue = "epub",
        readerFormat = ReaderFormat.Epub,
        fileKind = "EPUB",
        allowedMimeTypes = setOf("application/epub+zip", "application/octet-stream"),
    ),
    Mobi(
        wireValue = "mobi",
        readerFormat = ReaderFormat.Mobi,
        fileKind = "MOBI",
        allowedMimeTypes = setOf("application/x-mobipocket-ebook", "application/octet-stream"),
    ),
    Azw(
        wireValue = "azw",
        readerFormat = ReaderFormat.Mobi,
        fileKind = "AZW",
        allowedMimeTypes = setOf(
            "application/vnd.amazon.ebook",
            "application/x-mobipocket-ebook",
            "application/octet-stream",
        ),
    ),
    Azw3(
        wireValue = "azw3",
        readerFormat = ReaderFormat.Mobi,
        fileKind = "AZW3",
        allowedMimeTypes = setOf(
            "application/vnd.amazon.ebook",
            "application/x-mobipocket-ebook",
            "application/octet-stream",
        ),
    ),
    Prc(
        wireValue = "prc",
        readerFormat = ReaderFormat.Mobi,
        fileKind = "PRC",
        allowedMimeTypes = setOf("application/x-mobipocket-ebook", "application/octet-stream"),
    ),
    Txt(
        wireValue = "txt",
        readerFormat = ReaderFormat.Text,
        fileKind = "TXT",
        allowedMimeTypes = setOf("text/plain", "application/octet-stream"),
    ),
    Cbz(
        wireValue = "cbz",
        readerFormat = ReaderFormat.Comic,
        fileKind = "CBZ",
        allowedMimeTypes = setOf(
            "application/vnd.comicbook+zip",
            "application/x-cbz",
            "application/zip",
            "application/octet-stream",
        ),
    ),
    Zip(
        wireValue = "zip",
        readerFormat = ReaderFormat.Comic,
        fileKind = "ZIP",
        allowedMimeTypes = setOf("application/zip", "application/octet-stream"),
    ),
    Cbr(
        wireValue = "cbr",
        readerFormat = ReaderFormat.Comic,
        fileKind = "CBR",
        allowedMimeTypes = setOf(
            "application/vnd.comicbook-rar",
            "application/x-cbr",
            "application/vnd.rar",
            "application/octet-stream",
        ),
    ),
    Rar(
        wireValue = "rar",
        readerFormat = ReaderFormat.Comic,
        fileKind = "RAR",
        allowedMimeTypes = setOf(
            "application/vnd.rar",
            "application/vnd.comicbook-rar",
            "application/octet-stream",
        ),
    ),
    Pdf(
        wireValue = "pdf",
        readerFormat = ReaderFormat.Pdf,
        fileKind = "PDF",
        allowedMimeTypes = setOf("application/pdf", "application/octet-stream"),
    ),
    ;

    fun acceptsMimeType(value: String): Boolean = value.trim().lowercase() in allowedMimeTypes

    val isComic: Boolean
        get() = readerFormat == ReaderFormat.Comic

    companion object {
        fun fromWireValue(value: String?): ReaderSourceFormat? = entries.firstOrNull {
            it.wireValue == value?.trim()?.lowercase()
        }
    }
}

sealed interface ReaderSource {
    val sourceId: String
    val displayTitle: String
    val format: ReaderFormat
    /** Exact container format when the source belongs to the supported native reflowable family. */
    val sourceFormat: ReaderSourceFormat?
        get() = null
    val workId: String?
    val volumeId: String?
}

data class LocalReaderSource(
    override val sourceId: String,
    override val displayTitle: String,
    override val format: ReaderFormat,
    override val workId: String? = null,
    override val volumeId: String? = null,
    override val sourceFormat: ReaderSourceFormat? = null,
) : ReaderSource {
    init {
        require(sourceId.isNotBlank()) { "Reader source id is blank" }
        require(displayTitle.isNotBlank()) { "Reader display title is blank" }
        require(workId == null || workId.isNotBlank()) { "Work id is blank" }
        require(volumeId == null || volumeId.isNotBlank()) { "Volume id is blank" }
        require(sourceFormat == null || sourceFormat.readerFormat == format) {
            "Reader source format does not match its reader format"
        }
    }
}

/** Online PDF access. Cached chunks are private session data, never a completed offline artifact. */
data class RemoteByteRangeReaderSource(
    override val sourceId: String,
    override val displayTitle: String,
    override val workId: String,
    override val volumeId: String,
    val namespace: ReaderSyncNamespace,
    val apiPath: String,
    val expectedSizeBytes: Long,
) : ReaderSource {
    override val format: ReaderFormat = ReaderFormat.Pdf
    override val sourceFormat: ReaderSourceFormat = ReaderSourceFormat.Pdf

    init {
        require(sourceId.isNotBlank() && sourceId == volumeId) { "Remote PDF source id is invalid" }
        require(displayTitle.isNotBlank()) { "Remote PDF title is blank" }
        require(workId.isNotBlank()) { "Remote PDF work id is blank" }
        require(apiPath.startsWith("/api/") && '#' !in apiPath) { "Remote PDF path is invalid" }
        require(expectedSizeBytes > 0) { "Remote PDF size is invalid" }
        require(namespace.serverIdentity.isNotBlank() && namespace.userId.isNotBlank())
    }

}

data class RemoteComicPage(
    val pageIndex: Int,
    val resourceHref: String,
    val mediaType: String,
    val width: Int?,
    val height: Int?,
) {
    init {
        require(pageIndex >= 0)
        require(resourceHref == "pages/$pageIndex")
        require(mediaType.startsWith("image/"))
        require(width == null || width > 0)
        require(height == null || height > 0)
    }
}

/** Online comic access backed by canonical Reader V4 page resources. */
data class RemoteComicReaderSource(
    override val sourceId: String,
    override val displayTitle: String,
    override val workId: String,
    override val volumeId: String,
    val namespace: ReaderSyncNamespace,
    override val sourceFormat: ReaderSourceFormat,
    val manifestApiPath: String,
    val pageApiPathTemplate: String,
    val pages: List<RemoteComicPage>,
) : ReaderSource {
    override val format: ReaderFormat = ReaderFormat.Comic

    init {
        require(sourceId == volumeId && sourceId.isNotBlank())
        require(displayTitle.isNotBlank() && workId.isNotBlank())
        require(sourceFormat.isComic)
        require(manifestApiPath.startsWith("/api/") && '#' !in manifestApiPath)
        require(pageApiPathTemplate.startsWith("/api/") && "{pageIndex}" in pageApiPathTemplate)
        require(pages.isNotEmpty())
        require(pages.map(RemoteComicPage::pageIndex) == pages.indices.toList())
    }
}
