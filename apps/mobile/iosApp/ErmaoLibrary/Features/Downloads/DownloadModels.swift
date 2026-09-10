import Foundation
@preconcurrency import ErmaoShared

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
    var sharedTaskJSON: String? = nil

    var progress: Double? {
        guard let expectedBytes, expectedBytes > 0 else { return nil }
        return min(1, max(0, Double(receivedBytes) / Double(expectedBytes)))
    }

    var isVerifiedOfflineCopy: Bool {
        state == .completed && verification == .verified && localRelativePath != nil
    }

    var effectiveArtifactKind: ManagedDownloadArtifactKind { artifactKind ?? .singleOriginalAsset }

    /// Reader admission requires the shared task descriptor because it carries
    /// the exact asset version (size + mtime) that the native manifest alone lacks.
    var verifiedSharedArtifact: CompletedDownloadArtifact? {
        let expectedArtifactKind: DownloadArtifactKind = effectiveArtifactKind == .originalPageSet
            ? .originalpageset
            : .singleoriginalasset
        guard isVerifiedOfflineCopy,
              let expectedBytes,
              let mimeType,
              let localRelativePath,
              let sharedTaskJSON,
              let task = try? DownloadCatalogCodec.shared.decode(serialized: sharedTaskJSON),
              task.id == id,
              task.status == .completed,
              task.descriptor.identity.bookId == bookID,
              task.descriptor.identity.resourceId == resourceID,
              task.descriptor.identity.assetId == assetID,
              task.descriptor.totalBytes == expectedBytes,
              task.descriptor.format.caseInsensitiveCompare(format) == .orderedSame,
              task.descriptor.source.mimeType == mimeType,
              task.descriptor.readerType.name.lowercased() == readerType.rawValue,
              task.descriptor.artifactKind == expectedArtifactKind,
              let artifact = task.artifact,
              artifact.localReference == localRelativePath,
              artifact.verifiedBytes == receivedBytes
        else { return nil }
        let taskNamespace = task.descriptor.identity.namespace_
        guard "\(taskNamespace.serverIdentity)|\(taskNamespace.userId)|\(taskNamespace.authorizationVersion)" == namespace
        else { return nil }
        return artifact
    }
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

struct ManagedDownloadDestination: Sendable {
    let partialFileURL: URL
    let finalFileURL: URL
    let finalRelativePath: String
}

enum ManagedDownloadTransferError: Error, Equatable, Sendable {
    case unauthorized
    case inaccessible
    case insufficientSpace
    case invalidResponse
    case transportUnavailable
    case cancelled
    case versionChanged

    var stableCode: String {
        switch self {
        case .unauthorized: "DOWNLOAD_UNAUTHORIZED"
        case .inaccessible: "DOWNLOAD_CONTENT_UNAVAILABLE"
        case .insufficientSpace: "DOWNLOAD_INSUFFICIENT_SPACE"
        case .invalidResponse: "DOWNLOAD_INVALID_RESPONSE"
        case .transportUnavailable: "DOWNLOAD_TRANSPORT_UNAVAILABLE"
        case .cancelled: "DOWNLOAD_CANCELLED"
        case .versionChanged: "ASSET_VERSION_CHANGED"
        }
    }
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
    var initialTargetPayload: String? = nil
}

enum ManagedReaderAccessPolicy {
    /// A remote handoff starts the launch coordinator; reflowable formats may
    /// therefore enter a managed download before the native reader opens.
    static func supportsNativeHandoff(_ handoff: ReaderHandoff) -> Bool {
        switch handoff.source {
        case .remoteStream:
            ReaderFormatSupport.shared.deliveryMode(
                readerType: handoff.readerType.rawValue,
                format: handoff.format
            ) != .unsupported
        case .verifiedLocal:
            ReaderFormatSupport.shared.canReadOriginal(readerType: handoff.readerType.rawValue, format: handoff.format)
        }
    }

    static func verifiedLocalHandoff(record: ManagedDownloadRecord?, resourceID: String) -> ReaderHandoff? {
        guard let record,
              record.resourceID == resourceID,
              record.verifiedSharedArtifact != nil
        else { return nil }
        return ReaderHandoff(
            bookID: record.bookID, resourceID: record.resourceID, assetID: record.assetID,
            title: record.bookTitle, resourceTitle: record.resourceTitle, format: record.format,
            readerType: record.readerType, source: .verifiedLocal(recordID: record.id)
        )
    }

    static func completedRecord(records: [ManagedDownloadRecord], recordID: String) -> ManagedDownloadRecord? {
        records.first { $0.id == recordID && $0.verifiedSharedArtifact != nil }
    }
}

