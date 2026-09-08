import Foundation
import OSLog
@preconcurrency import ErmaoShared

@MainActor
final class DownloadCenterStore: ObservableObject {
    private static let readerMaterializationLogger = Logger(
        subsystem: "com.ermao.library",
        category: "Downloads"
    )

    @Published private(set) var records: [ManagedDownloadRecord] = []
    @Published private(set) var storageErrorCode: String?
    @Published private(set) var readerFailures: [String: String] = [:]
    @Published private(set) var activeManagementResourceIDs: Set<String> = []
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
        activeManagementResourceIDs.removeAll()
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
        activeManagementResourceIDs.removeAll()
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
            catch {
                guard self.context?.namespaceKey == context.namespaceKey else { return }
                storageErrorCode = "DOWNLOAD_MANIFEST_READ_FAILED"
            }
        }
    }

    func record(for resourceID: String, assetID: String? = nil) -> ManagedDownloadRecord? {
        records.first { $0.resourceID == resourceID && (assetID == nil || $0.assetID == assetID) }
    }

    func managementResource(for resource: BookResource) -> DownloadManagementResource {
        DownloadManagementAdapter.project(
            resource: resource,
            record: record(for: resource.id),
            active: activeManagementResourceIDs.contains(resource.id)
        )
    }

    func managementResources(for resources: [BookResource]) -> [DownloadManagementResource] {
        var seen = Set<String>()
        return resources.compactMap { resource in
            guard seen.insert(resource.id).inserted else { return nil }
            return managementResource(for: resource)
        }
    }

    /// Reloads the current namespace before an action is evaluated. A failed
    /// read leaves the in-memory records visible so a network or manifest
    /// failure cannot erase known rows from the management sheet.
    @discardableResult
    func reloadAndAwait(expectedNamespace: String? = nil) async -> Bool {
        guard let currentContext = context else {
            records = []
            return false
        }
        guard expectedNamespace == nil || expectedNamespace == currentContext.namespaceKey else { return false }
        let namespace = expectedNamespace ?? currentContext.namespaceKey
        do {
            let loaded = try await repository.records(namespace: namespace)
            guard self.context?.namespaceKey == namespace else { return false }
            records = loaded
            storageErrorCode = nil
            return true
        } catch {
            guard self.context?.namespaceKey == namespace else { return false }
            storageErrorCode = "DOWNLOAD_MANIFEST_READ_FAILED"
            return false
        }
    }

    /// Executes one shared management action for each selected resource. The
    /// policy is re-evaluated immediately before every item so a batch cannot
    /// apply a stale action after an earlier item changes the catalog.
    func executeManagement(
        action: DownloadManagementAction,
        selectedResourceIDs: Set<String>,
        resources: [BookResource],
        expectedNamespace: String? = nil
    ) async -> [DownloadManagementResult] {
        guard !selectedResourceIDs.isEmpty else { return [] }
        guard let currentContext = context,
              expectedNamespace == nil || expectedNamespace == currentContext.namespaceKey else {
            let outcome: DownloadManagementOutcome = .skipped
            return selectedResourceIDs.sorted().map {
                managementResult(resourceID: $0, action: action, outcome: outcome)
            }
        }
        let namespace = expectedNamespace ?? currentContext.namespaceKey
        guard await reloadAndAwait(expectedNamespace: namespace) else {
            let outcome: DownloadManagementOutcome = context?.namespaceKey == namespace ? .failed : .skipped
            let code: String? = outcome == .failed ? "DOWNLOAD_MANIFEST_READ_FAILED" : nil
            return selectedResourceIDs.sorted().map {
                managementResult(resourceID: $0, action: action, outcome: outcome, failureCode: code)
            }
        }
        var resourceByID: [String: BookResource] = [:]
        for resource in resources { resourceByID[resource.id] = resource }
        var results: [DownloadManagementResult] = []
        for resourceID in selectedResourceIDs.sorted() {
            guard context?.namespaceKey == namespace else {
                results.append(managementResult(resourceID: resourceID, action: action, outcome: .skipped))
                continue
            }
            guard await reloadAndAwait(expectedNamespace: namespace) else {
                let outcome: DownloadManagementOutcome = context?.namespaceKey == namespace ? .failed : .skipped
                results.append(managementResult(
                    resourceID: resourceID,
                    action: action,
                    outcome: outcome,
                    failureCode: outcome == .failed ? "DOWNLOAD_MANIFEST_READ_FAILED" : nil
                ))
                continue
            }
            guard resourceByID[resourceID] != nil else {
                results.append(managementResult(resourceID: resourceID, action: action, outcome: .skipped))
                continue
            }
            let latestResources = managementResources(for: resources)
            let applicable = DownloadManagementPolicy.shared.applicable(
                action: action,
                selectedResourceIds: [resourceID],
                resources: latestResources
            )
            guard applicable.contains(resourceID) else {
                results.append(managementResult(resourceID: resourceID, action: action, outcome: .skipped))
                continue
            }
            results.append(await executeApplicableManagementAction(
                action: action,
                resourceID: resourceID,
                expectedNamespace: namespace
            ))
        }
        return results
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

    func pause(_ record: ManagedDownloadRecord) { runningTasks[record.resourceID]?.cancel() }
    func resume(_ record: ManagedDownloadRecord) { start(resourceID: record.resourceID) }
    func retry(_ record: ManagedDownloadRecord) { start(resourceID: record.resourceID) }

    func verifiedReaderHandoff(resourceID: String, expectedNamespace: String? = nil) async -> ReaderHandoff? {
        guard let record = record(for: resourceID),
              expectedNamespace == nil || record.namespace == expectedNamespace,
              record.isVerifiedOfflineCopy,
              await repository.fileURL(for: record) != nil
        else { return nil }
        guard expectedNamespace == nil || context?.namespaceKey == expectedNamespace else { return nil }
        return ManagedReaderAccessPolicy.verifiedLocalHandoff(record: record, resourceID: resourceID)
    }

    private func executeApplicableManagementAction(
        action: DownloadManagementAction,
        resourceID: String,
        expectedNamespace: String
    ) async -> DownloadManagementResult {
        do {
            switch action {
            case .download, .resume, .retry:
                let accepted = start(resourceID: resourceID) != nil
                return managementResult(
                    resourceID: resourceID,
                    action: action,
                    outcome: accepted ? .accepted : .skipped
                )
            case .pause:
                let completed = try await pauseManagementDownload(resourceID: resourceID, expectedNamespace: expectedNamespace)
                return managementResult(
                    resourceID: resourceID,
                    action: action,
                    outcome: completed ? .completed : .skipped
                )
            case .remove:
                let result = try await removeManagementDownload(resourceID: resourceID, expectedNamespace: expectedNamespace)
                return managementResult(
                    resourceID: resourceID,
                    action: action,
                    outcome: result.outcome,
                    failureCode: result.failureCode
                )
            case .open:
                guard context?.namespaceKey == expectedNamespace else {
                    return managementResult(resourceID: resourceID, action: action, outcome: .skipped)
                }
                let canOpen = await verifiedReaderHandoff(resourceID: resourceID, expectedNamespace: expectedNamespace) != nil
                guard context?.namespaceKey == expectedNamespace else {
                    return managementResult(resourceID: resourceID, action: action, outcome: .skipped)
                }
                return managementResult(
                    resourceID: resourceID,
                    action: action,
                    outcome: canOpen ? .completed : .failed,
                    failureCode: canOpen ? nil : "DOWNLOAD_LOCAL_FILE_INVALID"
                )
            default:
                return managementResult(resourceID: resourceID, action: action, outcome: .skipped)
            }
        } catch is CancellationError {
            return managementResult(resourceID: resourceID, action: action, outcome: .skipped)
        } catch let error as ManagedDownloadTransferError {
            guard context?.namespaceKey == expectedNamespace else {
                return managementResult(resourceID: resourceID, action: action, outcome: .skipped)
            }
            storageErrorCode = error.stableCode
            return managementResult(
                resourceID: resourceID,
                action: action,
                outcome: .failed,
                failureCode: error.stableCode
            )
        } catch {
            guard context?.namespaceKey == expectedNamespace else {
                return managementResult(resourceID: resourceID, action: action, outcome: .skipped)
            }
            storageErrorCode = "DOWNLOAD_MANIFEST_WRITE_FAILED"
            return managementResult(
                resourceID: resourceID,
                action: action,
                outcome: .failed,
                failureCode: "DOWNLOAD_MANIFEST_WRITE_FAILED"
            )
        }
    }

    private func pauseManagementDownload(resourceID: String, expectedNamespace: String) async throws -> Bool {
        guard context?.namespaceKey == expectedNamespace else {
            throw ManagedDownloadTransferError.unauthorized
        }
        if let active = runningTasks[resourceID] {
            active.cancel()
            await active.value
        }
        guard let context, context.namespaceKey == expectedNamespace, isCurrent(context) else {
            throw ManagedDownloadTransferError.unauthorized
        }
        let loaded = try await repository.records(namespace: expectedNamespace)
        guard self.context?.namespaceKey == expectedNamespace else {
            throw ManagedDownloadTransferError.unauthorized
        }
        guard let record = loaded.first(where: { $0.resourceID == resourceID }) else { return false }
        guard let encoded = record.sharedTaskJSON,
              let task = try? DownloadCatalogCodec.shared.decode(serialized: encoded)
        else { return record.state == .paused }

        switch task.status {
        case .paused, .waitingforwifi:
            return true
        case .queued, .downloading:
            let pausedTask = try PublicKt.pauseDownloadTask(task: task)
            let pausedRecord = try ManagedDownloadRecord.fromSharedTask(
                pausedTask,
                previous: record,
                namespace: expectedNamespace
            )
            try await repository.update(pausedRecord)
            guard self.context?.namespaceKey == expectedNamespace else {
                throw ManagedDownloadTransferError.unauthorized
            }
            project(pausedRecord)
            return true
        default:
            return false
        }
    }

    private func removeManagementDownload(
        resourceID: String,
        expectedNamespace: String,
        recordID: String? = nil
    ) async throws -> (outcome: DownloadManagementOutcome, failureCode: String?) {
        guard context?.namespaceKey == expectedNamespace else {
            throw ManagedDownloadTransferError.unauthorized
        }

        // Read before cancelling so an old Download Center row cannot cancel
        // a newer task for the same resource. Panel removal passes nil and
        // intentionally targets every current record for that resource.
        let beforeCancel = try await repository.records(namespace: expectedNamespace)
        guard self.context?.namespaceKey == expectedNamespace else {
            throw ManagedDownloadTransferError.unauthorized
        }
        let beforeTargets = beforeCancel.filter { record in
            record.resourceID == resourceID && (recordID == nil || record.id == recordID)
        }
        let hadActiveTask = runningTasks[resourceID] != nil
        guard !beforeTargets.isEmpty || (recordID == nil && hadActiveTask) else {
            return (.skipped, nil)
        }

        let shouldCancel = recordID == nil || beforeTargets.contains {
            $0.state == .queued || $0.state == .downloading
        }
        if shouldCancel, let active = runningTasks[resourceID] {
            active.cancel()
            await active.value
        }
        guard let context, context.namespaceKey == expectedNamespace, isCurrent(context) else {
            throw ManagedDownloadTransferError.unauthorized
        }
        let loaded = try await repository.records(namespace: expectedNamespace)
            .filter { record in
                record.resourceID == resourceID && (recordID == nil || record.id == recordID)
            }
        guard self.context?.namespaceKey == expectedNamespace else {
            throw ManagedDownloadTransferError.unauthorized
        }
        guard !loaded.isEmpty else {
            return hadActiveTask && recordID == nil ? (.completed, nil) : (.skipped, nil)
        }

        var removedIDs = Set<String>()
        var failureCode: String?
        for record in loaded {
            guard self.context?.namespaceKey == expectedNamespace else {
                throw ManagedDownloadTransferError.unauthorized
            }
            do {
                try await repository.remove(record)
                removedIDs.insert(record.id)
            } catch {
                failureCode = "DOWNLOAD_REMOVE_FAILED"
            }
        }
        guard self.context?.namespaceKey == expectedNamespace else {
            throw ManagedDownloadTransferError.unauthorized
        }
        records.removeAll { removedIDs.contains($0.id) }
        guard let failureCode else { return (.completed, nil) }
        storageErrorCode = failureCode
        return (.failed, failureCode)
    }

    private func managementResult(
        resourceID: String,
        action: DownloadManagementAction,
        outcome: DownloadManagementOutcome,
        failureCode: String? = nil
    ) -> DownloadManagementResult {
        DownloadManagementResult(
            resourceId: resourceID,
            action: action,
            outcome: outcome,
            failureCode: failureCode
        )
    }

    func remove(_ record: ManagedDownloadRecord) {
        guard context?.namespaceKey == record.namespace else { return }
        Task {
            do {
                let result = try await removeManagementDownload(
                    resourceID: record.resourceID,
                    expectedNamespace: record.namespace,
                    recordID: record.id
                )
                if result.outcome == .failed,
                   self.context?.namespaceKey == record.namespace {
                    storageErrorCode = result.failureCode
                }
            } catch let error as ManagedDownloadTransferError {
                if self.context?.namespaceKey == record.namespace { storageErrorCode = error.stableCode }
            } catch {
                if self.context?.namespaceKey == record.namespace { storageErrorCode = "DOWNLOAD_REMOVE_FAILED" }
            }
        }
    }

    func remove(resourceID: String) { if let record = record(for: resourceID) { remove(record) } }
    func remove(bookID: String) { records.filter { $0.bookID == bookID }.forEach(remove) }
    func localFileURL(for record: ManagedDownloadRecord) async -> URL? { await repository.fileURL(for: record) }

    @discardableResult
    private func start(resourceID: String, expectedDescriptor: DownloadDescriptor? = nil) -> Task<Void, Never>? {
        guard let context, runningTasks[resourceID] == nil else { return nil }
        readerFailures[resourceID] = nil
        let task = Task { [weak self, repository, transfer] in
            guard let self else { return }
            defer {
                if self.context?.namespaceKey == context.namespaceKey {
                    self.runningTasks[resourceID] = nil
                    self.activeManagementResourceIDs.remove(resourceID)
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
        activeManagementResourceIDs.insert(resourceID)
        return task
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
