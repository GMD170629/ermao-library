import Foundation
@preconcurrency import ErmaoShared

struct IosReaderResumePrompt {
    let capturedAtEpochMillis: Int64
    let percent: Double
    let chapterLabel: String?
    let pageNumber: Int?
}

@MainActor
final class IosReaderNavigationQueue {
    private var tail: Task<Void, Never>?

    func enqueue(_ operation: @escaping @MainActor () async -> Bool) async -> Bool {
        let previous = tail
        let current = Task { @MainActor in
            await previous?.value
            return await operation()
        }
        tail = Task { @MainActor in _ = await current.value }
        return await current.value
    }
}

struct IosReaderFailureCode: RawRepresentable, Hashable, Sendable {
    let rawValue: String

    init?(rawValue: String) {
        guard !rawValue.isEmpty else { return nil }
        self.rawValue = rawValue
    }

    private init(_ rawValue: String) { self.rawValue = rawValue }

    static let unsupportedFormat = Self("UNSUPPORTED_FORMAT")
    static let corruptFile = Self("CORRUPT_FILE")
    static var drmProtected: Self { safety(ErmaoShared.PublicKt.readerSafetyDrmFailure()) }
    static let parseFailed = Self("PARSE_FAILED")
    static let readFailed = Self("PUBLICATION_READ_FAILED")
    static var securityRejected: Self {
        safety(ErmaoShared.PublicKt.readerSafetyEpubArchiveStructureFailure())
    }
    static let resourceMissing = Self("RESOURCE_MISSING")
    static let publicationUnavailable = Self("PUBLICATION_UNAVAILABLE")
    static let unauthorized = Self("UNAUTHORIZED")
    static let forbidden = Self("FORBIDDEN")
    static let invalidResponse = Self("PUBLICATION_RESPONSE_INVALID")
    static let serverUnavailable = Self("SERVER_UNAVAILABLE")
    static let requestTimeout = Self("REQUEST_TIMEOUT")
    static let tlsFailure = Self("TLS_FAILURE")
    static let rateLimited = Self("RATE_LIMITED")
    static let txtNulCharacter = Self("PUBLICATION_TXT_NUL_CHARACTER")
    static let txtEncodingUnsupported = Self("PUBLICATION_TXT_ENCODING_UNSUPPORTED")
    static let txtEmpty = Self("PUBLICATION_TXT_EMPTY")
    static let publicationChanged = Self("PUBLICATION_CHANGED")
    static let networkUnavailable = Self("NETWORK_UNAVAILABLE")
    static let outOfMemoryRisk = Self("OUT_OF_MEMORY_RISK")
    static var publicationTooLarge: Self {
        safety(ErmaoShared.PublicKt.readerSafetyOriginalMaxBytesFailure())
    }
    static let engineError = Self("READER_ENGINE_ERROR")
    static let locationRestoreFailed = Self("LOCATION_RESTORE_FAILED")
    static let persistenceFailed = Self("PERSISTENCE_FAILED")
    static let pdfRangeUnsupported = Self("PDF_RANGE_UNSUPPORTED")
    static var pdfRangeInvalid: Self {
        safety(ErmaoShared.PublicKt.readerSafetyPdfRangeProtocolFailure())
    }
    static let pdfEngineLimit = Self("PDF_ENGINE_PROGRESS_LIMIT")
    static let pdfResourceChanged = Self("PDF_RESOURCE_CHANGED")
    static let pdfCacheIO = Self("PDF_CACHE_IO")
    static let pdfInvalid = Self("PDF_INVALID")
    static let pdfPageLoadFailed = Self("PDF_PAGE_LOAD_FAILED")
    static let pdfRenderFailed = Self("PDF_RENDER_FAILED")
    static let comicArchiveOpenFailed = Self("COMIC_ARCHIVE_OPEN_FAILED")
    static let comicArchiveEncrypted = Self("COMIC_ARCHIVE_ENCRYPTED")
    static let comicArchivePartMissing = Self("COMIC_ARCHIVE_PART_MISSING")
    static let comicArchiveFormatUnsupported = Self("COMIC_ARCHIVE_FORMAT_UNSUPPORTED")
    static let comicArchiveCorrupt = Self("COMIC_ARCHIVE_CORRUPT")
    static let comicPageDecodeFailed = Self("COMIC_PAGE_DECODE_FAILED")
    static let comicOutOfMemoryRisk = Self("COMIC_OUT_OF_MEMORY_RISK")

    init(sharedCode: ErmaoShared.ReaderErrorCode) {
        rawValue = sharedCode.wireValue
    }

    private static func safety(_ failure: ErmaoShared.ReaderSafetyFailure) -> Self {
        Self(failure.errorCode)
    }

    var localizationKey: String {
        "reader.error.\(rawValue)"
    }

    var localizedDescription: String {
        String(localized: String.LocalizationValue(localizationKey))
    }
}

struct IosReaderFailure: LocalizedError, Equatable, Sendable {
    let code: IosReaderFailureCode
    let safeContext: [String: String]
    let underlyingError: NSError?

    init(
        code: IosReaderFailureCode,
        safeContext: [String: String] = [:],
        underlyingError: NSError? = nil
    ) {
        self.code = code
        self.safeContext = safeContext
        self.underlyingError = underlyingError
    }

    static func security(_ error: IosPublicationSecurityError) -> IosReaderFailure {
        switch error {
        case let .rejected(ruleId, errorCode):
            return safety(
                ErmaoShared.ReaderSafetyFailure(ruleId: ruleId, errorCode: errorCode),
                underlyingError: error as NSError
            )
        case .invalidEncoding:
            return IosReaderFailure(code: .txtEncodingUnsupported, underlyingError: error as NSError)
        case .invalidMarkup:
            return IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
        }
    }

    static func safety(
        _ failure: ErmaoShared.ReaderSafetyFailure,
        underlyingError: NSError? = nil
    ) -> IosReaderFailure {
        let code = ErmaoShared.PublicKt.readerErrorCodeForFailure(
            failureCode: failure.errorCode,
            recoverable: false
        )
        return IosReaderFailure(
            code: IosReaderFailureCode(sharedCode: code),
            safeContext: ["ruleId": failure.ruleId, "errorCode": failure.errorCode],
            underlyingError: underlyingError
        )
    }

    static func fileRead(_ error: any Error) -> IosReaderFailure {
        if let failure = error as? IosReaderFailure { return failure }
        let underlying = error as NSError
        let code: IosReaderFailureCode
        switch (underlying.domain, underlying.code) {
        case (NSCocoaErrorDomain, NSFileReadNoSuchFileError), (NSCocoaErrorDomain, NSFileNoSuchFileError):
            code = .resourceMissing
        case (NSCocoaErrorDomain, NSFileReadNoPermissionError): code = .forbidden
        default: code = .readFailed
        }
        return IosReaderFailure(code: code, underlyingError: underlying)
    }

    var errorDescription: String? {
        code.localizedDescription
    }
}
