import Foundation

@MainActor
final class DownloadCenterStore: ObservableObject {
    @Published private(set) var records: [ManagedDownloadRecord] = []
    @Published private(set) var storageErrorCode: String?
    @Published var completedSearch = ""

    private let repository: ManagedDownloadStore
    private let transfer: any ManagedDownloadTransferring
    private var context: ContentRequestContext?
    private var runningTasks: [String: Task<Void, Never>] = [:]

    init(
        repository: ManagedDownloadStore = ManagedDownloadStore(),
        transfer: any ManagedDownloadTransferring = UnavailableManagedDownloadTransfer()
    ) {
        self.repository = repository
        self.transfer = transfer
    }

    var activeRecords: [ManagedDownloadRecord] {
        records.filter { [.queued, .downloading, .paused].contains($0.state) }
    }

    var failedRecords: [ManagedDownloadRecord] {
        records.filter { [.failedRetryable, .failedTerminal].contains($0.state) }
    }

    var completedGroups: [ManagedDownloadWorkGroup] {
        ManagedDownloadGrouping.completed(records: records, query: completedSearch)
    }

    var usedBytes: Int64 {
        records.filter(\.isVerifiedOfflineCopy).reduce(0) { $0 + $1.receivedBytes }
    }

    func activate(context: ContentRequestContext) {
        guard self.context?.namespaceKey != context.namespaceKey else { return }
        runningTasks.values.forEach { $0.cancel() }
        runningTasks.removeAll()
        self.context = context
        reload()
    }

    func cancelAllTransfers() async {
        let tasks = Array(runningTasks.values)
        runningTasks.removeAll()
        tasks.forEach { $0.cancel() }
        for task in tasks {
            await task.value
        }
    }

    func reload() {
        guard let context else { records = []; return }
        Task {
            do {
                records = try await repository.records(namespace: context.namespaceKey)
                storageErrorCode = nil
            } catch {
                storageErrorCode = "DOWNLOAD_MANIFEST_READ_FAILED"
            }
        }
    }

    func record(for volumeID: String) -> ManagedDownloadRecord? {
        records.first { $0.volumeID == volumeID }
    }

    func enqueue(work: WorkCard, volume: WorkVolume, mediaKind: LibraryMediaKind) {
        guard let context else { return }
        Task {
            do {
                let bootstrap = try await transfer.prepare(context: context, volumeID: volume.id)
                try await enqueuePrepared(
                    work: work,
                    volume: volume,
                    mediaKind: mediaKind,
                    bootstrap: bootstrap,
                    context: context
                )
            } catch {
                recordPreparationError(error)
            }
        }
    }

    @discardableResult
    func requestReaderAccess(
        work: WorkCard,
        volume: WorkVolume,
        mediaKind: LibraryMediaKind,
        completion: @escaping @MainActor (ManagedReaderAccessOutcome) -> Void
    ) -> Task<Void, Never> {
        guard let context else {
            completion(.unavailable("DOWNLOAD_CONTEXT_UNAVAILABLE"))
            return Task {}
        }
        return Task {
            do {
                let bootstrap = try await transfer.prepare(context: context, volumeID: volume.id)
                if let completed = record(for: volume.id),
                   completed.isVerifiedOfflineCopy,
                   completed.readerType == bootstrap.readerType {
                    completion(.open(ReaderHandoff(
                        workID: work.id,
                        volumeID: volume.id,
                        title: work.title,
                        volumeTitle: volume.title,
                        format: completed.format,
                        readerType: completed.readerType,
                        source: .verifiedLocal(recordID: completed.id)
                    )))
                } else if bootstrap.readerType.requiresCompleteDownloadBeforeReading {
                    if let stale = record(for: volume.id),
                       stale.readerType != bootstrap.readerType ||
                       stale.effectiveMediaVersionID != bootstrap.mediaVersionID {
                        await removeForReplacement(stale)
                    }
                    try await enqueuePrepared(
                        work: work,
                        volume: volume,
                        mediaKind: mediaKind,
                        bootstrap: bootstrap,
                        context: context
                    )
                    guard let record = record(for: volume.id) else {
                        completion(.unavailable("DOWNLOAD_MANIFEST_WRITE_FAILED"))
                        return
                    }
                    completion(.needsDownload(recordID: record.id))
                } else if bootstrap.readerType.supportsStreaming {
                    completion(.open(ReaderHandoff(
                        workID: work.id,
                        volumeID: volume.id,
                        title: work.title,
                        volumeTitle: volume.title,
                        format: volume.formatLabel,
                        readerType: bootstrap.readerType,
                        source: .remoteStream
                    )))
                } else {
                    completion(.unavailable("READER_TYPE_UNAVAILABLE"))
                }
            } catch let error as ManagedDownloadTransferError {
                completion(.unavailable(error.stableCode))
            } catch {
                completion(.unavailable("DOWNLOAD_INVALID_RESPONSE"))
            }
        }
    }

    private func removeForReplacement(_ record: ManagedDownloadRecord) async {
        runningTasks[record.id]?.cancel()
        runningTasks[record.id] = nil
        try? await repository.remove(record)
        records.removeAll { $0.id == record.id }
    }

