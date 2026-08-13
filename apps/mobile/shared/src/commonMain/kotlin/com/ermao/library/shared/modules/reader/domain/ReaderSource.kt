package com.ermao.library.shared.modules.reader.domain

data class ContentFingerprint(
    val originalFileHash: String,
    val parserVersion: String,
    val normalizationVersion: String,
) {
    init {
        require(originalFileHash.startsWith(SHA256_PREFIX)) { "Content hash must be SHA-256" }
        require(originalFileHash.length == SHA256_TEXT_LENGTH) { "Content hash has an invalid length" }
        require(originalFileHash.drop(SHA256_PREFIX.length).all { it.isHexDigit() }) {
            "Content hash contains non-hexadecimal characters"
        }
        require(parserVersion.isNotBlank()) { "Parser version is blank" }
        require(normalizationVersion.isNotBlank()) { "Normalization version is blank" }
    }

    val stableKey: String
        get() = "$originalFileHash|$parserVersion|$normalizationVersion"

    private companion object {
        const val SHA256_PREFIX = "sha256:"
        const val SHA256_TEXT_LENGTH = SHA256_PREFIX.length + 64
    }
}

private fun Char.isHexDigit(): Boolean = this in '0'..'9' || this in 'a'..'f' || this in 'A'..'F'

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
    Pdf(
        wireValue = "pdf",
        readerFormat = ReaderFormat.Pdf,
        fileKind = "PDF",
        allowedMimeTypes = setOf("application/pdf", "application/octet-stream"),
    ),
    ;

    fun acceptsMimeType(value: String): Boolean = value.trim().lowercase() in allowedMimeTypes

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
    val contentFingerprint: ContentFingerprint
    val workId: String?
    val volumeId: String?
}

data class LocalReaderSource(
    override val sourceId: String,
    override val displayTitle: String,
    override val format: ReaderFormat,
    override val contentFingerprint: ContentFingerprint,
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
