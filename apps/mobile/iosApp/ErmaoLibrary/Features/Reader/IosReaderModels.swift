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

enum IosReaderFailureCode: String, Sendable {
    case unsupportedFormat = "UNSUPPORTED_FORMAT"
    case corruptFile = "CORRUPT_FILE"
    case drmProtected = "DRM_PROTECTED"
    case parseFailed = "PARSE_FAILED"
    case resourceMissing = "RESOURCE_MISSING"
    case networkUnavailable = "NETWORK_UNAVAILABLE"
    case outOfMemoryRisk = "OUT_OF_MEMORY_RISK"
    case engineError = "READER_ENGINE_ERROR"
    case locationRestoreFailed = "LOCATION_RESTORE_FAILED"
    case persistenceFailed = "PERSISTENCE_FAILED"
    case pdfRangeUnsupported = "PDF_RANGE_UNSUPPORTED"
    case pdfRangeInvalid = "PDF_RANGE_INVALID"
    case pdfResourceChanged = "PDF_RESOURCE_CHANGED"
    case pdfCacheIO = "PDF_CACHE_IO"
    case pdfEncrypted = "PDF_ENCRYPTED"
    case pdfInvalid = "PDF_INVALID"
    case pdfPageLoadFailed = "PDF_PAGE_LOAD_FAILED"
    case pdfRenderFailed = "PDF_RENDER_FAILED"
    case comicArchiveOpenFailed = "COMIC_ARCHIVE_OPEN_FAILED"
    case comicArchiveEncrypted = "COMIC_ARCHIVE_ENCRYPTED"
    case comicArchivePartMissing = "COMIC_ARCHIVE_PART_MISSING"
    case comicArchiveFormatUnsupported = "COMIC_ARCHIVE_FORMAT_UNSUPPORTED"
    case comicArchiveCorrupt = "COMIC_ARCHIVE_CORRUPT"
    case comicPageDecodeFailed = "COMIC_PAGE_DECODE_FAILED"
    case comicOutOfMemoryRisk = "COMIC_OUT_OF_MEMORY_RISK"

    var localizedDescription: String {
        switch self {
        case .unsupportedFormat: String(localized: "reader.error.UNSUPPORTED_FORMAT")
        case .corruptFile: String(localized: "reader.error.CORRUPT_FILE")
        case .drmProtected: String(localized: "reader.error.DRM_PROTECTED")
        case .parseFailed: String(localized: "reader.error.PARSE_FAILED")
        case .resourceMissing: String(localized: "reader.error.RESOURCE_MISSING")
        case .networkUnavailable: String(localized: "reader.error.NETWORK_UNAVAILABLE")
        case .outOfMemoryRisk: String(localized: "reader.error.OUT_OF_MEMORY_RISK")
        case .engineError: String(localized: "reader.error.READER_ENGINE_ERROR")
        case .locationRestoreFailed: String(localized: "reader.error.LOCATION_RESTORE_FAILED")
        case .persistenceFailed: String(localized: "reader.error.PERSISTENCE_FAILED")
        case .pdfRangeUnsupported: String(localized: "reader.error.PDF_RANGE_UNSUPPORTED")
        case .pdfRangeInvalid: String(localized: "reader.error.PDF_RANGE_INVALID")
        case .pdfResourceChanged: String(localized: "reader.error.PDF_RESOURCE_CHANGED")
        case .pdfCacheIO: String(localized: "reader.error.PDF_CACHE_IO")
        case .pdfEncrypted: String(localized: "reader.error.PDF_ENCRYPTED")
        case .pdfInvalid: String(localized: "reader.error.PDF_INVALID")
        case .pdfPageLoadFailed: String(localized: "reader.error.PDF_PAGE_LOAD_FAILED")
        case .pdfRenderFailed: String(localized: "reader.error.PDF_RENDER_FAILED")
        case .comicArchiveOpenFailed, .comicArchiveEncrypted, .comicArchivePartMissing,
             .comicArchiveFormatUnsupported, .comicArchiveCorrupt, .comicPageDecodeFailed,
             .comicOutOfMemoryRisk:
            String(localized: "reader.error.COMIC_ARCHIVE_OPEN_FAILED")
        }
    }
}

struct IosReaderFailure: LocalizedError, Equatable, Sendable {
    let code: IosReaderFailureCode

    var errorDescription: String? {
        code.localizedDescription
    }
}

struct IosReaderProgressContract: Equatable, Sendable {
    let sourceID: String
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
    let fileID: String?
    let chapterID: String?
    let positionMillis: Int64?
    let updatedAtEpochMillis: Int64
    let deviceID: String
}

/// Strict Swift-side projection of shared local-exact `ReaderProgressJson` v6 documents.
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
        guard document.schema == "ermao.reader-progress", document.version == 6,
              ["reflow", "pdf", "comic", "audio"].contains(document.location.kind),
              !document.sourceId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
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
            guard let fileID = document.location.fileId,
                  !fileID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  let positionMillis = document.location.positionMillis, positionMillis >= 0
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
        default: throw IosReaderFailure(code: .locationRestoreFailed)
        }
        let engineJSON = try document.location.engineLocator.map {
            try enginePayload($0, schemaVersion: document.version)
        }
        return IosReaderProgressContract(
            sourceID: document.sourceId,
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
            fileID: document.location.fileId,
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
        guard schemaVersion == 6 else { throw IosReaderFailure(code: .locationRestoreFailed) }
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
        let sourceId: String
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
        let fileId: String?
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
