import Foundation

enum ManagedDownloadReaderType: String, Codable, Hashable, Sendable {
    case reflowable
    case comic
    case pdf
    case audio

    /// Test-fixture helper only. Production access policy must use Reader v4 bootstrap.readerType.
    static func fixtureValue(format: String, mediaKind: LibraryMediaKind) -> Self? {
        switch format.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() {
        case "EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT": .reflowable
        case "PDF": .pdf
        case "COMIC", "CBR", "CBZ", "RAR", "ZIP": .comic
        case "AUDIO", "AUDIOBOOK", "M4B", "M4A", "MP3": .audio
        default: mediaKind == .comic ? .comic : mediaKind == .audiobook ? .audio : nil
        }
    }

    var requiresCompleteDownloadBeforeReading: Bool {
        self == .reflowable
    }

    var supportsStreaming: Bool {
        self == .comic || self == .pdf
    }
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

struct ManagedDownloadRecord: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let namespace: String
    var workID: String
    var workTitle: String
    var workAuthor: String
    var versionID: String
    var versionSourceKey: String
    var versionSourceName: String?
    var versionCompleted: Bool?
    let volumeID: String
    let volumeTitle: String
    let format: String
    let readerType: ManagedDownloadReaderType
    var state: ManagedDownloadState
    var verification: ManagedDownloadVerification
    var expectedBytes: Int64?
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
}

struct ManagedDownloadVersionGroup: Identifiable, Equatable, Sendable {
    let versionID: String
    let sourceKey: String
    let sourceName: String?
    let isServerComplete: Bool?
    let records: [ManagedDownloadRecord]

    var id: String { versionID }
    var totalBytes: Int64 { records.reduce(0) { $0 + $1.receivedBytes } }
}

struct ManagedDownloadWorkGroup: Identifiable, Equatable, Sendable {
    let workID: String
    let title: String
    let author: String
    let versions: [ManagedDownloadVersionGroup]

    var id: String { workID }
    var totalBytes: Int64 { versions.reduce(0) { $0 + $1.totalBytes } }
}

enum ManagedDownloadGrouping {
    static let implicitSourceKey = "__implicit__"

    static func completed(records: [ManagedDownloadRecord], query: String) -> [ManagedDownloadWorkGroup] {
        let normalizedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let completed = records.filter { record in
            guard record.isVerifiedOfflineCopy else { return false }
            guard !normalizedQuery.isEmpty else { return true }
            return [record.workTitle, record.workAuthor, record.volumeTitle, record.format]
                .contains { $0.localizedCaseInsensitiveContains(normalizedQuery) }
        }
        var workGroups: [ManagedDownloadWorkGroup] = []
        for (workID, workRecords) in Dictionary(grouping: completed, by: \.workID) {
            guard let first = workRecords.first else { continue }
            var versions: [ManagedDownloadVersionGroup] = []
            for (versionID, versionRecords) in Dictionary(grouping: workRecords, by: \.versionID) {
                guard let firstVersion = versionRecords.first else { continue }
                versions.append(ManagedDownloadVersionGroup(
                    versionID: versionID,
                    sourceKey: firstVersion.versionSourceKey,
                    sourceName: firstVersion.versionSourceName,
                    isServerComplete: firstVersion.versionCompleted,
                    records: versionRecords.sorted {
                        $0.volumeTitle.localizedStandardCompare($1.volumeTitle) == .orderedAscending
                    }
                ))
            }
            versions.sort(by: versionOrder)
            workGroups.append(ManagedDownloadWorkGroup(
                workID: workID,
                title: first.workTitle,
                author: first.workAuthor,
                versions: versions
            ))
        }
        return workGroups.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
    }

    private static func versionOrder(_ lhs: ManagedDownloadVersionGroup, _ rhs: ManagedDownloadVersionGroup) -> Bool {
        let lhsImplicit = lhs.sourceKey == implicitSourceKey ? 0 : 1
        let rhsImplicit = rhs.sourceKey == implicitSourceKey ? 0 : 1
        if lhsImplicit != rhsImplicit { return lhsImplicit < rhsImplicit }
        let lhsName = lhs.sourceName ?? ""
        let rhsName = rhs.sourceName ?? ""
        let nameOrder = lhsName.localizedStandardCompare(rhsName)
        if nameOrder != .orderedSame { return nameOrder == .orderedAscending }
        let keyOrder = lhs.sourceKey.localizedStandardCompare(rhs.sourceKey)
        if keyOrder != .orderedSame { return keyOrder == .orderedAscending }
        return lhs.versionID < rhs.versionID
    }
}

struct ManagedDownloadRequest: Sendable {
    let context: ContentRequestContext
    let record: ManagedDownloadRecord
    let destination: ManagedDownloadDestination
}

struct ManagedDownloadBootstrap: Sendable {
    let versionID: String
    let versionSourceKey: String
    let versionSourceName: String?
    let versionCompleted: Bool?
    let readerType: ManagedDownloadReaderType
    let expectedBytes: Int64?
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
    let work: WorkCard
    let volume: WorkVolume
    let mediaKind: LibraryMediaKind

    var id: String { "\(context.namespaceKey)|\(volume.id)" }
}

enum ReaderHandoffSource: Hashable, Sendable {
    case verifiedLocal(recordID: String)
    case remoteStream
}

struct ReaderHandoff: Hashable, Sendable {
    let workID: String
    let volumeID: String
    let title: String
    let volumeTitle: String
    let format: String
    let readerType: ManagedDownloadReaderType
    let source: ReaderHandoffSource
}

enum ManagedReaderAccessPolicy {
    static func supportsNativeReader(readerType: ManagedDownloadReaderType, format: String) -> Bool {
        let normalized = format.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        switch readerType {
        case .reflowable:
            return ["EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT"].contains(normalized)
        case .comic:
            return ["CBZ", "ZIP"].contains(normalized)
        case .pdf:
            return normalized == "PDF"
        case .audio:
            return false
        }
    }

    static func verifiedLocalHandoff(
        record: ManagedDownloadRecord?,
        volumeID: String
    ) -> ReaderHandoff? {
        guard let record,
              record.volumeID == volumeID,
              record.isVerifiedOfflineCopy else { return nil }
        return ReaderHandoff(
            workID: record.workID,
            volumeID: record.volumeID,
            title: record.workTitle,
            volumeTitle: record.volumeTitle,
            format: record.format,
            readerType: record.readerType,
            source: .verifiedLocal(recordID: record.id)
        )
    }

    static func completedRecord(
        records: [ManagedDownloadRecord],
        recordID: String
    ) -> ManagedDownloadRecord? {
        records.first {
            $0.id == recordID &&
            $0.isVerifiedOfflineCopy
        }
    }
}

protocol ManagedDownloadTransferring: Sendable {
    func prepare(context: ContentRequestContext, volumeID: String) async throws -> ManagedDownloadBootstrap

    func download(
        _ request: ManagedDownloadRequest,
        progress: @escaping @Sendable (ManagedDownloadProgress) async -> Void
    ) async throws -> ManagedDownloadReceipt
}

struct UnavailableManagedDownloadTransfer: ManagedDownloadTransferring {
    func prepare(context: ContentRequestContext, volumeID: String) async throws -> ManagedDownloadBootstrap {
        throw ManagedDownloadTransferError.transportUnavailable
    }

    func download(
        _ request: ManagedDownloadRequest,
        progress: @escaping @Sendable (ManagedDownloadProgress) async -> Void
    ) async throws -> ManagedDownloadReceipt {
        throw ManagedDownloadTransferError.transportUnavailable
    }
}
