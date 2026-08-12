import Foundation

enum MobiFormat: String, Codable, CaseIterable, Sendable {
    case mobi6
    case kf8
    case hybrid
}

enum MobiResourceCategory: String, Codable, Sendable {
    case markup
    case flow
    case resource
}

enum MobiReadingProgression: String, Codable, Sendable {
    case leftToRight
    case rightToLeft
}

struct MobiMetadata: Codable, Equatable, Sendable {
    let title: String
    let author: String?
    let language: String?
    let description: String?
    let readingProgression: MobiReadingProgression
}

struct MobiResource: Codable, Equatable, Identifiable, Sendable {
    var id: String { href }

    let uid: UInt64
    let href: String
    let mediaType: String
    let category: MobiResourceCategory
    let data: Data

    var isHTML: Bool {
        mediaType == "text/html" || mediaType == "application/xhtml+xml"
    }
}

typealias MobiContentResource = MobiResource

struct MobiNavigationItem: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let title: String
    let href: String
    let children: [MobiNavigationItem]
}

extension Array where Element == MobiNavigationItem {
    var flattened: [MobiNavigationItem] {
        flatMap { [$0] + $0.children.flattened }
    }
}

enum MobiWarningCode: String, Codable, Sendable {
    case missingOPF
    case invalidOPF
    case readingOrderFallback
    case missingNCX
    case invalidNCX
    case unresolvedTOCTarget
    case unsupportedResource
}

struct MobiWarning: Codable, Equatable, Identifiable, Sendable {
    var id: String { "\(code.rawValue):\(message)" }

    let code: MobiWarningCode
    let message: String
}

struct MobiExtractedBook: Sendable {
    let format: MobiFormat
    let metadata: MobiMetadata
    let readingOrder: [MobiContentResource]
    let resources: [MobiResource]
    let tableOfContents: [MobiNavigationItem]
    let warnings: [MobiWarning]

    var allResources: [MobiResource] {
        readingOrder + resources
    }
}

protocol MobiExtracting: Sendable {
    func extract(_ file: URL) async throws -> MobiExtractedBook
}

enum MobiExtractionError: Error, Equatable, LocalizedError, Sendable {
    case fileNotFound
    case unreadableFile
    case encrypted
    case unsupportedFormat
    case corruptContainer
    case noMarkup
    case outOfMemory
    case invalidResourcePath(String)
    case duplicateResourcePath(String)
    case libmobi(code: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .fileNotFound:
            String(localized: "error.fileNotFound")
        case .unreadableFile:
            String(localized: "error.unreadableFile")
        case .encrypted:
            String(localized: "error.encrypted")
        case .unsupportedFormat:
            String(localized: "error.unsupportedFormat")
        case .corruptContainer:
            String(localized: "error.corruptContainer")
        case .noMarkup:
            String(localized: "error.noMarkup")
        case .outOfMemory:
            String(localized: "error.outOfMemory")
        case let .invalidResourcePath(path):
            String(format: String(localized: "error.invalidResourcePath"), path)
        case let .duplicateResourcePath(path):
            String(format: String(localized: "error.duplicateResourcePath"), path)
        case let .libmobi(code, message):
            String(format: String(localized: "error.libmobi"), code, message)
        }
    }
}
