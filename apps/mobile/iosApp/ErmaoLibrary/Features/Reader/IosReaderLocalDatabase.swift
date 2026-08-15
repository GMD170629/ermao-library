import CryptoKit
import Foundation
import SQLite3
@preconcurrency import ErmaoShared

/// Durable, device-local exact Reader positions.
///
/// The owner key deliberately excludes authorizationVersion so a successful
/// reauthentication cannot hide the position stored on this installation.
/// Exact progress and the latest pending mutation share one DB.
final class IosReaderLocalDatabase: ErmaoShared.ReaderProgressSyncStateStore, @unchecked Sendable {
    private let worker: IosReaderLocalDatabaseWorker

    init(
        identity: ErmaoShared.ReaderLocalProgressIdentity,
        databaseURL: URL? = nil,
        legacyProgressRoot: URL? = nil,
        fileManager: FileManager = .default
    ) throws {
        worker = try IosReaderLocalDatabaseWorker(
            identity: identity,
            databaseURL: databaseURL,
            legacyProgressRoot: legacyProgressRoot,
            fileManager: SendableFileManager(fileManager)
        )
    }

    func load(sourceId: String) async throws -> ErmaoShared.ReaderProgress? {
        try await worker.load(sourceID: sourceId).value
    }

    func save(progress: ErmaoShared.ReaderProgress) async throws {
        try await worker.save(SendableReaderProgress(progress))
    }

    func delete(sourceId: String) async throws {
        try await worker.delete(sourceID: sourceId)
    }

    func loadSyncState() async throws -> ErmaoShared.ReaderProgressDurableState {
        try await worker.loadSyncState().value
    }

    func commitProgressAndPending(
        progress: ErmaoShared.ReaderProgress,
        pending: ErmaoShared.ReaderProgressMutation
    ) async throws {
        try await worker.commitProgressAndPending(
            SendableReaderProgress(progress),
            pending: SendableProgressMutation(value: pending)
        )
    }

    func acknowledge(mutationId: String, snapshot: ErmaoShared.ReaderProgressSnapshotV4) async throws {
        try await worker.acknowledge(mutationID: mutationId, snapshot: SendableProgressSnapshot(value: snapshot))
    }

    func discardPendingAfterConflict(mutationId: String, serverRevision: Int64) async throws {
        try await worker.discardPendingAfterConflict(
            mutationID: mutationId,
            serverRevision: serverRevision
        )
    }

    func acceptRemoteProgress(
        progress: ErmaoShared.ReaderProgress,
        snapshot: ErmaoShared.ReaderProgressSnapshotV4
    ) async throws {
        try await worker.acceptRemoteProgress(
            SendableReaderProgress(progress),
            snapshot: SendableProgressSnapshot(value: snapshot)
        )
    }

    func recordTerminalFailure(mutationId: String, failureCode: String) async throws {
        try await worker.recordTerminalFailure(mutationID: mutationId, code: failureCode)
    }
}

private struct SendableFileManager: @unchecked Sendable {
    let value: FileManager

    init(_ value: FileManager) {
        self.value = value
    }
}

private struct SendableReaderProgress: @unchecked Sendable {
    let value: ErmaoShared.ReaderProgress

    init(_ value: ErmaoShared.ReaderProgress) {
        self.value = value
    }
}

private struct SendableOptionalReaderProgress: @unchecked Sendable {
    let value: ErmaoShared.ReaderProgress?
}

private struct SendableSyncState: @unchecked Sendable { let value: ErmaoShared.ReaderProgressDurableState }
private struct SendableProgressMutation: @unchecked Sendable { let value: ErmaoShared.ReaderProgressMutation }
private struct SendableProgressSnapshot: @unchecked Sendable { let value: ErmaoShared.ReaderProgressSnapshotV4 }

