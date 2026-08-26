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
private val READER_AUDIO_MIME_TYPES = setOf(
    "audio/aac",
    "audio/ac3",
    "audio/aiff",
    "audio/amr",
    "audio/basic",
    "audio/eac3",
    "audio/flac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/vnd.dts",
    "audio/vnd.rn-realaudio",
    "audio/wav",
    "audio/webm",
    "audio/x-matroska",
    "audio/x-ms-wma",
    "audio/x-adx",
    "audio/x-ape",
    "audio/x-aptx",
    "audio/x-aptxhd",
    "audio/x-caf",
    "audio/x-dff",
    "audio/x-dsf",
    "audio/x-g722",
    "audio/x-g726",
    "audio/x-gsm",
    "audio/x-lbc",
    "audio/x-mlp",
    "audio/x-mpc",
    "audio/x-oma",
    "audio/x-qcp",
    "audio/x-shn",
    "audio/x-sph",
    "audio/x-tak",
    "audio/x-thd",
    "audio/x-tta",
    "audio/x-voc",
    "audio/x-wv",
    "audio/x-xma",
)

enum class ReaderSourceFormat(
    val wireValue: String,
    val readerFormat: ReaderFormat,
    val fileKind: String,
    val allowedMimeTypes: Set<String>,
) {
    Epub("epub", ReaderFormat.Epub, "EPUB", setOf("application/epub+zip")),
    Mobi("mobi", ReaderFormat.Mobi, "MOBI", setOf("application/x-mobipocket-ebook")),
    Azw("azw", ReaderFormat.Mobi, "AZW", setOf("application/vnd.amazon.ebook", "application/x-mobipocket-ebook")),
    Azw3("azw3", ReaderFormat.Mobi, "AZW3", setOf("application/vnd.amazon.ebook", "application/x-mobipocket-ebook")),
    Prc("prc", ReaderFormat.Mobi, "PRC", setOf("application/x-mobipocket-ebook")),
    Txt("txt", ReaderFormat.Text, "TXT", setOf("text/plain")),
    Fb2("fb2", ReaderFormat.Epub, "FB2", setOf("application/x-fictionbook+xml")),
    Cbz("cbz", ReaderFormat.Comic, "CBZ", setOf("application/vnd.comicbook+zip", "application/x-cbz", "application/zip")),
    Zip("zip", ReaderFormat.Comic, "ZIP", setOf("application/zip")),
    Cbr("cbr", ReaderFormat.Comic, "CBR", setOf("application/vnd.comicbook-rar", "application/x-cbr", "application/vnd.rar")),
    Rar("rar", ReaderFormat.Comic, "RAR", setOf("application/vnd.rar", "application/vnd.comicbook-rar")),
    ImageDir("image_dir", ReaderFormat.Comic, "IMAGE_DIR", setOf("image/jpeg", "image/png", "image/gif", "image/webp")),
    Pdf("pdf", ReaderFormat.Pdf, "PDF", setOf("application/pdf")),
    Audio("audio", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    Audiobook("audiobook", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    AudiobookDir("audiobook_dir", ReaderFormat.Audio, "AUDIOBOOK_DIR", READER_AUDIO_MIME_TYPES),
    M4b("m4b", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    M4a("m4a", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    Mp3("mp3", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    Flac("flac", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    Ogg("ogg", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    Opus("opus", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    Wav("wav", ReaderFormat.Audio, "AUDIO", READER_AUDIO_MIME_TYPES),
    ;

    fun acceptsMimeType(value: String): Boolean {
        val normalized = value.trim().lowercase().substringBefore(';')
        return normalized in allowedMimeTypes
    }

    val isComic: Boolean
        get() = readerFormat == ReaderFormat.Comic

    companion object {
        /**
         * The backend derives these values from its supported audio extension table. Keep this
         * finite: accepting every wildcard audio response would allow a server-side MIME typo to
         * cross the download/reader boundary.
         */
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
    override val assetId: String?,
    val namespace: ReaderSyncNamespace,
    override val sourceFormat: ReaderSourceFormat,
    val manifestApiPath: String,
    val pageApiPathTemplate: String,
    val pages: List<RemoteComicPage>,
) : ReaderSource {
    override val format: ReaderFormat = ReaderFormat.Comic

    init {
        require(resourceId.isNotBlank() && bookId.isNotBlank())
        require(displayTitle.isNotBlank())
        require(sourceFormat.isComic)
        require(sourceFormat == ReaderSourceFormat.ImageDir || !assetId.isNullOrBlank())
        require(sourceFormat != ReaderSourceFormat.ImageDir || assetId == null)
        require(manifestApiPath.startsWith("/api/") && '#' !in manifestApiPath)
        require(pageApiPathTemplate.startsWith("/api/") && "{pageIndex}" in pageApiPathTemplate)
        require(pages.isNotEmpty())
        require(pages.map(RemoteComicPage::pageIndex) == pages.indices.toList())
    }
}
