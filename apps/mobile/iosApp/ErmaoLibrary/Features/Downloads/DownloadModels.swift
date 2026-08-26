import Foundation

enum ManagedDownloadReaderType: String, Codable, Hashable, Sendable {
    case reflowable
    case comic
    case pdf
    case audio

    static func fixtureValue(format: String, readerType: String) -> Self? {
        switch readerType.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "reflowable": return .reflowable
        case "comic": return .comic
        case "pdf": return .pdf
        case "audio": return .audio
        default: break
        }
        switch format.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() {
        case "EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT": return .reflowable
        case "PDF": return .pdf
        case "COMIC", "CBR", "CBZ", "RAR", "ZIP": return .comic
        case "AUDIO", "AUDIOBOOK", "M4B", "M4A", "MP3": return .audio
        default: return nil
        }
    }

    var requiresCompleteDownloadBeforeReading: Bool { self == .reflowable }
    var supportsStreaming: Bool { self == .comic || self == .pdf }
}

enum ManagedDownloadState: String, Codable, Hashable, Sendable {
    case queued
    case downloading
    case paused
    case completed
    case failedRetryable = "failed-retryable"
    case failedTerminal = "failed-terminal"
}

enum ManagedDownloadVerification: String, Codable, Hashable, Sendable {
    case pending
    case verified
    case invalid
}

enum ManagedDownloadArtifactKind: String, Codable, Hashable, Sendable {
    case singleOriginalAsset
    case originalPageSet
}

/// iOS-owned manifest identity. One record is one Book/Resource/Asset copy.
struct ManagedDownloadRecord: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let namespace: String
    var bookID: String
    var bookTitle: String
    var bookAuthor: String?
    let resourceID: String
    let resourceTitle: String
    let assetID: String
    var format: String
    var mimeType: String?
    let readerType: ManagedDownloadReaderType
    var state: ManagedDownloadState
    var verification: ManagedDownloadVerification
    var expectedBytes: Int64?
    var artifactKind: ManagedDownloadArtifactKind?
    var receivedBytes: Int64
    var localRelativePath: String?
    var stableErrorCode: String?
    let createdAt: Date
    var updatedAt: Date
    var completedAt: Date?
    var lastOpenedAt: Date?

    var progress: Double? {
        guard let expectedBytes, expectedBytes > 0 else { return nil }
        return min(1, max(0, Double(receivedBytes) / Double(expectedBytes)))
    }

    var isVerifiedOfflineCopy: Bool {
        state == .completed && verification == .verified && localRelativePath != nil
    }

    var effectiveArtifactKind: ManagedDownloadArtifactKind { artifactKind ?? .singleOriginalAsset }
}

struct ManagedDownloadResourceGroup: Identifiable, Equatable, Sendable {
    let resourceID: String
    let records: [ManagedDownloadRecord]
    var id: String { resourceID }
    var title: String { records.first?.resourceTitle ?? resourceID }
    var totalBytes: Int64 { records.reduce(0) { $0 + $1.receivedBytes } }
}

struct ManagedDownloadBookGroup: Identifiable, Equatable, Sendable {
    let bookID: String
    let title: String
    let author: String?
    let resources: [ManagedDownloadResourceGroup]
    var id: String { bookID }
    var totalBytes: Int64 { resources.reduce(0) { $0 + $1.totalBytes } }
}

enum ManagedDownloadGrouping {
    static func completed(records: [ManagedDownloadRecord], query: String) -> [ManagedDownloadBookGroup] {
        let normalizedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let completed = records.filter { record in
            guard record.isVerifiedOfflineCopy else { return false }
            guard !normalizedQuery.isEmpty else { return true }
            return [record.bookTitle, record.bookAuthor ?? "", record.resourceTitle, record.format]
                .contains { $0.localizedCaseInsensitiveContains(normalizedQuery) }
        }
        return Dictionary(grouping: completed, by: \.bookID).compactMap { bookID, bookRecords in
            guard let first = bookRecords.first else { return nil }
            let resources = Dictionary(grouping: bookRecords, by: \.resourceID).map { resourceID, resourceRecords in
                ManagedDownloadResourceGroup(
                    resourceID: resourceID,
                    records: resourceRecords.sorted { $0.assetID < $1.assetID }
                )
            }.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
            return ManagedDownloadBookGroup(bookID: bookID, title: first.bookTitle, author: first.bookAuthor, resources: resources)
        }.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
    }
}

