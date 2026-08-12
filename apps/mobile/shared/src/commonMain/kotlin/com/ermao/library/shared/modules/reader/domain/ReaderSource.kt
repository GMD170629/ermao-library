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

sealed interface ReaderSource {
    val sourceId: String
    val displayTitle: String
    val format: ReaderFormat
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
) : ReaderSource {
    init {
        require(sourceId.isNotBlank()) { "Reader source id is blank" }
        require(displayTitle.isNotBlank()) { "Reader display title is blank" }
        require(workId == null || workId.isNotBlank()) { "Work id is blank" }
        require(volumeId == null || volumeId.isNotBlank()) { "Volume id is blank" }
    }
}
