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
    ReadFailed("PUBLICATION_READ_FAILED"),
    SecurityRejected("PUBLICATION_SECURITY_REJECTED"),
    ResourceMissing("RESOURCE_MISSING"),
    PublicationUnavailable("PUBLICATION_UNAVAILABLE"),
    PublicationChanged("PUBLICATION_CHANGED"),
    Unauthorized("UNAUTHORIZED"),
    Forbidden("FORBIDDEN"),
    InvalidResponse("PUBLICATION_RESPONSE_INVALID"),
    ServerUnavailable("SERVER_UNAVAILABLE"),
    RequestTimeout("REQUEST_TIMEOUT"),
    TlsFailure("TLS_FAILURE"),
    RateLimited("RATE_LIMITED"),
    TxtNulCharacter("PUBLICATION_TXT_NUL_CHARACTER"),
    TxtEncodingUnsupported("PUBLICATION_TXT_ENCODING_UNSUPPORTED"),
    TxtEmpty("PUBLICATION_TXT_EMPTY"),
    NetworkUnavailable("NETWORK_UNAVAILABLE"),
    OutOfMemoryRisk("OUT_OF_MEMORY_RISK"),
    PublicationTooLarge("READER_PUBLICATION_TOO_LARGE"),
    OnlineLimit("PUBLICATION_ONLINE_LIMIT"),
    ReaderEngineError("READER_ENGINE_ERROR"),
    LocationRestoreFailed("LOCATION_RESTORE_FAILED"),
    RangeUnsupported("PDF_RANGE_UNSUPPORTED"),
    RangeInvalid("PDF_RANGE_INVALID"),
    PdfEngineLimit("PDF_ENGINE_PROGRESS_LIMIT"),
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
    // Retained for public-call compatibility; retryability does not identify a cause.
    @Suppress("UNUSED_PARAMETER")
    recoverable: Boolean,
): ReaderErrorCode {
    val code = failureCode.trim().uppercase()
    ReaderErrorCode.entries.firstOrNull { it.wireValue == code }?.let { return it }
    return when (code) {
        "PUBLICATION_RESOURCE_CHANGED", "BINARY_VERSION_CHANGED", "CONFLICT" -> ReaderErrorCode.PublicationChanged
        "PUBLICATION_RESOURCE_TOO_LARGE", "BINARY_TOO_LARGE", "PAYLOAD_TOO_LARGE" -> ReaderErrorCode.OnlineLimit
        "PUBLICATION_NOT_FOUND", "PUBLICATION_RESOURCE_NOT_FOUND", "NOT_FOUND", "GONE" -> ReaderErrorCode.PublicationUnavailable
        "READER_PUBLICATION_ASSET_MISSING" -> ReaderErrorCode.ResourceMissing
        "PUBLICATION_CORRUPT", "PUBLICATION_PARSE_FAILED", "PUBLICATION_MARKUP_INVALID",
        "PUBLICATION_STRUCTURE_INVALID" -> ReaderErrorCode.ParseFailed
        "PUBLICATION_DRM_PROTECTED" -> ReaderErrorCode.DrmProtected
        "PUBLICATION_PARSER_LIMIT", "PUBLICATION_PARSER_MEMORY" -> ReaderErrorCode.OutOfMemoryRisk
        "READER_PUBLICATION_ASSET_INVALID" -> ReaderErrorCode.CorruptFile
        "PUBLICATION_UNSUPPORTED", "READER_PUBLICATION_UNSUPPORTED", "READER_BOOTSTRAP_UNSUPPORTED" -> ReaderErrorCode.UnsupportedFormat
        "TIMEOUT" -> ReaderErrorCode.RequestTimeout
        "SERVER_FAILURE", "SERVICE_UNAVAILABLE", "UNAVAILABLE" -> ReaderErrorCode.ServerUnavailable
        "BINARY_CONTENT_TYPE_MISSING", "BINARY_CONTENT_TYPE_INVALID", "BINARY_LENGTH_INVALID",
        "BINARY_LENGTH_MISMATCH", "BINARY_REDIRECT_REJECTED", "UNEXPECTED_BINARY_RESPONSE",
        "JSON_CONTENT_TYPE_MISSING", "JSON_CONTENT_TYPE_INVALID", "JSON_RESPONSE_LIMIT_OR_LENGTH_INVALID",
        "REDIRECT_LOCATION_MISSING", "REDIRECT_LOCATION_INVALID", "PROTOCOL_VIOLATION",
        "PUBLICATION_MANIFEST_INVALID", "PUBLICATION_POSITIONS_INVALID", "PUBLICATION_READING_ORDER_EMPTY",
        "PUBLICATION_RESOURCE_HREF_INVALID", "READER_PUBLICATION_MANIFEST_INVALID", "READER_BOOTSTRAP_INVALID",
        -> ReaderErrorCode.InvalidResponse
        "ARCHIVE_PART_MISSING" -> ReaderErrorCode.ComicArchivePartMissing
        "ARCHIVE_FORMAT_SETUP_FAILED" -> ReaderErrorCode.ComicArchiveFormatUnsupported
        "ARCHIVE_OPEN_FAILED" -> ReaderErrorCode.ComicArchiveOpenFailed
        "ARCHIVE_ENCRYPTED" -> ReaderErrorCode.ComicArchiveEncrypted
        "ARCHIVE_PATH_INVALID", "ARCHIVE_PATH_DUPLICATE", "ARCHIVE_HEADER_INVALID", "ARCHIVE_DATA_INVALID",
        "ARCHIVE_DATA_TRUNCATED", "ARCHIVE_NO_IMAGES", "ARCHIVE_ENTRY_TYPE_INVALID",
        -> ReaderErrorCode.ComicArchiveCorrupt
        "ARCHIVE_OUT_OF_MEMORY", "ARCHIVE_ENTRY_LIMIT_EXCEEDED", "ARCHIVE_PAGE_LIMIT_EXCEEDED",
        "ARCHIVE_EXPANDED_LIMIT_EXCEEDED",
        -> ReaderErrorCode.ComicOutOfMemoryRisk
        "ARCHIVE_PAGE_MISSING" -> ReaderErrorCode.ResourceMissing
        else -> ReaderErrorCode.ReaderEngineError
    }
}

data class ReaderError(
    val code: ReaderErrorCode,
    val safeContext: Map<String, String> = emptyMap(),
    val cause: Throwable? = null,
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
