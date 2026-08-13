import Foundation
@preconcurrency import ErmaoShared

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
        let baseRevision = state.conflict?.server.revision ?? state.confirmedRevision
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
                  state.conflict == nil,
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
                try? await database.acknowledge(mutationID: pending.mutationId, snapshot: accepted.snapshot)
            case let conflict as ErmaoShared.ReaderProgressPushResultConflict:
                let value = ErmaoShared.ReaderProgressConflict(pending: pending, server: conflict.current)
                try? await database.recordConflict(value)
                return
            case is ErmaoShared.ReaderProgressPushResultRetryableFailure:
                return
            case let rejected as ErmaoShared.ReaderProgressPushResultRejected:
                try? await database.recordTerminalFailure(
                    mutationID: pending.mutationId,
                    code: rejected.failureCode
                )
                return
            default:
                try? await database.recordTerminalFailure(
                    mutationID: pending.mutationId,
                    code: "INVALID_PROGRESS_RESPONSE"
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
