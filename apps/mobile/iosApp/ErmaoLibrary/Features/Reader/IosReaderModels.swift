import Foundation
@preconcurrency import ErmaoShared

struct IosContentFingerprint: Codable, Equatable, Sendable {
    let originalFileHash: String
    let parserVersion: String
    let normalizationVersion: String

    init(originalFileHash: String, parserVersion: String, normalizationVersion: String) throws {
        let digest = originalFileHash.dropFirst("sha256:".count)
        guard originalFileHash.hasPrefix("sha256:"), originalFileHash.count == 71,
              digest.allSatisfy({ $0.isHexDigit }),
              !parserVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !normalizationVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        self.originalFileHash = originalFileHash
        self.parserVersion = parserVersion
        self.normalizationVersion = normalizationVersion
    }

    init(shared: ErmaoShared.ContentFingerprint) {
        originalFileHash = shared.originalFileHash
        parserVersion = shared.parserVersion
        normalizationVersion = shared.normalizationVersion
    }

    var shared: ErmaoShared.ContentFingerprint {
        ErmaoShared.ContentFingerprint(
            originalFileHash: originalFileHash,
            parserVersion: parserVersion,
            normalizationVersion: normalizationVersion
        )
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
    let resourceKey: String?
    let progression: Double?
    let totalProgression: Double?
    let position: Int?
    let quoteExact: String?
    let quotePrefix: String?
    let quoteSuffix: String?
    let engineLocatorCanonicalJSON: String?
    let fingerprint: IosContentFingerprint
    let updatedAtEpochMillis: Int64
    let deviceID: String
}

/// Strict Swift-side projection of shared local-exact `ReaderProgressJson` v1/v4 documents.
/// The KMP codec remains the persistence authority; this decoder lets iOS map
/// an engine locator without turning its arbitrary JSON members into domain state.
enum IosReaderProgressContractDecoder {
    static func decode(_ payload: String) throws -> IosReaderProgressContract {
        let data = Data(payload.utf8)
        let document = try JSONDecoder().decode(Document.self, from: data)
        guard document.schema == "ermao.reader-progress", [1, 4].contains(document.version),
              document.location.kind == "reflow",
              !document.sourceId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              document.location.resourceKey.map {
                  !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              } ?? true,
              document.location.progression.map { $0.isFinite && (0 ... 1).contains($0) } ?? true,
              document.location.totalProgression.map { $0.isFinite && (0 ... 1).contains($0) } ?? true,
              document.location.position.map { $0 > 0 } ?? true,
              document.location.textQuote.map {
                  !$0.exact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                      && ($0.prefix.map { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } ?? true)
                      && ($0.suffix.map { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } ?? true)
              } ?? true,
              document.location.engineLocator.map(\.isObject) ?? true,
              document.location.engineLocator != nil || document.location.resourceKey != nil
                  || document.location.textQuote != nil || document.location.position != nil,
              !document.deviceId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw IosReaderFailure(code: .locationRestoreFailed)
        }
        let engineJSON = try document.location.engineLocator.map {
            try enginePayload($0, schemaVersion: document.version)
        }
        return IosReaderProgressContract(
            sourceID: document.sourceId,
            resourceKey: document.location.resourceKey,
            progression: document.location.progression,
            totalProgression: document.location.totalProgression,
            position: document.location.position,
            quoteExact: document.location.textQuote?.exact,
            quotePrefix: document.location.textQuote?.prefix,
            quoteSuffix: document.location.textQuote?.suffix,
            engineLocatorCanonicalJSON: engineJSON,
            fingerprint: try IosContentFingerprint(
                originalFileHash: document.location.contentFingerprint.originalFileHash,
                parserVersion: document.location.contentFingerprint.parserVersion,
                normalizationVersion: document.location.contentFingerprint.normalizationVersion
            ),
            updatedAtEpochMillis: document.updatedAtEpochMillis,
            deviceID: document.deviceId
        )
    }

    private static func canonicalJSON(_ value: JSONValue) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: value.foundationValue, options: [.sortedKeys])
        guard let result = String(data: data, encoding: .utf8) else {
            throw IosReaderFailure(code: .locationRestoreFailed)
        }
        return result
    }

    private static func enginePayload(_ value: JSONValue, schemaVersion: Int) throws -> String {
        if schemaVersion == 1 { return try canonicalJSON(value) }
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
        let contentFingerprint: Fingerprint
    }

    private struct Quote: Decodable {
        let exact: String
        let prefix: String?
        let suffix: String?
    }

    private struct Fingerprint: Decodable {
        let originalFileHash: String
        let parserVersion: String
        let normalizationVersion: String
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
