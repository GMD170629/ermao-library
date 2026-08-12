import Foundation
@preconcurrency import ErmaoShared

/// Reader v4 exact-local persistence plus a deliberately ephemeral upload slot.
/// A save is durable as soon as SQLite succeeds. The subsequent PUT has no
/// disk-backed outbox, retry, lease, quarantine, or sequence state.
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
        uploadSlot = IosReaderProgressUploadSlot(port: syncPort)
    }

    func load(sourceId: String) async throws -> ErmaoShared.ReaderProgress? {
        try await database.load(sourceId: sourceId)
    }

    func save(progress: ErmaoShared.ReaderProgress) async throws {
        guard progress.sourceId == target.volumeId,
              let location = progress.location as? ErmaoShared.ReflowReaderLocation
        else { throw IosReaderFailure(code: .persistenceFailed) }

        // The exact local write is the only durability boundary. Upload is
        // offered only after it commits, and a failed PUT is intentionally lost.
        try await database.save(progress: progress)
        let upload = ErmaoShared.PublicKt.createReaderProgressUpload(
            target: target,
            progress: progress
        )
        await uploadSlot.offer(upload)
    }

    func delete(sourceId: String) async throws {
        try await database.delete(sourceId: sourceId)
    }

    func awaitPendingUpload() async throws {
        await uploadSlot.awaitIdle()
    }
}

/// One request may be in flight. Any number of locations arriving during that
/// request collapse into one latest pending upload. Success and failure both
/// consume the attempted value; there is no retry path.
private actor IosReaderProgressUploadSlot {
    private let port: ErmaoShared.ReaderProgressSyncPort
    private var latest: ErmaoShared.ReaderProgressUpload?
    private var worker: Task<Void, Never>?

    init(port: ErmaoShared.ReaderProgressSyncPort) {
        self.port = port
    }

    func offer(_ upload: ErmaoShared.ReaderProgressUpload) {
        latest = upload
        guard worker == nil else { return }
        worker = Task { await drain() }
    }

    func awaitIdle() async {
        while let active = worker { await active.value }
    }

    private func drain() async {
        while let selected = latest {
            latest = nil
            _ = try? await port.push(upload: selected)
        }
        worker = nil
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
