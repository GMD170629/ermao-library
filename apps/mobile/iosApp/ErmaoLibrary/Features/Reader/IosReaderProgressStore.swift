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
            Task { @MainActor [weak self] in await self?.checkForRemoteProgress() }
        }
        networkMonitor.start(queue: DispatchQueue(label: "reader.progress.network"))
    }

    deinit {
        networkMonitor.cancel()
        runtime.close()
    }

    func checkForRemoteProgress() async {
        let result: ErmaoShared.ReaderProgressQueryResult
        do {
            result = try await server.load(target: target, etag: etag)
        } catch {
            return
        }
        if let current = result as? ErmaoShared.ReaderProgressQueryResultCurrent {
            etag = current.etag
            guard let snapshot = current.snapshot else { return }
            let local = try? await database.load(sourceId: target.volumeId)
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

    /// Waits for the single-flight slot so a 409 becomes visible before the
    /// next user gesture. Network failures return without clearing pending.
    func refreshAfterSave() async {
        try? await runtime.coordinator.awaitIdle()
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

    func continueStartupWithLocal(
        progress: ErmaoShared.ReaderProgress,
        serverRevision: Int64
    ) async throws {
        try await runtime.coordinator.continueStartupWithLocal(
            target: target,
            progress: progress,
            serverRevision: serverRevision
        )
    }

    func useServerForStartup(_ conflict: IosReaderStartupConflict) async throws {
        try await runtime.coordinator.discardStartupPending(
            mutationId: conflict.mutation.mutationId,
            serverRevision: conflict.server.revision
        )
    }
}

/// Durable latest-only Reader v4 synchronization for the native iOS shell.
final class IosReaderProgressStore: ErmaoShared.ReaderProgressSyncingStore, @unchecked Sendable {
    private let database: IosReaderLocalDatabase
    private let target: ErmaoShared.ReaderProgressSyncTarget
    private let uploadSlot: IosReaderProgressUploadSlot

    init(
        database: IosReaderLocalDatabase,
        target: ErmaoShared.ReaderProgressSyncTarget,
        syncPort: ErmaoShared.ReaderProgressSyncPort
    ) {
        self.database = database
        self.target = target
        uploadSlot = IosReaderProgressUploadSlot(database: database, target: target, port: syncPort)
    }

    func load(sourceId: String) async throws -> ErmaoShared.ReaderProgress? {
        try await database.load(sourceId: sourceId)
    }

    func save(progress: ErmaoShared.ReaderProgress) async throws {
        guard progress.sourceId == target.volumeId else {
            throw IosReaderFailure(code: .persistenceFailed)
        }

        let state = try await database.loadSyncState()
        let baseRevision = state.confirmedRevision
        let upload = ErmaoShared.PublicKt.createReaderProgressUpload(
            target: target,
            progress: progress,
            baseRevision: baseRevision,
            mutationId: UUID().uuidString.lowercased()
        )
        try await database.commitProgressAndPending(progress: progress, pending: upload.mutation)
        await uploadSlot.wake()
    }

    func delete(sourceId: String) async throws {
        try await database.delete(sourceId: sourceId)
    }

    func awaitPendingUpload() async throws {
        await uploadSlot.awaitIdle()
    }

    func retryPendingUpload() async throws {
        await uploadSlot.wake()
    }

    func syncState() async throws -> ErmaoShared.ReaderProgressDurableState {
        try await database.loadSyncState()
    }
}

/// Single-flight worker. The database, not actor memory, owns the latest slot.
private actor IosReaderProgressUploadSlot {
    private let database: IosReaderLocalDatabase
    private let target: ErmaoShared.ReaderProgressSyncTarget
    private let port: ErmaoShared.ReaderProgressSyncPort
    private var worker: Task<Void, Never>?

    init(
        database: IosReaderLocalDatabase,
        target: ErmaoShared.ReaderProgressSyncTarget,
        port: ErmaoShared.ReaderProgressSyncPort
    ) {
        self.database = database
        self.target = target
        self.port = port
    }

    func wake() {
        guard worker == nil else { return }
        worker = Task { await drain() }
    }

    func awaitIdle() async {
        while let active = worker { await active.value }
    }

    private func drain() async {
        defer { worker = nil }
        while !Task.isCancelled {
            guard let state = try? await database.loadSyncState(),
                  state.terminalFailureCode == nil,
                  let pending = state.pending
            else { return }
            let upload = ErmaoShared.ReaderProgressUpload(target: target, mutation: pending)
            let result: ErmaoShared.ReaderProgressPushResult
            do {
                result = try await port.push(upload: upload)
            } catch {
                return
            }
            switch result {
            case let accepted as ErmaoShared.ReaderProgressPushResultAccepted:
                try? await database.acknowledge(mutationId: pending.mutationId, snapshot: accepted.snapshot)
            case let conflict as ErmaoShared.ReaderProgressPushResultConflict:
                // The rejected mutation must never be replayed automatically. The
                // active Reader session will surface the remote snapshot and only
                // a later, genuine position change may create a replacement.
                try? await database.discardPendingAfterConflict(
                    mutationId: pending.mutationId,
                    serverRevision: conflict.current.revision
                )
                return
            case is ErmaoShared.ReaderProgressPushResultRetryableFailure:
                return
            case let rejected as ErmaoShared.ReaderProgressPushResultRejected:
                try? await database.recordTerminalFailure(
                    mutationId: pending.mutationId,
                    failureCode: rejected.failureCode
                )
                return
            default:
                try? await database.recordTerminalFailure(
                    mutationId: pending.mutationId,
                    failureCode: "INVALID_PROGRESS_RESPONSE"
                )
                return
            }
        }
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
