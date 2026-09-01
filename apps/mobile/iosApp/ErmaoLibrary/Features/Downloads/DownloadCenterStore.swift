import Foundation
import OSLog
@preconcurrency import ErmaoShared

struct ManagedDownloadBatchResult: Sendable {
    let succeededCount: Int
    let failedResourceIDs: Set<String>
    var failedCount: Int { failedResourceIDs.count }
}

@MainActor
final class DownloadCenterStore: ObservableObject {
    private static let readerMaterializationLogger = Logger(
        subsystem: "com.ermao.library",
        category: "Downloads"
    )

    @Published private(set) var records: [ManagedDownloadRecord] = []
    @Published private(set) var storageErrorCode: String?
    @Published private(set) var readerFailures: [String: String] = [:]
    @Published var completedSearch = ""
    #if DEBUG
    @Published var uiTestResourceFilterID: String?
    #endif

    private let repository: ManagedDownloadStore
    private let transfer: any ManagedDownloadTransferring
    private var context: ContentRequestContext?
    private var runningTasks: [String: Task<Void, Never>] = [:]
    /// Descriptors owned by Reader-started transfers. A resource key alone
    /// is not enough: a changed asset version must never be joined silently.
    private var runningReaderDescriptors: [String: DownloadDescriptor] = [:]

    init(repository: ManagedDownloadStore = ManagedDownloadStore(), transfer: any ManagedDownloadTransferring = UnavailableManagedDownloadTransfer()) {
        self.repository = repository
        self.transfer = transfer
    }

    var activeRecords: [ManagedDownloadRecord] { records.filter { [.queued, .downloading, .paused].contains($0.state) } }
    var failedRecords: [ManagedDownloadRecord] { records.filter { [.failedRetryable, .failedTerminal].contains($0.state) } }
    var completedGroups: [ManagedDownloadBookGroup] {
        #if DEBUG
        let projectedRecords = uiTestResourceFilterID.map { resourceID in
            records.filter { $0.resourceID == resourceID }
        } ?? records
        #else
        let projectedRecords = records
        #endif
        return ManagedDownloadGrouping.completed(records: projectedRecords, query: completedSearch)
    }
    var usedBytes: Int64 { records.filter(\.isVerifiedOfflineCopy).reduce(0) { $0 + $1.receivedBytes } }

    func activate(context: ContentRequestContext) {
        guard self.context?.namespaceKey != context.namespaceKey else { return }
        runningTasks.values.forEach { $0.cancel() }
        runningTasks.removeAll()
        runningReaderDescriptors.removeAll()
        self.context = context
        records = []
        readerFailures = [:]
        storageErrorCode = nil
        reload()
    }

    func cancelAllTransfers() async {
        let tasks = Array(runningTasks.values)
        runningTasks.removeAll()
        runningReaderDescriptors.removeAll()
        tasks.forEach { $0.cancel() }
        for task in tasks { await task.value }
    }

    func reload() {
        guard let context else { records = []; return }
        Task {
            do {
                let loaded = try await repository.records(namespace: context.namespaceKey)
                guard self.context?.namespaceKey == context.namespaceKey else { return }
                records = loaded; storageErrorCode = nil
            }
            catch { storageErrorCode = "DOWNLOAD_MANIFEST_READ_FAILED" }
        }
    }

    func record(for resourceID: String, assetID: String? = nil) -> ManagedDownloadRecord? {
        records.first { $0.resourceID == resourceID && (assetID == nil || $0.assetID == assetID) }
    }

    func enqueue(book: BookCard, resource: BookResource) { start(resourceID: resource.id) }

    func readerCoordinator(context: ContentRequestContext) async throws -> ReaderLaunchCoordinator {
        guard isCurrent(context) else { throw ManagedDownloadTransferError.unauthorized }
        return try await transfer.readerCoordinator(context: context, repository: repository) { [weak self] record in
            await self?.project(record)
        }
    }