@MainActor
protocol ManagedDownloadTransferring: Sendable {
    func readerCoordinator(context: ContentRequestContext, repository: ManagedDownloadStore,
                           changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws -> ReaderLaunchCoordinator
    func download(context: ContentRequestContext, resourceID: String, repository: ManagedDownloadStore,
                  expectedDescriptor: DownloadDescriptor?,
                  changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws
}

extension ManagedDownloadTransferring {
    func readerCoordinator(context: ContentRequestContext, repository: ManagedDownloadStore,
                           changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws -> ReaderLaunchCoordinator {
        throw ManagedDownloadTransferError.transportUnavailable
    }
}

struct UnavailableManagedDownloadTransfer: ManagedDownloadTransferring {
    func download(context: ContentRequestContext, resourceID: String, repository: ManagedDownloadStore,
                  expectedDescriptor: DownloadDescriptor?,
                  changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws {
        throw ManagedDownloadTransferError.transportUnavailable
    }
}

struct CompletedDownloadFile: Sendable {
    let fileURL: URL
    let assetID: String
    let displayTitle: String
    let bookID: String
    let resourceID: String
    let sourceFormat: String
    let byteCount: Int64
}

/// Maps iOS-owned catalog facts into the shared download-management policy.
///
/// The policy owns status and action semantics. This adapter only supplies the
/// task status, verification fact, live-transfer ownership, and server
/// availability observed by iOS.
enum DownloadManagementAdapter {
    static func taskStatus(for record: ManagedDownloadRecord?) -> DownloadTaskStatus? {
        guard let record else { return nil }
        if let encoded = record.sharedTaskJSON,
           let task = try? DownloadCatalogCodec.shared.decode(serialized: encoded),
           task.id == record.id,
           task.descriptor.identity.bookId == record.bookID,
           task.descriptor.identity.resourceId == record.resourceID,
           task.descriptor.identity.assetId == record.assetID {
            let namespace = task.descriptor.identity.namespace_
            let taskNamespace = "\(namespace.serverIdentity)|\(namespace.userId)|\(namespace.authorizationVersion)"
            if taskNamespace == record.namespace {
                return task.status
            }
        }
        return record.state.sharedStatus
    }

    static func item(
        resource: BookResource,
        record: ManagedDownloadRecord?,
        active: Bool
    ) -> DownloadManagementItem {
        DownloadManagementItem(
            resourceId: resource.id,
            status: taskStatus(for: record),
            verified: record?.verifiedSharedArtifact != nil,
            active: active,
            available: resource.isReadable == true,
            failureCode: record?.stableErrorCode
        )
    }

    static func project(
        resource: BookResource,
        record: ManagedDownloadRecord?,
        active: Bool
    ) -> DownloadManagementResource {
        DownloadManagementPolicy.shared.project(
            item: item(resource: resource, record: record, active: active)
        )
    }

    /// Creates a display-only resource for a manifest entry absent from the
    /// current server page. It deliberately remains unavailable so the shared
    /// policy can expose only actions justified by local facts (Open/Remove).
    static func catalogResource(_ record: ManagedDownloadRecord) -> BookResource {
        let byteCount = record.expectedBytes ?? record.receivedBytes
        return BookResource(
            id: record.resourceID,
            bookID: record.bookID,
            sourceNodeID: "download-catalog",
            title: record.resourceTitle,
            format: record.format,
            readerType: record.readerType.rawValue,
            sizeLabel: byteCount > 0
                ? ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file)
                : nil,
            sizeBytes: record.expectedBytes,
            progress: record.progress,
            isReadable: false,
            isSelected: false,
            sortOrder: Int.max
        )
    }
}

extension ManagedDownloadRecord {
    /// The one native manifest mapper used by both transfer callbacks and
    /// management transitions that persist a shared task.
    static func fromSharedTask(
        _ task: DownloadTask,
        previous: ManagedDownloadRecord?,
        namespace: String
    ) throws -> ManagedDownloadRecord {
        let descriptor = task.descriptor
        guard let readerType = ManagedDownloadReaderType(rawValue: descriptor.readerType.name.lowercased()) else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        let artifact = task.artifact
        return ManagedDownloadRecord(
            id: task.id,
            namespace: namespace,
            bookID: descriptor.identity.bookId,
            bookTitle: descriptor.bookTitle,
            bookAuthor: descriptor.bookAuthor,
            resourceID: descriptor.identity.resourceId,
            resourceTitle: descriptor.resourceTitle,
            assetID: descriptor.identity.assetId,
            format: descriptor.format.uppercased(),
            mimeType: descriptor.source.mimeType,
            readerType: readerType,
            state: Self.nativeState(for: task.status),
            verification: artifact == nil ? .pending : .verified,
            expectedBytes: descriptor.totalBytes,
            artifactKind: descriptor.artifactKind == .originalpageset ? .originalPageSet : .singleOriginalAsset,
            receivedBytes: task.transferredBytes,
            localRelativePath: artifact?.localReference,
            stableErrorCode: task.failureCode,
            createdAt: previous?.createdAt ?? Date(),
            updatedAt: Date(),
            completedAt: artifact.map { Date(timeIntervalSince1970: Double($0.completedAtEpochMillis) / 1000) },
            lastOpenedAt: previous?.lastOpenedAt,
            sharedTaskJSON: DownloadCatalogCodec.shared.encode(task: task)
        )
    }

    private static func nativeState(for status: DownloadTaskStatus) -> ManagedDownloadState {
        switch status {
        case .queued: .queued
        case .downloading: .downloading
        case .paused, .waitingforwifi: .paused
        case .completed: .completed
        case .failedretryable, .insufficientspace: .failedRetryable
        case .failedterminal, .cancelled: .failedTerminal
        default: .failedTerminal
        }
    }
}

protocol CompletedDownloadProviding: Sendable {
    func completedFile(recordID: String, namespace: String) async throws -> CompletedDownloadFile?
}
