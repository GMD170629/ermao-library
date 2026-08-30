import Foundation
@preconcurrency import ErmaoShared

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

struct IosReaderProgressContract: Equatable, Sendable {
    let resourceID: String
    let kind: String
    let resourceKey: String?
    let progression: Double?
    let totalProgression: Double?
    let position: Int?
    let quoteExact: String?
    let quotePrefix: String?
    let quoteSuffix: String?
    let engineLocatorCanonicalJSON: String?
    let pageIndex: Int?
    let pageProgression: Double?
    let resourceHref: String?
    let assetID: String?
    let chapterID: String?
    let positionMillis: Int64?
    let updatedAtEpochMillis: Int64
    let deviceID: String
}

/// Strict Swift-side projection of shared local-exact `ReaderProgressJson` v7 documents.
/// The KMP codec remains the persistence authority; this decoder lets iOS map
/// an engine locator without turning its arbitrary JSON members into domain state.
enum IosReaderProgressContractDecoder {
    static func decode(_ payload: String) throws -> IosReaderProgressContract {
        _ = try ErmaoShared.PublicKt.createReaderProgressJson().decode(payload: payload)
        let data = Data(payload.utf8)
        let document = try JSONDecoder().decode(Document.self, from: data)
        let resourceKeyIsValid = document.location.resourceKey.map {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        } ?? true
        let progressionIsValid = document.location.progression.map {
            $0.isFinite && (0 ... 1).contains($0)
        } ?? true
        let totalProgressionIsValid = document.location.totalProgression.map {
            $0.isFinite && (0 ... 1).contains($0)
        } ?? true
        let positionIsValid = document.location.position.map { $0 > 0 } ?? true
        let textQuoteIsValid = document.location.textQuote.map {
            !$0.exact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && ($0.prefix.map { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } ?? true)
                && ($0.suffix.map { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } ?? true)
        } ?? true
        let engineLocatorIsValid = document.location.engineLocator.map(\.isObject) ?? true
        guard document.schema == "ermao.reader-progress", document.version == 7,
              ["reflow", "pdf", "comic", "audio"].contains(document.location.kind),
              !document.resourceId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              resourceKeyIsValid,
              progressionIsValid,
              totalProgressionIsValid,
              positionIsValid,
              textQuoteIsValid,
              engineLocatorIsValid,
              !document.deviceId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw IosReaderFailure(code: .locationRestoreFailed)
        }
        switch document.location.kind {
        case "reflow":
            guard document.location.engineLocator != nil else { throw IosReaderFailure(code: .locationRestoreFailed) }
        case "pdf":
            guard let pageIndex = document.location.pageIndex, pageIndex >= 0,
                  let pageProgression = document.location.pageProgression,
                  pageProgression.isFinite, (0 ... 1).contains(pageProgression)
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
        case "comic":
            guard let pageIndex = document.location.pageIndex, pageIndex >= 0,
                  let href = document.location.resourceHref,
                  !href.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
        case "audio":
            guard let assetID = document.location.assetId,
                  !assetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  let positionMillis = document.location.positionMillis, positionMillis >= 0
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
        default: throw IosReaderFailure(code: .locationRestoreFailed)
        }
        let engineJSON = try document.location.engineLocator.map {
            try enginePayload($0, schemaVersion: document.version)
        }
        return IosReaderProgressContract(
            resourceID: document.resourceId,
            kind: document.location.kind,
            resourceKey: document.location.resourceKey,
            progression: document.location.progression,
            totalProgression: document.location.totalProgression,
            position: document.location.position,
            quoteExact: document.location.textQuote?.exact,
            quotePrefix: document.location.textQuote?.prefix,
            quoteSuffix: document.location.textQuote?.suffix,
            engineLocatorCanonicalJSON: engineJSON,
            pageIndex: document.location.pageIndex,
            pageProgression: document.location.pageProgression,
            resourceHref: document.location.resourceHref,
            assetID: document.location.assetId,
            chapterID: document.location.chapterId,
            positionMillis: document.location.positionMillis,
            updatedAtEpochMillis: document.updatedAtEpochMillis,
            deviceID: document.deviceId
        )
    }

    private static func canonicalJSON(_ value: JSONValue) throws -> String {
        let data = try JSONSerialization.data(
            withJSONObject: value.foundationValue,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        guard let result = String(data: data, encoding: .utf8) else {
            throw IosReaderFailure(code: .locationRestoreFailed)
        }
        return result
    }

    private static func enginePayload(_ value: JSONValue, schemaVersion: Int) throws -> String {
        guard schemaVersion == 7 else { throw IosReaderFailure(code: .locationRestoreFailed) }
        guard case let .object(fields) = value,
              fields["engine"]?.stringValue == "readium",
              fields["platform"]?.stringValue == "ios",
              let version = fields["version"]?.stringValue,
              !version.isEmpty,
              let payload = fields["payload"],
              payload.isObject
        else { throw IosReaderFailure(code: .locationRestoreFailed) }
        let result = try canonicalJSON(payload)
        guard result.utf8.count <= 65_536 else { throw IosReaderFailure(code: .locationRestoreFailed) }
        return result
    }

    private struct Document: Decodable {
        let schema: String
        let version: Int
        let resourceId: String
        let location: Location
        let updatedAtEpochMillis: Int64
        let deviceId: String
    }

    private struct Location: Decodable {
        let kind: String
        let resourceKey: String?
        let progression: Double?
        let totalProgression: Double?
        let position: Int?
        let textQuote: Quote?
        let engineLocator: JSONValue?
        let pageIndex: Int?
        let pageProgression: Double?
        let resourceHref: String?
        let assetId: String?
        let chapterId: String?
        let positionMillis: Int64?
    }

    private struct Quote: Decodable {
        let exact: String
        let prefix: String?
        let suffix: String?
    }

}

private enum JSONValue: Decodable {
    case object([String: JSONValue])
    case array([JSONValue])
    case string(String)
    case number(Double)
    case boolean(Bool)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else { self = .number(try container.decode(Double.self)) }
    }

    var foundationValue: Any {
        switch self {
        case let .object(value): value.mapValues(\.foundationValue)
        case let .array(value): value.map(\.foundationValue)
        case let .string(value): value
        case let .number(value): value
        case let .boolean(value): value
        case .null: NSNull()
        }
    }

    var isObject: Bool {
        if case .object = self { return true }
        return false
    }

    var stringValue: String? {
        if case let .string(value) = self { return value }
        return nil
    }
}