    func isCurrent(_ context: ContentRequestContext) -> Bool { self.context?.namespaceKey == context.namespaceKey }

    /// Returns ownership of the transfer, not ownership of the persisted download.
    func beginReaderDownload(resourceID: String, descriptor: DownloadDescriptor) -> Bool {
        guard context != nil else { return false }
        if let activeDescriptor = runningReaderDescriptors[resourceID] {
            guard PublicKt.downloadDescriptorsMatch(expected: activeDescriptor, candidate: descriptor) else {
                return false
            }
            return false
        }
        guard runningTasks[resourceID] == nil else { return false }
        let owned = true
        runningReaderDescriptors[resourceID] = descriptor
        start(resourceID: resourceID, expectedDescriptor: descriptor)
        if runningTasks[resourceID] == nil {
            runningReaderDescriptors[resourceID] = nil
            return false
        }
        return owned
    }

    func readerRecord(
        descriptor: DownloadDescriptor,
        records candidates: [ManagedDownloadRecord]? = nil
    ) -> ManagedDownloadRecord? {
        (candidates ?? records).first { record in
            guard record.resourceID == descriptor.identity.resourceId,
                  record.assetID == descriptor.identity.assetId,
                  let encoded = record.sharedTaskJSON,
                  let task = try? DownloadCatalogCodec.shared.decode(serialized: encoded)
            else { return false }
            return task.matchesDescriptor(candidate: descriptor)
        }
    }

    func completedReaderRecord(
        descriptor: DownloadDescriptor,
        context: ContentRequestContext
    ) async throws -> ManagedDownloadRecord? {
        let candidates = try await repository.records(namespace: context.namespaceKey)
        return readerRecord(descriptor: descriptor, records: candidates).flatMap { record in
            record.isVerifiedOfflineCopy ? record : nil
        }
    }

    /// Starts or joins the canonical Reader download and waits for its exact,
    /// verified artifact. The Reader never owns a second transfer pipeline;
    /// this method is the small iOS facade used when PDFium must materialize
    /// its remote byte source.
    func awaitVerifiedReaderDownload(
        descriptor: DownloadDescriptor,
        context: ContentRequestContext
    ) async throws -> ManagedDownloadRecord {
        do {
            return try await awaitVerifiedReaderDownloadOperation(
                descriptor: descriptor,
                context: context
            )
        } catch is CancellationError {
            Self.readerMaterializationLogger.notice(
                "pdf_materialization platform=ios resource_id=\(descriptor.identity.resourceId, privacy: .public) stage=download_cancelled result=DOWNLOAD_CANCELLED bytes=\(descriptor.totalBytes, privacy: .public)"
            )
            throw CancellationError()
        } catch let error as ManagedDownloadTransferError {
            Self.readerMaterializationLogger.error(
                "pdf_materialization platform=ios resource_id=\(descriptor.identity.resourceId, privacy: .public) stage=download_failed result=\(error.stableCode, privacy: .public) bytes=\(descriptor.totalBytes, privacy: .public)"
            )
            throw error
        } catch {
            Self.readerMaterializationLogger.error(
                "pdf_materialization platform=ios resource_id=\(descriptor.identity.resourceId, privacy: .public) stage=download_failed result=DOWNLOAD_MANIFEST_READ_FAILED bytes=\(descriptor.totalBytes, privacy: .public)"
            )
            throw error
        }
    }