private actor IosReaderLocalDatabaseWorker {
    private static let maximumDocumentBytes = 1_048_576
    private static let sqliteTransient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private let ownerKey: String
    private let clientID: String
    private let sourceID: String
    private let legacyProgressRoot: URL
    private let databaseURL: URL
    private let fileManager: FileManager
    private let progressCodec = ErmaoShared.PublicKt.createReaderProgressJson()
    private let syncCodec = ErmaoShared.PublicKt.createReaderProgressSyncStateJson()
    private nonisolated(unsafe) var database: OpaquePointer?
    private var initialized = false

    init(
        identity: ErmaoShared.ReaderLocalProgressIdentity,
        databaseURL: URL?,
        legacyProgressRoot: URL?,
        fileManager: SendableFileManager
    ) throws {
        guard !identity.stableKey.isEmpty else { throw IosReaderFailure(code: .persistenceFailed) }
        ownerKey = identity.stableKey
        clientID = identity.clientId
        sourceID = identity.volumeId
        let manager = fileManager.value
        self.fileManager = manager

        let url: URL
        let defaultLegacyRoot: URL
        if let databaseURL {
            url = databaseURL
            defaultLegacyRoot = databaseURL.deletingLastPathComponent()
                .appendingPathComponent("Progress", isDirectory: true)
        } else {
            let support = try manager.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            let directory = support.appendingPathComponent("Reader", isDirectory: true)
            try manager.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
            )
            url = directory.appendingPathComponent("Reader.sqlite3")
            defaultLegacyRoot = directory.appendingPathComponent("Progress", isDirectory: true)
        }
        self.legacyProgressRoot = legacyProgressRoot ?? defaultLegacyRoot
        self.databaseURL = url

        guard sqlite3_open_v2(
            url.path,
            &database,
            SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX,
            nil
        ) == SQLITE_OK else {
            if let database { sqlite3_close(database) }
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    deinit {
        if let database { sqlite3_close(database) }
    }

    func load(sourceID: String) throws -> SendableOptionalReaderProgress {
        try initializeIfNeeded()
        guard sourceID == self.sourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        if let payload = try scalarText(
            "SELECT progress_document FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
            bindings: [.text(ownerKey), .text(sourceID)]
        ) {
            let progress: ErmaoShared.ReaderProgress
            do {
                progress = try decodeProgress(payload, expectedSourceID: sourceID)
            } catch {
                try discardCurrentContractState()
                return SendableOptionalReaderProgress(value: nil)
            }
            try requireIdentity(progress)
            return SendableOptionalReaderProgress(value: progress)
        }
        return SendableOptionalReaderProgress(value: try migrateLegacyProgressFile(sourceID: sourceID))
    }

    func save(_ progressTransfer: SendableReaderProgress) throws {
        try initializeIfNeeded()
        let progress = progressTransfer.value
        try requireIdentity(progress)
        try withTransaction { try saveProgress(progress, ownerKey: ownerKey, preferNewer: false) }
    }

    func loadSyncState() throws -> SendableSyncState {
        try initializeIfNeeded()
        return SendableSyncState(value: try readSyncState())
    }

    func commitProgressAndPending(
        _ progressTransfer: SendableReaderProgress,
        pending: SendableProgressMutation
    ) throws {
        try initializeIfNeeded()
        let progress = progressTransfer.value
        try requireIdentity(progress)
        guard pending.value.sourceId == sourceID, pending.value.clientId == clientID else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        try withTransaction {
            try saveProgress(progress, ownerKey: ownerKey, preferNewer: false)
            let current = try readSyncState()
            try writeSyncState(ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: current.confirmedRevision,
                pending: pending.value,
                terminalFailureCode: nil
            ))
        }
    }

    func acknowledge(mutationID: String, snapshot: SendableProgressSnapshot) throws {
        try initializeIfNeeded()
        try withTransaction {
            let current = try readSyncState()
            let pending: ErmaoShared.ReaderProgressMutation?
            if let existing = current.pending, existing.mutationId != mutationID {
                pending = ErmaoShared.ReaderProgressMutation(
                    sourceId: existing.sourceId,
                    clientId: existing.clientId,
                    mutationId: existing.mutationId,
                    baseRevision: snapshot.value.revision,
                    capturedAtEpochMillis: existing.capturedAtEpochMillis,
                    locator: existing.locator
                )
            } else {
                pending = nil
            }
            try writeSyncState(ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: max(current.confirmedRevision, snapshot.value.revision),
                pending: pending,
                terminalFailureCode: nil
            ))
        }
    }

    func discardPendingAfterConflict(mutationID: String, serverRevision: Int64) throws {
        try initializeIfNeeded()
        try withTransaction {
            let current = try readSyncState()
            let pending: ErmaoShared.ReaderProgressMutation?
            if let existing = current.pending, existing.mutationId != mutationID {
                pending = ErmaoShared.ReaderProgressMutation(
                    sourceId: existing.sourceId,
                    clientId: existing.clientId,
                    mutationId: existing.mutationId,
                    baseRevision: serverRevision,
                    capturedAtEpochMillis: existing.capturedAtEpochMillis,
                    locator: existing.locator
                )
            } else {
                pending = nil
            }
            try writeSyncState(ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: max(current.confirmedRevision, serverRevision),
                pending: pending,
                terminalFailureCode: nil
            ))
        }
    }

    func acceptRemoteProgress(
        _ progressTransfer: SendableReaderProgress,
        snapshot: SendableProgressSnapshot
    ) throws {
        try initializeIfNeeded()
        let progress = progressTransfer.value
        try requireIdentity(progress)
        try withTransaction {
            try saveProgress(progress, ownerKey: ownerKey, preferNewer: false)
            try writeSyncState(ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: snapshot.value.revision,
                pending: nil,
                terminalFailureCode: nil
            ))
        }
    }

    func recordTerminalFailure(mutationID: String, code: String) throws {
        try initializeIfNeeded()
        try withTransaction {
            let current = try readSyncState()
            guard current.pending?.mutationId == mutationID else { return }
            try writeSyncState(ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: current.confirmedRevision,
                pending: current.pending,
                terminalFailureCode: code
            ))
        }
    }

    func delete(sourceID: String) throws {
        try initializeIfNeeded()
        guard sourceID == self.sourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        try withTransaction {
            try run(
                "DELETE FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
                bindings: [.text(ownerKey), .text(sourceID)]
            )
            try run(
                "DELETE FROM reader_progress_sync_v4 WHERE owner_key = ?",
                bindings: [.text(ownerKey)]
            )
        }
    }

    private func initializeIfNeeded() throws {
        guard !initialized else { return }
        do {
            try execute("PRAGMA journal_mode=WAL")
            try execute("PRAGMA synchronous=FULL")
            try execute("PRAGMA busy_timeout=5000")
            try execute(
                """
                CREATE TABLE IF NOT EXISTS reader_local_exact (
                    owner_key TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    progress_document TEXT NOT NULL,
                    updated_at_epoch_millis INTEGER NOT NULL CHECK(updated_at_epoch_millis >= 0),
                    PRIMARY KEY (owner_key, source_id)
                )
                """
            )
            try execute(
                """
                CREATE TABLE IF NOT EXISTS reader_progress_sync_v4 (
                    owner_key TEXT PRIMARY KEY NOT NULL,
                    state_document TEXT NOT NULL
                )
                """
            )
            try discardIncompatibleReaderStateIfNeeded()
            try fileManager.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: databaseURL.path
            )
            initialized = true
        } catch {
            if let database { sqlite3_close(database) }
            database = nil
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    private func discardIncompatibleReaderStateIfNeeded() throws {
        try execute(
            """
            CREATE TABLE IF NOT EXISTS reader_contract_metadata (
                singleton INTEGER PRIMARY KEY NOT NULL CHECK(singleton = 1),
                contract_version INTEGER NOT NULL
            )
            """
        )
        let version = try scalarText(
            "SELECT CAST(contract_version AS TEXT) FROM reader_contract_metadata WHERE singleton = 1",
            bindings: []
        )
        guard version != "6" else { return }
        try withTransaction {
            try execute("DELETE FROM reader_local_exact")
            try execute("DELETE FROM reader_progress_sync_v4")
            try execute("DROP TABLE IF EXISTS reader_progress")
            try discardObsoleteSyncTables()
            try run(
                """
                INSERT INTO reader_contract_metadata(singleton, contract_version) VALUES(1, 6)
                ON CONFLICT(singleton) DO UPDATE SET contract_version = excluded.contract_version
                """,
                bindings: []
            )
        }
    }

    private func saveProgress(
        _ progress: ErmaoShared.ReaderProgress,
        ownerKey: String,
        preferNewer: Bool
    ) throws {
        try requireIdentity(progress)
        let payload = try progressCodec.encode(progress: progress)
        _ = try decodeProgress(payload, expectedSourceID: progress.sourceId)
        try run(
            """
            INSERT INTO reader_local_exact(
                owner_key, source_id, progress_document, updated_at_epoch_millis
            ) VALUES(?, ?, ?, ?)
            ON CONFLICT(owner_key, source_id) DO UPDATE SET
                progress_document = excluded.progress_document,
                updated_at_epoch_millis = excluded.updated_at_epoch_millis
            \(preferNewer ? "WHERE excluded.updated_at_epoch_millis >= reader_local_exact.updated_at_epoch_millis" : "")
            """,
            bindings: [
                .text(ownerKey),
                .text(progress.sourceId),
                .text(payload),
                .int64(progress.updatedAtEpochMillis),
            ]
        )
    }

    private func readSyncState() throws -> ErmaoShared.ReaderProgressDurableState {
        guard let payload = try scalarText(
            "SELECT state_document FROM reader_progress_sync_v4 WHERE owner_key = ?",
            bindings: [.text(ownerKey)]
        ) else {
            return ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: 0,
                pending: nil,
                terminalFailureCode: nil
            )
        }
        do {
            try requireDocumentSize(payload)
            return syncCodec.decode(payload: payload)
        } catch {
            try discardCurrentContractState()
            return ErmaoShared.ReaderProgressDurableState(
                confirmedRevision: 0,
                pending: nil,
                terminalFailureCode: nil
            )
        }
    }

    private func writeSyncState(_ state: ErmaoShared.ReaderProgressDurableState) throws {
        let payload = syncCodec.encode(state: state)
        try requireDocumentSize(payload)
        try run(
            """
            INSERT INTO reader_progress_sync_v4(owner_key, state_document) VALUES(?, ?)
            ON CONFLICT(owner_key) DO UPDATE SET state_document = excluded.state_document
            """,
            bindings: [.text(ownerKey), .text(payload)]
        )
    }

    private func discardObsoleteSyncTables() throws {
        try execute("DROP TABLE IF EXISTS reader_outbox")
        try execute("DROP TABLE IF EXISTS reader_sequence_counters")
    }

    private func discardCurrentContractState() throws {
        try run(
            "DELETE FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
            bindings: [.text(ownerKey), .text(sourceID)]
        )
        try run(
            "DELETE FROM reader_progress_sync_v4 WHERE owner_key = ?",
            bindings: [.text(ownerKey)]
        )
    }

    /// The pre-union file namespace is deliberately discarded, never imported.
    private func migrateLegacyProgressFile(sourceID: String) throws -> ErmaoShared.ReaderProgress? {
        let legacyURL = legacyProgressURL(sourceID)
        guard fileManager.fileExists(atPath: legacyURL.path) else { return nil }
        try requireLegacyContained(legacyURL)
        let values = try legacyURL.resourceValues(
            forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
        )
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              (values.fileSize ?? 0) <= Self.maximumDocumentBytes
        else { throw IosReaderFailure(code: .persistenceFailed) }
        try fileManager.removeItem(at: legacyURL)
        return nil
    }

    private func decodeProgress(
        _ payload: String,
        expectedSourceID: String
    ) throws -> ErmaoShared.ReaderProgress {
        try requireDocumentSize(payload)
        let projection = try IosReaderProgressContractDecoder.decode(payload)
        guard projection.sourceID == expectedSourceID else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        return try progressCodec.decode(payload: payload)
    }

    private func requireIdentity(_ progress: ErmaoShared.ReaderProgress) throws {
        guard progress.sourceId == sourceID,
              matchesIdentity(progress)
        else { throw IosReaderFailure(code: .persistenceFailed) }
    }

    private func matchesIdentity(_ progress: ErmaoShared.ReaderProgress) -> Bool {
        progress.deviceId == clientID
    }

    private func legacyProgressURL(_ sourceID: String) -> URL {
        let key = SHA256.hash(data: Data(sourceID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return legacyProgressRoot.appendingPathComponent(key).appendingPathExtension("json")
    }

    private func requireLegacyContained(_ url: URL) throws {
        let rootPath = legacyProgressRoot.standardizedFileURL.resolvingSymlinksInPath().path + "/"
        let path = url.standardizedFileURL.resolvingSymlinksInPath().path
        guard path.hasPrefix(rootPath) else { throw IosReaderFailure(code: .persistenceFailed) }
    }

    private func requireDocumentSize(_ value: String) throws {
        guard value.utf8.count <= Self.maximumDocumentBytes else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    private func withTransaction<T>(_ operation: () throws -> T) throws -> T {
        try execute("BEGIN IMMEDIATE")
        do {
            let value = try operation()
            try execute("COMMIT")
            return value
        } catch {
            try? execute("ROLLBACK")
            throw error
        }
    }

    private func execute(_ sql: String) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else { throw databaseFailure() }
    }

    private func run(_ sql: String, bindings: [SQLiteBinding]) throws {
        let statement = try prepare(sql)
        defer { sqlite3_finalize(statement) }
        try bind(bindings, to: statement)
        guard sqlite3_step(statement) == SQLITE_DONE else { throw databaseFailure() }
    }

    private func scalarText(_ sql: String, bindings: [SQLiteBinding]) throws -> String? {
        let statement = try prepare(sql)
        defer { sqlite3_finalize(statement) }
        try bind(bindings, to: statement)
        switch sqlite3_step(statement) {
        case SQLITE_ROW:
            guard let bytes = sqlite3_column_text(statement, 0) else { return nil }
            return String(cString: bytes)
        case SQLITE_DONE:
            return nil
        default:
            throw databaseFailure()
        }
    }

    private func prepare(_ sql: String) throws -> OpaquePointer {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK,
              let statement
        else { throw databaseFailure() }
        return statement
    }

    private func bind(_ values: [SQLiteBinding], to statement: OpaquePointer) throws {
        for (offset, value) in values.enumerated() {
            let index = Int32(offset + 1)
            let result: Int32
            switch value {
            case .text(let text):
                result = sqlite3_bind_text(statement, index, text, -1, Self.sqliteTransient)
            case .int64(let integer):
                result = sqlite3_bind_int64(statement, index, integer)
            }
            guard result == SQLITE_OK else { throw databaseFailure() }
        }
    }

    private func databaseFailure() -> IosReaderFailure {
        IosReaderFailure(code: .persistenceFailed)
    }
}

private enum SQLiteBinding {
    case text(String)
    case int64(Int64)
}
