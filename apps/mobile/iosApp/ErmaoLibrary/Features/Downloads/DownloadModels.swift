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
    let workID: String
    let workTitle: String
    let workAuthor: String
    /// Nil only for manifests written before media-version grouping shipped.
    let mediaVersionID: String?
    let volumeID: String
    let volumeTitle: String
    let format: String
    let mediaKind: LibraryMediaKind
    let readerType: ManagedDownloadReaderType
    var state: ManagedDownloadState
    var verification: ManagedDownloadVerification
    var contentFingerprint: String?
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

    var effectiveMediaVersionID: String {
        guard let value = mediaVersionID?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return "legacy-volume:\(volumeID)"
        }
        return value
    }
}

struct ManagedDownloadMediaVersionGroup: Identifiable, Equatable, Sendable {
    let mediaVersionID: String
    let mediaKind: LibraryMediaKind
    let records: [ManagedDownloadRecord]

    var id: String { mediaVersionID }
    var totalBytes: Int64 { records.reduce(0) { $0 + $1.receivedBytes } }
}

struct ManagedDownloadWorkGroup: Identifiable, Equatable, Sendable {
    let workID: String
    let title: String
    let author: String
    let mediaVersions: [ManagedDownloadMediaVersionGroup]

    var id: String { workID }
    var totalBytes: Int64 { mediaVersions.reduce(0) { $0 + $1.totalBytes } }
}

enum ManagedDownloadGrouping {
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
            var versions: [ManagedDownloadMediaVersionGroup] = []
            for (mediaVersionID, versionRecords) in Dictionary(
                grouping: workRecords,
                by: \.effectiveMediaVersionID
            ) {
                guard let firstVersion = versionRecords.first else { continue }
                versions.append(ManagedDownloadMediaVersionGroup(
                    mediaVersionID: mediaVersionID,
                    mediaKind: firstVersion.mediaKind,
                    records: versionRecords.sorted {
                        $0.volumeTitle.localizedStandardCompare($1.volumeTitle) == .orderedAscending
                    }
                ))
            }
            versions.sort {
                let lhs = mediaKindSortOrder($0.mediaKind)
                let rhs = mediaKindSortOrder($1.mediaKind)
                return lhs == rhs ? $0.mediaVersionID < $1.mediaVersionID : lhs < rhs
            }
            workGroups.append(ManagedDownloadWorkGroup(
                    workID: workID,
                    title: first.workTitle,
                    author: first.workAuthor,
                    mediaVersions: versions
            ))
        }
        return workGroups.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
    }

    private static func mediaKindSortOrder(_ kind: LibraryMediaKind) -> Int {
        switch kind {
        case .ebook: 0
        case .comic: 1
        case .audiobook: 2
        }
    }
}

struct ManagedDownloadRequest: Sendable {
    let context: ContentRequestContext
    let record: ManagedDownloadRecord
    let destination: ManagedDownloadDestination
}

struct ManagedDownloadBootstrap: Sendable {
    let mediaVersionID: String
    let mediaKind: LibraryMediaKind
    let readerType: ManagedDownloadReaderType
    let contentFingerprint: String
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
    let contentFingerprint: String
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
    case needsDownload(recordID: String, contentFingerprint: String)
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
        recordID: String,
        contentFingerprint: String
    ) -> ManagedDownloadRecord? {
        records.first {
            $0.id == recordID &&
            $0.isVerifiedOfflineCopy &&
            $0.contentFingerprint == contentFingerprint
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