    private func awaitVerifiedReaderDownloadOperation(
        descriptor: DownloadDescriptor,
        context: ContentRequestContext
    ) async throws -> ManagedDownloadRecord {
        guard isCurrent(context) else { throw ManagedDownloadTransferError.unauthorized }

        if let completed = try await completedReaderRecord(descriptor: descriptor, context: context) {
            Self.readerMaterializationLogger.notice(
                "pdf_materialization platform=ios resource_id=\(descriptor.identity.resourceId, privacy: .public) stage=download_reuse result=verified_existing bytes=\(descriptor.totalBytes, privacy: .public)"
            )
            return completed
        }

        Self.readerMaterializationLogger.notice(
            "pdf_materialization platform=ios resource_id=\(descriptor.identity.resourceId, privacy: .public) stage=download_start result=join_or_start bytes=\(descriptor.totalBytes, privacy: .public)"
        )
        let joinedOrStarted = beginReaderDownload(resourceID: descriptor.identity.resourceId, descriptor: descriptor)
        if !joinedOrStarted,
           let activeDescriptor = runningReaderDescriptors[descriptor.identity.resourceId] {
            guard PublicKt.downloadDescriptorsMatch(expected: activeDescriptor, candidate: descriptor) else {
                throw ManagedDownloadTransferError.versionChanged
            }
        } else if !joinedOrStarted,
                  runningTasks[descriptor.identity.resourceId] != nil,
                  readerRecord(descriptor: descriptor) == nil {
            // A non-Reader transfer owns this resource and its descriptor is
            // not available for an exact join. Do not attach PDFium to it.
            throw ManagedDownloadTransferError.versionChanged
        }
        for await (records, failures) in $records.combineLatest($readerFailures).values {
            try Task.checkCancellation()
            guard isCurrent(context) else { throw CancellationError() }

            let record = readerRecord(descriptor: descriptor, records: records)
            if let record, record.isVerifiedOfflineCopy {
                // Re-read the persisted manifest so a projected Published
                // value can never be mistaken for an exact local artifact.
                if let completed = try await completedReaderRecord(descriptor: descriptor, context: context) {
                    Self.readerMaterializationLogger.notice(
                        "pdf_materialization platform=ios resource_id=\(descriptor.identity.resourceId, privacy: .public) stage=download_complete result=verified_artifact bytes=\(descriptor.totalBytes, privacy: .public)"
                    )
                    return completed
                }
                throw ManagedDownloadTransferError.invalidResponse
            }

            guard let record, record.state == .failedRetryable || record.state == .failedTerminal else {
                continue
            }
            let code = failures[descriptor.identity.resourceId] ?? record.stableErrorCode
            throw Self.transferError(for: code)
        }
        throw ManagedDownloadTransferError.cancelled
    }

    func pauseReaderDownload(resourceID: String) { runningTasks[resourceID]?.cancel() }

    func rebuildReaderDownload(resourceID: String, descriptor: DownloadDescriptor) async -> Bool {
        if let active = runningTasks[resourceID] {
            active.cancel()
            await active.value
        }
        guard runningTasks[resourceID] == nil else { return false }
        return beginReaderDownload(resourceID: resourceID, descriptor: descriptor)
    }

    func performBatch(book: BookCard, resources: [BookResource],
                      completion: @escaping @MainActor (ManagedDownloadBatchResult) -> Void) {
        guard context != nil else {
            completion(ManagedDownloadBatchResult(succeededCount: 0, failedResourceIDs: Set(resources.map(\.id))))
            return
        }
        let result = DownloadBatchResult(results: Set(resources.map(\.id)).sorted().map { resourceID in
            let record = record(for: resourceID)
            return DownloadBatchPolicy.shared.decide(resourceId: resourceID, status: record?.state.sharedStatus,
                failureCode: record?.stableErrorCode, active: runningTasks[resourceID] != nil)
        })
        result.requestedResourceIds.forEach { start(resourceID: $0) }
        completion(ManagedDownloadBatchResult(succeededCount: Int(result.succeededCount), failedResourceIDs: result.failedResourceIds))
    }

    func pause(_ record: ManagedDownloadRecord) { runningTasks[record.resourceID]?.cancel() }
    func resume(_ record: ManagedDownloadRecord) { start(resourceID: record.resourceID) }
    func retry(_ record: ManagedDownloadRecord) { start(resourceID: record.resourceID) }

    func remove(_ record: ManagedDownloadRecord) {
        let active = runningTasks[record.resourceID]
        active?.cancel()
        Task {
            await active?.value
            do { try await repository.remove(record); records.removeAll { $0.id == record.id } }
            catch { storageErrorCode = "DOWNLOAD_REMOVE_FAILED" }
        }
    }

