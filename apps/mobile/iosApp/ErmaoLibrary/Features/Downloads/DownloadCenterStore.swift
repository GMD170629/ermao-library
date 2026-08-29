import Foundation
@preconcurrency import ErmaoShared

struct ManagedDownloadBatchResult: Sendable {
    let succeededCount: Int
    let failedResourceIDs: Set<String>
    var failedCount: Int { failedResourceIDs.count }
}

@MainActor
final class DownloadCenterStore: ObservableObject {
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
        self.context = context
        records = []
        readerFailures = [:]
        storageErrorCode = nil
        reload()
    }

    func cancelAllTransfers() async {
        let tasks = Array(runningTasks.values)
        runningTasks.removeAll()
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
        let owned = runningTasks[resourceID] == nil
        start(resourceID: resourceID, expectedDescriptor: descriptor)
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
                if self.context?.namespaceKey == context.namespaceKey { self.runningTasks[resourceID] = nil }
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