    func pause(_ record: ManagedDownloadRecord) {
        runningTasks[record.id]?.cancel()
        runningTasks[record.id] = nil
        persist(record) { value in
            value.state = .paused
            value.stableErrorCode = nil
        }
    }

    func resume(_ record: ManagedDownloadRecord) {
        start(record)
    }

    func retry(_ record: ManagedDownloadRecord) {
        start(record)
    }

    func remove(_ record: ManagedDownloadRecord) {
        runningTasks[record.id]?.cancel()
        runningTasks[record.id] = nil
        Task {
            do {
                try await repository.remove(record)
                records.removeAll { $0.id == record.id }
            } catch {
                storageErrorCode = "DOWNLOAD_REMOVE_FAILED"
            }
        }
    }

    func localFileURL(for record: ManagedDownloadRecord) async -> URL? {
        await repository.fileURL(for: record)
    }

    private func start(_ original: ManagedDownloadRecord) {
        guard let context, runningTasks[original.id] == nil else { return }
        var record = original
        record.state = .downloading
        record.verification = .pending
        record.stableErrorCode = nil
        record.updatedAt = Date()
        replace(record)
        let recordID = record.id
        let task = Task { [weak self, repository, transfer] in
            guard let self else { return }
            do {
                try await repository.update(record)
                let destination = try await repository.destination(for: record)
                let receipt = try await transfer.download(
                    ManagedDownloadRequest(context: context, record: record, destination: destination)
                ) { [weak self] progress in
                    await self?.recordProgress(recordID: recordID, progress: progress)
                }
                try Task.checkCancellation()
                guard self.context?.namespaceKey == record.namespace,
                      self.record(for: record.volumeID)?.id == record.id else {
                    throw CancellationError()
                }
                let completed = try await repository.publish(
                    record: self.record(for: record.volumeID) ?? record,
                    destination: destination,
                    receipt: receipt
                )
                self.replace(completed)
            } catch is CancellationError {
                if self.record(for: record.volumeID)?.state != .paused {
                    self.persist(record) { value in value.state = .paused }
                }
            } catch let error as ManagedDownloadTransferError {
                self.fail(record, error: error)
            } catch {
                self.fail(record, error: .invalidResponse)
            }
            self.runningTasks[recordID] = nil
        }
        runningTasks[recordID] = task
    }

    private func enqueuePrepared(
        work: WorkCard,
        volume: WorkVolume,
        mediaKind: LibraryMediaKind,
        bootstrap: ManagedDownloadBootstrap,
        context: ContentRequestContext
    ) async throws {
        guard bootstrap.mediaVersionID == volume.mediaVersionID,
              bootstrap.mediaKind == mediaKind else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        let record = try await repository.enqueue(
            namespace: context.namespaceKey,
            work: work,
            volume: volume,
            mediaVersionID: bootstrap.mediaVersionID,
            mediaKind: mediaKind,
            readerType: bootstrap.readerType,
            expectedBytes: bootstrap.expectedBytes
        )
        replace(record)
        start(record)
    }

    private func recordPreparationError(_ error: Error) {
        if let transferError = error as? ManagedDownloadTransferError {
            storageErrorCode = transferError.stableCode
        } else {
            storageErrorCode = "DOWNLOAD_MANIFEST_WRITE_FAILED"
        }
    }

    private func recordProgress(recordID: String, progress: ManagedDownloadProgress) {
        guard let index = records.firstIndex(where: { $0.id == recordID }) else { return }
        records[index].receivedBytes = progress.receivedBytes
        records[index].expectedBytes = progress.expectedBytes
        records[index].updatedAt = Date()
    }

    private func fail(_ original: ManagedDownloadRecord, error: ManagedDownloadTransferError) {
        persist(record(for: original.volumeID) ?? original) { value in
            value.state = error == .inaccessible || error == .invalidResponse
                ? .failedTerminal
                : .failedRetryable
            value.verification = .invalid
            value.stableErrorCode = error.stableCode
        }
    }

    private func persist(
        _ record: ManagedDownloadRecord,
        mutation: @escaping (inout ManagedDownloadRecord) -> Void
    ) {
        var updated = record
        mutation(&updated)
        updated.updatedAt = Date()
        replace(updated)
        Task {
            do { try await repository.update(updated) }
            catch { storageErrorCode = "DOWNLOAD_MANIFEST_WRITE_FAILED" }
        }
    }

    private func replace(_ record: ManagedDownloadRecord) {
        if let index = records.firstIndex(where: { $0.id == record.id }) {
            records[index] = record
        } else {
            records.append(record)
        }
        records.sort { $0.updatedAt > $1.updatedAt }
    }

}

struct CompositePrivateContentCache: PrivateContentCacheClearing {
    let libraryCache: LibraryCacheStore
    let downloads: ManagedDownloadStore

    func removeNamespace(_ namespace: String) async throws {
        try await libraryCache.removeNamespace(namespace)
        try await downloads.removeNamespace(namespace)
    }
}