    func remove(resourceID: String) { if let record = record(for: resourceID) { remove(record) } }
    func remove(bookID: String) { records.filter { $0.bookID == bookID }.forEach(remove) }
    func localFileURL(for record: ManagedDownloadRecord) async -> URL? { await repository.fileURL(for: record) }

    private func start(resourceID: String, expectedDescriptor: DownloadDescriptor? = nil) {
        guard let context, runningTasks[resourceID] == nil else { return }
        readerFailures[resourceID] = nil
        let task = Task { [weak self, repository, transfer] in
            guard let self else { return }
            defer {
                if self.context?.namespaceKey == context.namespaceKey {
                    self.runningTasks[resourceID] = nil
                    if expectedDescriptor != nil { self.runningReaderDescriptors[resourceID] = nil }
                }
            }
            do {
                try await transfer.download(context: context, resourceID: resourceID, repository: repository, expectedDescriptor: expectedDescriptor) { [weak self] record in
                    await self?.project(record)
                }
            } catch is CancellationError {
                // The shared use case persists pause before returning cancellation.
            } catch let error as ManagedDownloadTransferError {
                guard !Task.isCancelled, self.context?.namespaceKey == context.namespaceKey else { return }
                self.storageErrorCode = error.stableCode
                self.readerFailures[resourceID] = error.stableCode
            } catch {
                guard !Task.isCancelled, self.context?.namespaceKey == context.namespaceKey else { return }
                self.storageErrorCode = "DOWNLOAD_MANIFEST_WRITE_FAILED"
                self.readerFailures[resourceID] = "DOWNLOAD_MANIFEST_WRITE_FAILED"
            }
        }
        runningTasks[resourceID] = task
    }

    private func project(_ record: ManagedDownloadRecord) {
        guard context?.namespaceKey == record.namespace else { return }
        if let index = records.firstIndex(where: { $0.id == record.id }) { records[index] = record }
        else { records.append(record) }
        records.sort { $0.updatedAt > $1.updatedAt }
    }

    private static func transferError(for code: String?) -> ManagedDownloadTransferError {
        switch code {
        case "ASSET_VERSION_CHANGED": return .versionChanged
        case "DOWNLOAD_INSUFFICIENT_SPACE": return .insufficientSpace
        case "DOWNLOAD_UNAUTHORIZED": return .unauthorized
        case "DOWNLOAD_CONTENT_UNAVAILABLE": return .inaccessible
        case "DOWNLOAD_INVALID_RESPONSE", "DOWNLOAD_LOCAL_FILE_INVALID": return .invalidResponse
        case "DOWNLOAD_CANCELLED": return .cancelled
        default: return .transportUnavailable
        }
    }

}

extension ContentRequestContext {
    var downloadRequestContext: DownloadRequestContext {
        PublicKt.createDownloadRequestContext(
            profileId: profileID, displayName: profileDisplayName, baseUrl: baseURL,
            serverIdentity: serverIdentity, acceptsInsecureTls: acceptsInsecureTLS,
            userId: userID, authorizationVersion: authorizationVersion
        )
    }
}

struct CompositePrivateContentCache: PrivateContentCacheClearing {
    let coverCache: AuthenticatedCoverCache
    let downloads: ManagedDownloadStore
    let reader: (any PrivateContentCacheClearing)?

    init(
        coverCache: AuthenticatedCoverCache,
        downloads: ManagedDownloadStore,
        reader: (any PrivateContentCacheClearing)? = nil
    ) {
        self.coverCache = coverCache
        self.downloads = downloads
        self.reader = reader
    }

    func removeNamespace(_ namespace: String) async throws {
        try await coverCache.removeNamespace(namespace)
        try await downloads.removeNamespace(namespace)
        try await reader?.removeNamespace(namespace)
    }
}
