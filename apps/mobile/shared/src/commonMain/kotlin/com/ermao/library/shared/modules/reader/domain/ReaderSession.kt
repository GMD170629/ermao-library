package com.ermao.library.shared.modules.reader.domain

enum class ReaderSessionPhase {
    Opening,
    Ready,
    Reading,
    Background,
    Closing,
    Closed,
    Failed,
}

enum class ReaderErrorCode(val wireValue: String) {
    UnsupportedFormat("UNSUPPORTED_FORMAT"),
    CorruptFile("CORRUPT_FILE"),
    DrmProtected("DRM_PROTECTED"),
    ParseFailed("PARSE_FAILED"),
    ResourceMissing("RESOURCE_MISSING"),
    NetworkUnavailable("NETWORK_UNAVAILABLE"),
    OutOfMemoryRisk("OUT_OF_MEMORY_RISK"),
    ReaderEngineError("READER_ENGINE_ERROR"),
    LocationRestoreFailed("LOCATION_RESTORE_FAILED"),
    RangeUnsupported("PDF_RANGE_UNSUPPORTED"),
    RangeInvalid("PDF_RANGE_INVALID"),
    ResourceChanged("PDF_RESOURCE_CHANGED"),
    CacheIo("PDF_CACHE_IO"),
    Encrypted("PDF_ENCRYPTED"),
    Invalid("PDF_INVALID"),
    PageLoadFailed("PDF_PAGE_LOAD_FAILED"),
    RenderFailed("PDF_RENDER_FAILED"),
    ComicArchiveOpenFailed("COMIC_ARCHIVE_OPEN_FAILED"),
    ComicArchiveEncrypted("COMIC_ARCHIVE_ENCRYPTED"),
    ComicArchivePartMissing("COMIC_ARCHIVE_PART_MISSING"),
    ComicArchiveFormatUnsupported("COMIC_ARCHIVE_FORMAT_UNSUPPORTED"),
    ComicArchiveCorrupt("COMIC_ARCHIVE_CORRUPT"),
    ComicPageDecodeFailed("COMIC_PAGE_DECODE_FAILED"),
    ComicOutOfMemoryRisk("COMIC_OUT_OF_MEMORY_RISK"),
}

data class ReaderError(
    val code: ReaderErrorCode,
    val safeContext: Map<String, String> = emptyMap(),
)

data class ReaderSession(
    val sessionId: String,
    val source: ReaderSource,
    val phase: ReaderSessionPhase,
    val capabilities: ReaderCapabilities,
    val preferences: ReaderPreferences,
    val currentLocation: ReaderLocation? = null,
    val error: ReaderError? = null,
) {
    init {
        require(sessionId.isNotBlank()) { "Reader session id is blank" }
        require((phase == ReaderSessionPhase.Failed) == (error != null)) {
            "Only a failed Reader session carries an error"
        }
    }
}
