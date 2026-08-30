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

enum class ReaderSourceFormat(
    val wireValue: String,
    val readerFormat: ReaderFormat,
    private val policyFormat: ReaderSafetyFormat,
    private val codecExtension: String? = null,
) {
    Epub("epub", ReaderFormat.Epub, ReaderSafetyFormat.EPUB),
    Mobi("mobi", ReaderFormat.Mobi, ReaderSafetyFormat.MOBI),
    Azw("azw", ReaderFormat.Mobi, ReaderSafetyFormat.AZW),
    Azw3("azw3", ReaderFormat.Mobi, ReaderSafetyFormat.AZW3),
    Prc("prc", ReaderFormat.Mobi, ReaderSafetyFormat.PRC),
    Txt("txt", ReaderFormat.Text, ReaderSafetyFormat.TXT),
    Fb2("fb2", ReaderFormat.Epub, ReaderSafetyFormat.FB2),
    Cbz("cbz", ReaderFormat.Comic, ReaderSafetyFormat.CBZ),
    Zip("zip", ReaderFormat.Comic, ReaderSafetyFormat.ZIP),
    Cbr("cbr", ReaderFormat.Comic, ReaderSafetyFormat.CBR),
    Rar("rar", ReaderFormat.Comic, ReaderSafetyFormat.RAR),
    ImageDir("image_dir", ReaderFormat.Comic, ReaderSafetyFormat.IMAGE_DIR),
    Pdf("pdf", ReaderFormat.Pdf, ReaderSafetyFormat.PDF),
    Audio("audio", ReaderFormat.Audio, ReaderSafetyFormat.AUDIO),
    Audiobook("audiobook", ReaderFormat.Audio, ReaderSafetyFormat.AUDIOBOOK),
    AudiobookDir("audiobook_dir", ReaderFormat.Audio, ReaderSafetyFormat.AUDIOBOOK_DIR),
    M4b("m4b", ReaderFormat.Audio, ReaderSafetyFormat.M4B),
    M4a("m4a", ReaderFormat.Audio, ReaderSafetyFormat.M4A),
    Mp3("mp3", ReaderFormat.Audio, ReaderSafetyFormat.MP3),
    Flac("flac", ReaderFormat.Audio, ReaderSafetyFormat.AUDIO, ".flac"),
    Ogg("ogg", ReaderFormat.Audio, ReaderSafetyFormat.AUDIO, ".ogg"),
    Opus("opus", ReaderFormat.Audio, ReaderSafetyFormat.AUDIO, ".opus"),
    Wav("wav", ReaderFormat.Audio, ReaderSafetyFormat.AUDIO, ".wav"),
    ;

    val fileKind: String
        get() = policyFormat.name

    private val allowedMimeTypes: Set<String>
        get() {
            if (policyFormat == ReaderSafetyFormat.IMAGE_DIR) {
                return ReaderSafetyPolicy.comicProfile.allowedPageMimeTypes.toSet()
            }
            val formatPolicy = ReaderSafetyPolicy.formats.getValue(policyFormat)
            if (formatPolicy.acceptedMimeTypes.isNotEmpty()) {
                return formatPolicy.acceptedMimeTypes.toSet()
            }
            if (readerFormat != ReaderFormat.Audio) return emptySet()
            val exactExtension = codecExtension ?: formatPolicy.extension
            return if (exactExtension == null) {
                ReaderSafetyPolicy.audioProfile.containerMimeTypes.values.toSet()
            } else {
                setOfNotNull(ReaderSafetyPolicy.audioProfile.containerMimeTypes[exactExtension])
            }
        }

    fun acceptsMimeType(value: String): Boolean {
        val normalized = value.trim().lowercase().substringBefore(';')
        return normalized in allowedMimeTypes
    }

    val isComic: Boolean
        get() = ReaderSafetyPolicy.formats.getValue(policyFormat).morphology ==
            ReaderSafetyMorphology.COMIC

    val isReflowable: Boolean
        get() = ReaderSafetyPolicy.formats.getValue(policyFormat).morphology ==
            ReaderSafetyMorphology.REFLOWABLE

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

/** How the first-party Reader obtains publication bytes for a supported resource. */
enum class ReaderDeliveryMode {
    DownloadOriginal,
    Stream,
    Unsupported,
}

/** Native entry support has one authoritative format and delivery inventory. */
object ReaderFormatSupport {
    fun canReadOriginal(readerType: String, format: String): Boolean {
        val policy = ReaderSafetyPolicy.formatPolicy(format) ?: return false
        if (policy.morphology == ReaderSafetyMorphology.AUDIO) return false
        return readerType.trim().equals(policy.morphology.readerTypeWire, ignoreCase = true)
    }

    fun deliveryMode(readerType: String, format: String): ReaderDeliveryMode {
        val policy = ReaderSafetyPolicy.formatPolicy(format)
            ?: return ReaderDeliveryMode.Unsupported
        if (!readerType.trim().equals(policy.morphology.readerTypeWire, ignoreCase = true)) {
            return ReaderDeliveryMode.Unsupported
        }
        return when (policy.deliveryMode) {
            ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL -> ReaderDeliveryMode.DownloadOriginal
            ReaderSafetyDeliveryMode.STREAM -> ReaderDeliveryMode.Stream
            ReaderSafetyDeliveryMode.PLAYER -> ReaderDeliveryMode.Unsupported
        }
    }
}

private val ReaderSafetyMorphology.readerTypeWire: String
    get() = when (this) {
        ReaderSafetyMorphology.REFLOWABLE -> "reflowable"
        ReaderSafetyMorphology.PDF -> "pdf"
        ReaderSafetyMorphology.COMIC -> "comic"
        ReaderSafetyMorphology.AUDIO -> "audio"
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
        require(mediaType in ReaderSafetyPolicy.comicProfile.allowedPageMimeTypes)
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
    /** Strong server revision advertised by the v4 comic manifest. */
    val revision: String,
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
        require(isValidComicRevision(revision)) { "Remote comic revision is invalid" }
        require(pages.isNotEmpty())
        require(pages.map(RemoteComicPage::pageIndex) == pages.indices.toList())
    }
}

/** The server revision is an opaque hash with a deliberately narrow wire shape. */
fun isValidComicRevision(value: String): Boolean =
    value.matches(Regex("^sha256:[0-9a-f]{64}$"))
