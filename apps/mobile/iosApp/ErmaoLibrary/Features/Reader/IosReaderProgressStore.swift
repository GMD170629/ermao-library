import Foundation
import Combine
import Network
@preconcurrency import ErmaoShared

/// Session-only coordination for lifecycle checks and non-modal remote notices.
/// Durable mutations remain owned by the shared coordinator/runtime.
@MainActor
final class IosReaderProgressSessionCoordination: ObservableObject {
    @Published private(set) var remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4? {
        didSet { noticeHandler?(remoteSnapshot) }
    }
    var noticeHandler: ((ErmaoShared.ReaderProgressSnapshotV4?) -> Void)?

    let runtime: ErmaoShared.ReaderProgressSyncRuntime
    private let database: IosReaderLocalDatabase
    private let target: ErmaoShared.ReaderProgressSyncTarget
    private let server: ErmaoShared.ReaderProgressServerPort
    private let clientID: String
    private var etag: String?
    private let networkMonitor = NWPathMonitor()
    private var lifecycleTask: Task<Void, Never>?
    private var isClosed = false

    init(
        runtime: ErmaoShared.ReaderProgressSyncRuntime,
        database: IosReaderLocalDatabase,
        target: ErmaoShared.ReaderProgressSyncTarget,
        server: ErmaoShared.ReaderProgressServerPort,
        clientID: String,
        bootstrapSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    ) {
        self.runtime = runtime
        self.database = database
        self.target = target
        self.server = server
        self.clientID = clientID
        runtime.coordinator.beginSession(snapshot: bootstrapSnapshot)
        networkMonitor.pathUpdateHandler = { [weak self] path in
            guard path.status == .satisfied else { return }
            Task { @MainActor [weak self] in self?.beginDeferredSynchronization() }
        }
        networkMonitor.start(queue: DispatchQueue(label: "reader.progress.network"))
    }

    deinit {
        lifecycleTask?.cancel()
        networkMonitor.cancel()
        runtime.close()
    }

    func beginDeferredSynchronization() {
        guard !isClosed else { return }
        lifecycleTask?.cancel()
        lifecycleTask = Task { @MainActor [weak self] in
            await self?.recoverPendingAndCheckRemote()
        }
    }

    func close() {
        guard !isClosed else { return }
        isClosed = true
        lifecycleTask?.cancel()
        lifecycleTask = nil
        networkMonitor.cancel()
        runtime.close()
    }

    func checkForRemoteProgress() async {
        guard !isClosed, !Task.isCancelled else { return }
        let result: ErmaoShared.ReaderProgressQueryResult
        do {
            result = try await server.load(target: target, etag: etag)
        } catch {
            return
        }
        guard !isClosed, !Task.isCancelled else { return }
        if let current = result as? ErmaoShared.ReaderProgressQueryResultCurrent {
            etag = current.etag
            guard let snapshot = current.snapshot else { return }
            let local = try? await database.load(resourceId: target.resourceId)
            _ = try? await runtime.coordinator.observeRemoteProgress(
                snapshot: snapshot,
                currentClientId: clientID,
                currentProgress: local
            )
            remoteSnapshot = runtime.coordinator.remoteProgressNotice()?.snapshot
        } else if let unchanged = result as? ErmaoShared.ReaderProgressQueryResultUnchanged {
            etag = unchanged.etag ?? etag
        }
    }

    func recoverPendingAndCheckRemote() async {
        guard !isClosed, !Task.isCancelled else { return }
        try? await runtime.store.retryPendingUpload()
        try? await runtime.store.awaitPendingUpload()
        guard !isClosed, !Task.isCancelled else { return }
        remoteSnapshot = runtime.coordinator.remoteProgressNotice()?.snapshot
        await checkForRemoteProgress()
    }

    /// Waits for the single-flight slot so a 409 becomes visible before the
    /// next user gesture. Network failures return without clearing pending.
    func refreshAfterSave() async {
        guard !isClosed, !Task.isCancelled else { return }
        try? await runtime.coordinator.awaitIdle()
        guard !isClosed, !Task.isCancelled else { return }
        remoteSnapshot = runtime.coordinator.remoteProgressNotice()?.snapshot
    }

    func dismissRemoteNotice() {
        runtime.coordinator.dismissRemoteProgressNotice()
        remoteSnapshot = nil
    }

    func acceptVerifiedRemote(
        progress: ErmaoShared.ReaderProgress,
        snapshot: ErmaoShared.ReaderProgressSnapshotV4
    ) async throws {
        try await runtime.coordinator.acceptVerifiedRemoteProgress(progress: progress, snapshot: snapshot)
        remoteSnapshot = nil
    }

}

/// Reader content remains usable when progress persistence or synchronization
/// cannot be initialized. This store intentionally keeps those concerns inert.
final class IosNonBlockingReaderProgressStore: ErmaoShared.ReaderProgressSyncingStore, @unchecked Sendable {
    func load(resourceId _: String) async throws -> ErmaoShared.ReaderProgress? { nil }

    func load(sourceId _: String) async throws -> ErmaoShared.ReaderProgress? { nil }

    func save(progress _: ErmaoShared.ReaderProgress) async throws {}

    func delete(resourceId _: String) async throws {}

    func delete(sourceId _: String) async throws {}

    func awaitPendingUpload() async throws {}

    func retryPendingUpload() async throws {}

    func syncState() async throws -> ErmaoShared.ReaderProgressDurableState {
        ErmaoShared.ReaderProgressDurableState(
            confirmedRevision: 0,
            pending: nil,
            terminalFailureCode: nil
        )
    }
}

/// Persists exact Reader positions without creating any remote synchronization
/// work. Download Center uses this store so a verified original remains fully
/// usable when the server is unreachable.
final class IosLocalOnlyReaderProgressStore: ErmaoShared.ReaderProgressSyncingStore, @unchecked Sendable {
    private let database: IosReaderLocalDatabase

    init(database: IosReaderLocalDatabase) {
        self.database = database
    }

    func load(resourceId: String) async throws -> ErmaoShared.ReaderProgress? {
        try await database.load(resourceId: resourceId)
    }

    func load(sourceId: String) async throws -> ErmaoShared.ReaderProgress? {
        try await database.load(sourceId: sourceId)
    }

    func save(progress: ErmaoShared.ReaderProgress) async throws {
        try await database.save(progress: progress)
    }

    func delete(resourceId: String) async throws {
        try await database.delete(resourceId: resourceId)
    }

    func delete(sourceId: String) async throws {
        try await database.delete(sourceId: sourceId)
    }

    func awaitPendingUpload() async throws {}

    func retryPendingUpload() async throws {}

    func syncState() async throws -> ErmaoShared.ReaderProgressDurableState {
        try await database.loadSyncState()
    }
}

final class IosReaderDeviceIdentity: ErmaoShared.ReaderDeviceIdentity {
    private let defaults: UserDefaults
    private let key: String
    private let lock = NSLock()

    init(defaults: UserDefaults = .standard, key: String = "reader.installation.device-id") {
        self.defaults = defaults
        self.key = key
    }

    func stableDeviceId() -> String {
        lock.lock()
        defer { lock.unlock() }
        if let existing = defaults.string(forKey: key), !existing.isEmpty { return existing }
        let created = UUID().uuidString.lowercased()
        defaults.set(created, forKey: key)
        return created
    }
}
