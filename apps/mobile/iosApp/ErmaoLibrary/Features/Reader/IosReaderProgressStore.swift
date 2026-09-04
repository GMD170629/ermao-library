import Foundation
import Combine
import Network
@preconcurrency import ErmaoShared

/// Session-only coordination for lifecycle checks and non-modal remote notices.
/// Durable mutations remain owned by the shared coordinator/runtime.
@MainActor
final class IosReaderProgressSessionCoordination: ObservableObject {
    @Published private(set) var remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV5? {
        didSet { noticeHandler?(remoteSnapshot) }
    }
    var noticeHandler: ((ErmaoShared.ReaderProgressSnapshotV5?) -> Void)?

    let runtime: ErmaoShared.ReaderPositionSyncRuntime
    private let database: IosReaderLocalDatabase
    private let target: ErmaoShared.ReaderProgressSyncTarget
    private let server: ErmaoShared.ReaderPositionServerPort
    private let clientID: String
    private var etag: String?
    private let networkMonitor = NWPathMonitor()
    private var lifecycleTask: Task<Void, Never>?
    private var isClosed = false
    private var networkMonitorStarted = false

    init(
        runtime: ErmaoShared.ReaderPositionSyncRuntime,
        database: IosReaderLocalDatabase,
        target: ErmaoShared.ReaderProgressSyncTarget,
        server: ErmaoShared.ReaderPositionServerPort,
        clientID: String,
        bootstrapSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
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
    }

    deinit {
        lifecycleTask?.cancel()
        networkMonitor.cancel()
        runtime.close()
    }

    func beginDeferredSynchronization() {
        guard !isClosed else { return }
        startNetworkMonitorIfNeeded()
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
        defer { startNetworkMonitorIfNeeded() }
        let result: ErmaoShared.ReaderPositionQueryResult
        do {
            result = try await server.load(target: target, etag: etag)
        } catch {
            return
        }
        guard !isClosed, !Task.isCancelled else { return }
        if let current = result as? ErmaoShared.ReaderPositionQueryResultCurrent {
            etag = current.etag
            guard let snapshot = current.snapshot else { return }
            _ = try? await runtime.coordinator.observeRemotePosition(
                snapshot: snapshot,
                currentClientId: clientID
            )
            remoteSnapshot = runtime.coordinator.remotePositionNotice()?.snapshot
        } else if let unchanged = result as? ErmaoShared.ReaderPositionQueryResultUnchanged {
            etag = unchanged.etag ?? etag
        }
    }

    func recoverPendingAndCheckRemote() async {
        guard !isClosed, !Task.isCancelled else { return }
        startNetworkMonitorIfNeeded()
        try? await runtime.store.retryPendingUpload()
        try? await runtime.store.awaitPendingUpload()
        guard !isClosed, !Task.isCancelled else { return }
        remoteSnapshot = runtime.coordinator.remotePositionNotice()?.snapshot
        await checkForRemoteProgress()
    }

    /// Waits for the single-flight slot. Network failures return without
    /// clearing the latest pending v5 mutation.
    func refreshAfterSave() async {
        guard !isClosed, !Task.isCancelled else { return }
        try? await runtime.coordinator.awaitIdle()
        guard !isClosed, !Task.isCancelled else { return }
        remoteSnapshot = runtime.coordinator.remotePositionNotice()?.snapshot
    }

    func dismissRemoteNotice() {
        runtime.coordinator.dismissRemotePositionNotice()
        remoteSnapshot = nil
    }

    func acceptRemote(
        position: ErmaoShared.ReaderPositionLocalState,
        snapshot: ErmaoShared.ReaderProgressSnapshotV5
    ) async throws {
        try await runtime.coordinator.acceptRemotePosition(position: position, snapshot: snapshot)
        remoteSnapshot = nil
    }

    /// The first network recovery is intentionally deferred until a Reader
    /// session has finished selecting its startup location.  Starting the
    /// monitor in init could acknowledge the durable pending mutation while
    /// restore() was still reading it, making an older bootstrap snapshot win
    /// the explicit v5 priority on a cold open.
    private func startNetworkMonitorIfNeeded() {
        guard !networkMonitorStarted, !isClosed else { return }
        networkMonitorStarted = true
        networkMonitor.start(queue: DispatchQueue(label: "reader.progress.network"))
    }

}

/// Reader content remains usable when progress persistence or synchronization
/// cannot be initialized. This store intentionally keeps those concerns inert.
final class IosNonBlockingReaderProgressStore: ErmaoShared.ReaderPositionSyncingStore, @unchecked Sendable {
    func load(resourceId _: String) async throws -> ErmaoShared.ReaderPositionLocalState? { nil }

    func save(position _: ErmaoShared.ReaderPositionLocalState) async throws {}

    func delete(resourceId _: String) async throws {}

    func awaitPendingUpload() async throws {}

    func retryPendingUpload() async throws {}

    func syncState() async throws -> ErmaoShared.ReaderPositionDurableState {
        ErmaoShared.ReaderPositionDurableState(
            confirmedRevision: 0,
            pending: nil,
            terminalFailureCode: nil
        )
    }
}

/// Persists exact Reader positions without creating any remote synchronization
/// work. Download Center uses this store so a verified original remains fully
/// usable when the server is unreachable.
final class IosLocalOnlyReaderProgressStore: ErmaoShared.ReaderPositionSyncingStore, @unchecked Sendable {
    private let database: IosReaderLocalDatabase

    init(database: IosReaderLocalDatabase) {
        self.database = database
    }

    func load(resourceId: String) async throws -> ErmaoShared.ReaderPositionLocalState? {
        try await database.loadPosition(resourceId: resourceId)
    }

    func save(position: ErmaoShared.ReaderPositionLocalState) async throws {
        try await database.savePosition(position: position)
    }

    func delete(resourceId: String) async throws {
        try await database.deletePosition(resourceId: resourceId)
    }

    func awaitPendingUpload() async throws {}

    func retryPendingUpload() async throws {}

    func syncState() async throws -> ErmaoShared.ReaderPositionDurableState {
        try await database.loadPositionSyncState()
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