struct ManagedDownloadRequest: Sendable {
    let context: ContentRequestContext
    let record: ManagedDownloadRecord
    let destination: ManagedDownloadDestination
}

struct ManagedDownloadBootstrap: Sendable {
    let bookID: String
    let resourceID: String
    let assetID: String
    let sourceFormat: String
    let mimeType: String
    let readerType: ManagedDownloadReaderType
    let expectedBytes: Int64?
    let artifactKind: ManagedDownloadArtifactKind
}

struct ManagedDownloadDestination: Sendable {
    let partialFileURL: URL
    let finalFileURL: URL
    let finalRelativePath: String
}

struct ManagedDownloadProgress: Sendable {
    let receivedBytes: Int64
    let expectedBytes: Int64?
}

struct ManagedDownloadReceipt: Sendable {
    let receivedBytes: Int64
    let expectedBytes: Int64?
}

enum ManagedDownloadTransferError: Error, Equatable, Sendable {
    case unauthorized
    case inaccessible
    case insufficientSpace
    case invalidResponse
    case transportUnavailable
    case cancelled

    var stableCode: String {
        switch self {
        case .unauthorized: "DOWNLOAD_UNAUTHORIZED"
        case .inaccessible: "DOWNLOAD_CONTENT_UNAVAILABLE"
        case .insufficientSpace: "DOWNLOAD_INSUFFICIENT_SPACE"
        case .invalidResponse: "DOWNLOAD_INVALID_RESPONSE"
        case .transportUnavailable: "DOWNLOAD_TRANSPORT_UNAVAILABLE"
        case .cancelled: "DOWNLOAD_CANCELLED"
        }
    }
}

enum ManagedReaderAccessOutcome: Sendable {
    case open(ReaderHandoff)
    case needsDownload(recordID: String)
    case unavailable(String)
}

struct ReaderPreparationRequest: Identifiable, Sendable {
    let context: ContentRequestContext
    let book: BookCard
    let resource: BookResource
    var id: String { "\(context.namespaceKey)|\(resource.id)" }
}

enum ReaderHandoffSource: Hashable, Sendable {
    case verifiedLocal(recordID: String)
    case remoteStream
}

struct ReaderHandoff: Hashable, Sendable {
    let bookID: String
    let resourceID: String
    let assetID: String?
    let title: String
    let resourceTitle: String
    let format: String
    let readerType: ManagedDownloadReaderType
    let source: ReaderHandoffSource
}

enum ManagedReaderAccessPolicy {
    static func supportsNativeReader(readerType: ManagedDownloadReaderType, format: String) -> Bool {
        let normalized = format.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        return switch readerType {
        case .reflowable: ["EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT"].contains(normalized)
        case .comic: ["CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR"].contains(normalized)
        case .pdf: normalized == "PDF"
        case .audio: false
        }
    }

    static func verifiedLocalHandoff(record: ManagedDownloadRecord?, resourceID: String) -> ReaderHandoff? {
        guard let record, record.resourceID == resourceID, record.isVerifiedOfflineCopy else { return nil }
        return ReaderHandoff(
            bookID: record.bookID, resourceID: record.resourceID, assetID: record.assetID,
            title: record.bookTitle, resourceTitle: record.resourceTitle, format: record.format,
            readerType: record.readerType, source: .verifiedLocal(recordID: record.id)
        )
    }

    static func completedRecord(records: [ManagedDownloadRecord], recordID: String) -> ManagedDownloadRecord? {
        records.first { $0.id == recordID && $0.isVerifiedOfflineCopy }
    }
}

protocol ManagedDownloadTransferring: Sendable {
    func prepare(context: ContentRequestContext, resourceID: String) async throws -> ManagedDownloadBootstrap
    func download(_ request: ManagedDownloadRequest, progress: @escaping @Sendable (ManagedDownloadProgress) async -> Void) async throws -> ManagedDownloadReceipt
}

struct UnavailableManagedDownloadTransfer: ManagedDownloadTransferring {
    func prepare(context: ContentRequestContext, resourceID: String) async throws -> ManagedDownloadBootstrap { throw ManagedDownloadTransferError.transportUnavailable }
    func download(_ request: ManagedDownloadRequest, progress: @escaping @Sendable (ManagedDownloadProgress) async -> Void) async throws -> ManagedDownloadReceipt { throw ManagedDownloadTransferError.transportUnavailable }
}
