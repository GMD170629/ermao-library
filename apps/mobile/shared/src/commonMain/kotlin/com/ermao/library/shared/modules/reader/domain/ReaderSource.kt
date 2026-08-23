package com.ermao.library.shared.modules.reader.domain

/** Reader morphology exposed by the resource-first Reader bootstrap. */
enum class ReaderFormat(val wireValue: String) {
    Epub("epub"),
    Mobi("mobi"),
    Text("text"),
    Pdf("pdf"),
    Comic("comic"),
    Audio("audio"),
}

/** Concrete resource format. The server may expose a codec-specific audio format. */
enum class ReaderSourceFormat(
    val wireValue: String,
    val readerFormat: ReaderFormat,
    val fileKind: String,
    val allowedMimeTypes: Set<String>,
) {
    Epub("epub", ReaderFormat.Epub, "EPUB", setOf("application/epub+zip", "application/octet-stream")),
    Mobi("mobi", ReaderFormat.Mobi, "MOBI", setOf("application/x-mobipocket-ebook", "application/octet-stream")),
    Azw("azw", ReaderFormat.Mobi, "AZW", setOf("application/vnd.amazon.ebook", "application/x-mobipocket-ebook", "application/octet-stream")),
    Azw3("azw3", ReaderFormat.Mobi, "AZW3", setOf("application/vnd.amazon.ebook", "application/x-mobipocket-ebook", "application/octet-stream")),
    Prc("prc", ReaderFormat.Mobi, "PRC", setOf("application/x-mobipocket-ebook", "application/octet-stream")),
    Txt("txt", ReaderFormat.Text, "TXT", setOf("text/plain", "application/octet-stream")),
    Cbz("cbz", ReaderFormat.Comic, "CBZ", setOf("application/vnd.comicbook+zip", "application/x-cbz", "application/zip", "application/octet-stream")),
    Zip("zip", ReaderFormat.Comic, "ZIP", setOf("application/zip", "application/octet-stream")),
    Cbr("cbr", ReaderFormat.Comic, "CBR", setOf("application/vnd.comicbook-rar", "application/x-cbr", "application/vnd.rar", "application/octet-stream")),
    Rar("rar", ReaderFormat.Comic, "RAR", setOf("application/vnd.rar", "application/vnd.comicbook-rar", "application/octet-stream")),
    Pdf("pdf", ReaderFormat.Pdf, "PDF", setOf("application/pdf", "application/octet-stream")),
    Audio("audio", ReaderFormat.Audio, "AUDIO", setOf("audio/mpeg", "audio/mp4", "audio/ogg", "audio/flac", "audio/wav", "application/octet-stream")),
    Audiobook("audiobook", ReaderFormat.Audio, "AUDIO", setOf("audio/mpeg", "audio/mp4", "audio/ogg", "audio/flac", "audio/wav", "application/octet-stream")),
    M4b("m4b", ReaderFormat.Audio, "AUDIO", setOf("audio/mp4", "audio/x-m4b", "application/octet-stream")),
    M4a("m4a", ReaderFormat.Audio, "AUDIO", setOf("audio/mp4", "audio/x-m4a", "application/octet-stream")),
    Mp3("mp3", ReaderFormat.Audio, "AUDIO", setOf("audio/mpeg", "audio/mp3", "application/octet-stream")),
    Flac("flac", ReaderFormat.Audio, "AUDIO", setOf("audio/flac", "application/octet-stream")),
    Ogg("ogg", ReaderFormat.Audio, "AUDIO", setOf("audio/ogg", "application/ogg", "application/octet-stream")),
    Opus("opus", ReaderFormat.Audio, "AUDIO", setOf("audio/opus", "application/octet-stream")),
    Wav("wav", ReaderFormat.Audio, "AUDIO", setOf("audio/wav", "audio/x-wav", "application/octet-stream")),
    ;

    fun acceptsMimeType(value: String): Boolean {
        val normalized = value.trim().lowercase().substringBefore(';')
        return normalized in allowedMimeTypes || readerFormat == ReaderFormat.Audio && normalized.startsWith("audio/")
    }

    val isComic: Boolean
        get() = readerFormat == ReaderFormat.Comic

    companion object {
        fun fromWireValue(value: String?): ReaderSourceFormat? = entries.firstOrNull {
            it.wireValue == value?.trim()?.lowercase()
        }
    }
}

sealed interface ReaderSource {
    /** Resource identity; this is the Reader/progress owner and never a file identity. */
    val resourceId: String
    val displayTitle: String
    val format: ReaderFormat
    val sourceFormat: ReaderSourceFormat?
        get() = null
    val bookId: String?
    val assetId: String?
}

data class LocalReaderSource(
    override val resourceId: String,
    override val displayTitle: String,
    override val format: ReaderFormat,
    override val bookId: String? = null,
    override val assetId: String? = null,
    override val sourceFormat: ReaderSourceFormat? = null,
) : ReaderSource {
    init {
        require(resourceId.isNotBlank()) { "Reader resource id is blank" }
        require(displayTitle.isNotBlank()) { "Reader display title is blank" }
        require(bookId == null || bookId.isNotBlank()) { "Book id is blank" }
        require(assetId == null || assetId.isNotBlank()) { "Asset id is blank" }
        require(sourceFormat == null || sourceFormat.readerFormat == format) {
            "Reader source format does not match its reader format"
        }
    }
}

/** Online PDF access. Cached chunks are private session data, never a completed offline artifact. */
data class RemoteByteRangeReaderSource(
    override val resourceId: String,
    override val displayTitle: String,
    override val bookId: String,
    override val assetId: String,
    val namespace: ReaderSyncNamespace,
    val apiPath: String,
    val expectedSizeBytes: Long,
) : ReaderSource {
    override val format: ReaderFormat = ReaderFormat.Pdf
    override val sourceFormat: ReaderSourceFormat = ReaderSourceFormat.Pdf

    init {
        require(resourceId.isNotBlank()) { "Remote PDF resource id is blank" }
        require(displayTitle.isNotBlank()) { "Remote PDF title is blank" }
        require(bookId.isNotBlank()) { "Remote PDF book id is blank" }
        require(assetId.isNotBlank()) { "Remote PDF asset id is blank" }
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

/** Online comic access backed by canonical Reader resource page endpoints. */
data class RemoteComicReaderSource(
    override val resourceId: String,
    override val displayTitle: String,
    override val bookId: String,
    override val assetId: String,
    val namespace: ReaderSyncNamespace,
    override val sourceFormat: ReaderSourceFormat,
    val manifestApiPath: String,
    val pageApiPathTemplate: String,
    val pages: List<RemoteComicPage>,
) : ReaderSource {
    override val format: ReaderFormat = ReaderFormat.Comic

    init {
        require(resourceId.isNotBlank() && bookId.isNotBlank() && assetId.isNotBlank())
        require(displayTitle.isNotBlank())
        require(sourceFormat.isComic)
        require(manifestApiPath.startsWith("/api/") && '#' !in manifestApiPath)
        require(pageApiPathTemplate.startsWith("/api/") && "{pageIndex}" in pageApiPathTemplate)
        require(pages.isNotEmpty())
        require(pages.map(RemoteComicPage::pageIndex) == pages.indices.toList())
    }
}
