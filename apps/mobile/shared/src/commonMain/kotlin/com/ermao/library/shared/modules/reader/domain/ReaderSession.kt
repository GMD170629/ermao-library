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
    PublicationChanged("PUBLICATION_CHANGED"),
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

/** Maps transport/bootstrap/parser stable codes into the Reader UI error taxonomy. */
fun readerErrorCodeForFailure(
    failureCode: String,
    recoverable: Boolean,
): ReaderErrorCode {
    val code = failureCode.trim().uppercase()
    return when {
        code in setOf("PUBLICATION_CHANGED", "PUBLICATION_RESOURCE_CHANGED", "BINARY_VERSION_CHANGED") -> ReaderErrorCode.PublicationChanged
        code in setOf("PUBLICATION_RESOURCE_TOO_LARGE", "BINARY_TOO_LARGE") -> ReaderErrorCode.OutOfMemoryRisk
        code in NETWORK_FAILURE_CODES || recoverable -> ReaderErrorCode.NetworkUnavailable
        code == "COMIC_ARCHIVE_PART_MISSING" || code == "ARCHIVE_PART_MISSING" ->
            ReaderErrorCode.ComicArchivePartMissing
        code == "COMIC_ARCHIVE_FORMAT_UNSUPPORTED" || code == "ARCHIVE_FORMAT_SETUP_FAILED" ->
            ReaderErrorCode.ComicArchiveFormatUnsupported
        code == "COMIC_PAGE_DECODE_FAILED" -> ReaderErrorCode.ComicPageDecodeFailed
        code == "COMIC_ARCHIVE_OPEN_FAILED" || code == "ARCHIVE_OPEN_FAILED" ->
            ReaderErrorCode.ComicArchiveOpenFailed
        code == "COMIC_ARCHIVE_CORRUPT" || code.startsWith("ARCHIVE_PATH_") ||
            code.startsWith("ARCHIVE_HEADER_") || code.startsWith("ARCHIVE_DATA_") ||
            code == "ARCHIVE_NO_IMAGES" -> ReaderErrorCode.ComicArchiveCorrupt
        code == "COMIC_OUT_OF_MEMORY_RISK" || code.startsWith("ARCHIVE_OUT_OF_MEMORY") ||
            code.contains("ARCHIVE_ENTRY_LIMIT") || code.contains("ARCHIVE_PAGE_LIMIT") ||
            code.contains("ARCHIVE_EXPANDED_LIMIT") -> ReaderErrorCode.ComicOutOfMemoryRisk
        "DRM" in code -> ReaderErrorCode.DrmProtected
        "ENCRYPT" in code -> if (code.startsWith("PDF_")) {
            ReaderErrorCode.Encrypted
        } else {
            ReaderErrorCode.ComicArchiveEncrypted
        }
        "UNSUPPORTED" in code || "FORMAT_UNSUPPORTED" in code -> ReaderErrorCode.UnsupportedFormat
        "OUT_OF_MEMORY" in code || "LIMIT_EXCEEDED" in code || "TOO_LARGE" in code -> ReaderErrorCode.OutOfMemoryRisk
        "MISSING" in code || "NOT_FOUND" in code -> ReaderErrorCode.ResourceMissing
        "PARSE" in code -> ReaderErrorCode.ParseFailed
        "CORRUPT" in code || "INVALID" in code || "CONTENT_TYPE" in code -> ReaderErrorCode.CorruptFile
        else -> ReaderErrorCode.ReaderEngineError
    }
}

private val NETWORK_FAILURE_CODES = setOf(
    "NETWORK_UNAVAILABLE",
    "TIMEOUT",
    "RATE_LIMITED",
    "SERVICE_UNAVAILABLE",
    "SERVER_FAILURE",
    "TLS_FAILURE",
    "UNAUTHORIZED",
)

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
