import Foundation
import SQLite3
@preconcurrency import ErmaoShared

/// Durable, device-local Reader v5 position reports.
///
/// The owner key deliberately excludes authorizationVersion so a successful
/// reauthentication cannot hide the position stored on this installation.
/// The current report and latest pending mutation share one fresh v5 DB.
final class IosReaderLocalDatabase: ErmaoShared.ReaderPositionSyncStateStore, @unchecked Sendable {
    private let worker: IosReaderLocalDatabaseWorker

    init(
        identity: ErmaoShared.ReaderLocalProgressIdentity,
        databaseURL: URL? = nil,
        fileManager: FileManager = .default
    ) throws {
        worker = try IosReaderLocalDatabaseWorker(
            identity: identity,
            databaseURL: databaseURL,
            fileManager: SendableFileManager(fileManager)
        )
    }

    func loadPosition(resourceId: String) async throws -> ErmaoShared.ReaderPositionLocalState? {
        try await worker.load(resourceID: resourceId).value
    }

    func savePosition(position: ErmaoShared.ReaderPositionLocalState) async throws {
        try await worker.save(SendableReaderPosition(position))
    }

    func deletePosition(resourceId: String) async throws {
        try await worker.delete(resourceID: resourceId)
    }

    func loadPositionSyncState() async throws -> ErmaoShared.ReaderPositionDurableState {
        try await worker.loadSyncState().value
    }

    func commitPositionAndPending(
        position: ErmaoShared.ReaderPositionLocalState,
        pending: ErmaoShared.ReaderProgressMutationV5
    ) async throws {
        try await worker.commitPositionAndPending(
            SendableReaderPosition(position),
            pending: SendablePositionMutation(value: pending)
        )
    }

    func acknowledgePosition(
        mutationId: String,
        response: ErmaoShared.ReaderPositionWriteResponse
    ) async throws {
        try await worker.acknowledge(
            mutationID: mutationId,
            response: SendablePositionWriteResponse(value: response)
        )
    }

    func acceptRemotePosition(
        position: ErmaoShared.ReaderPositionLocalState,
        snapshot: ErmaoShared.ReaderProgressSnapshotV5
    ) async throws {
        try await worker.acceptRemotePosition(
            SendableReaderPosition(position),
            snapshot: SendablePositionSnapshot(value: snapshot)
        )
    }

    func recordPositionTerminalFailure(mutationId: String, failureCode: String) async throws {
        try await worker.recordTerminalFailure(mutationID: mutationId, code: failureCode)
    }

    func close() async {
        await worker.close()
    }

    /// Purges all v5 position and pending-sync rows owned by one account.
    /// The DB intentionally omits authorizationVersion from owner keys, so a
    /// reauthentication does not strand the account's local position.
    static func purgeNamespace(
        _ namespace: String,
        databaseURL: URL? = nil,
        fileManager: FileManager = .default
    ) throws {
        try IosReaderLocalDatabaseNamespacePurger.purge(
            namespace,
            databaseURL: databaseURL,
            fileManager: fileManager
        )
    }
}

private enum IosReaderLocalDatabaseNamespacePurger {
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    static func purge(
        _ namespace: String,
        databaseURL: URL?,
        fileManager: FileManager
    ) throws {
        guard let (serverIdentity, userID) = accountComponents(namespace) else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        let url: URL
        if let databaseURL {
            url = databaseURL
        } else {
            let support = try fileManager.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            url = support
                .appendingPathComponent("Reader", isDirectory: true)
                .appendingPathComponent("ReaderV5.sqlite3")
        }
        guard fileManager.fileExists(atPath: url.path) else { return }

        var database: OpaquePointer?
        guard sqlite3_open_v2(
            url.path,
            &database,
            SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX,
            nil
        ) == SQLITE_OK else {
            if let database { sqlite3_close(database) }
            throw IosReaderFailure(code: .persistenceFailed)
        }
        defer { if let database { sqlite3_close(database) } }

        do {
            try exec(database, "BEGIN IMMEDIATE")
            // A newly installed app can have the SQLite file without having
            // initialized the Reader tables yet; these no-op schemas make the
            // purge safe in that state.
            try exec(database, """
                CREATE TABLE IF NOT EXISTS reader_local_v5 (
                    owner_key TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    progress_document TEXT NOT NULL,
                    updated_at_epoch_millis INTEGER NOT NULL,
                    PRIMARY KEY (owner_key, source_id)
                )
                """)
            try exec(database, """
                CREATE TABLE IF NOT EXISTS reader_progress_sync_v5 (
                    owner_key TEXT PRIMARY KEY NOT NULL,
                    state_document TEXT NOT NULL
                )
                """)
            let prefix = lengthPrefixed(serverIdentity, userID)
            try delete(database, table: "reader_local_v5", prefix: prefix)
            try delete(database, table: "reader_progress_sync_v5", prefix: prefix)
            try exec(database, "COMMIT")
        } catch {
            try? exec(database, "ROLLBACK")
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    private static func accountComponents(_ namespace: String) -> (String, String)? {
        let parts = namespace.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count >= 2,
              !parts[0].isEmpty,
              !parts[1].isEmpty else { return nil }
        return (String(parts[0]), String(parts[1]))
    }

    private static func lengthPrefixed(_ values: String...) -> String {
        values.map { "\($0.utf16.count):\($0)" }.joined()
    }

    private static func exec(_ database: OpaquePointer?, _ sql: String) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    private static func delete(_ database: OpaquePointer?, table: String, prefix: String) throws {
        let sql = "DELETE FROM \(table) WHERE owner_key LIKE ? ESCAPE '\\'"
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, sql, -1, &statement, nil) == SQLITE_OK,
              let statement else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        defer { sqlite3_finalize(statement) }
        let escapedPrefix = prefix
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "%", with: "\\%")
            .replacingOccurrences(of: "_", with: "\\_")
        guard sqlite3_bind_text(statement, 1, (escapedPrefix + "%"), -1, transient) == SQLITE_OK,
              sqlite3_step(statement) == SQLITE_DONE else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }
}

private struct SendableFileManager: @unchecked Sendable {
    let value: FileManager

    init(_ value: FileManager) {
        self.value = value
    }
}

private struct SendableReaderPosition: @unchecked Sendable {
    let value: ErmaoShared.ReaderPositionLocalState

    init(_ value: ErmaoShared.ReaderPositionLocalState) {
        self.value = value
    }
}

private struct SendableOptionalReaderPosition: @unchecked Sendable {
    let value: ErmaoShared.ReaderPositionLocalState?
}

private struct SendablePositionSyncState: @unchecked Sendable {
    let value: ErmaoShared.ReaderPositionDurableState
}
private struct SendablePositionMutation: @unchecked Sendable {
    let value: ErmaoShared.ReaderProgressMutationV5
}
private struct SendablePositionSnapshot: @unchecked Sendable {
    let value: ErmaoShared.ReaderProgressSnapshotV5
}
private struct SendablePositionWriteResponse: @unchecked Sendable {
    let value: ErmaoShared.ReaderPositionWriteResponse
}

private actor IosReaderLocalDatabaseWorker {
    private static let maximumDocumentBytes = 1_048_576
    private static let sqliteTransient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private let ownerKey: String
    private let clientID: String
    private let resourceID: String
    private let databaseURL: URL
    private let fileManager: FileManager
    private let positionCodec = ErmaoShared.PublicKt.createReaderPositionJson()
    private let syncCodec = ErmaoShared.PublicKt.createReaderPositionSyncStateJson()
    private nonisolated(unsafe) var database: OpaquePointer?
    private var initialized = false

    init(
        identity: ErmaoShared.ReaderLocalProgressIdentity,
        databaseURL: URL?,
        fileManager: SendableFileManager
    ) throws {
        guard !identity.stableKey.isEmpty else { throw IosReaderFailure(code: .persistenceFailed) }
        ownerKey = identity.stableKey
        clientID = identity.clientId
        resourceID = identity.resourceId
        let manager = fileManager.value
        self.fileManager = manager

        let url: URL
        if let databaseURL {
            url = databaseURL
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
            url = directory.appendingPathComponent("ReaderV5.sqlite3")
        }
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

    func close() {
        guard let database else { return }
        sqlite3_close(database)
        self.database = nil
        initialized = false
    }

    func load(resourceID: String) throws -> SendableOptionalReaderPosition {
        try initializeIfNeeded()
        guard resourceID == self.resourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        if let payload = try scalarText(
            "SELECT progress_document FROM reader_local_v5 WHERE owner_key = ? AND source_id = ?",
            bindings: [.text(ownerKey), .text(resourceID)]
        ) {
            let position: ErmaoShared.ReaderPositionLocalState
            do {
                position = try decodePosition(payload, expectedResourceID: resourceID)
            } catch {
                return SendableOptionalReaderPosition(value: nil)
            }
            try requireIdentity(position)
            return SendableOptionalReaderPosition(value: position)
        }
        return SendableOptionalReaderPosition(value: nil)
    }

    func save(_ positionTransfer: SendableReaderPosition) throws {
        try initializeIfNeeded()
        let position = positionTransfer.value
        try requireIdentity(position)
        try withTransaction { try savePosition(position, ownerKey: ownerKey) }
    }

    func loadSyncState() throws -> SendablePositionSyncState {
        try initializeIfNeeded()
        return SendablePositionSyncState(value: try readSyncState())
    }

    func commitPositionAndPending(
        _ positionTransfer: SendableReaderPosition,
        pending: SendablePositionMutation
    ) throws {
        try initializeIfNeeded()
        let position = positionTransfer.value
        try requireIdentity(position)
        guard pending.value.resourceId == resourceID, pending.value.clientId == clientID else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        try withTransaction {
            try savePosition(position, ownerKey: ownerKey)
            let current = try readSyncState()
            try writeSyncState(ErmaoShared.ReaderPositionDurableState(
                confirmedRevision: current.confirmedRevision,
                pending: pending.value,
                terminalFailureCode: nil
            ))
        }
    }

    func acknowledge(mutationID: String, response: SendablePositionWriteResponse) throws {
        try initializeIfNeeded()
        try withTransaction {
            let current = try readSyncState()
            let acknowledgedCurrentPending = current.pending?.mutationId == mutationID
            let pending = acknowledgedCurrentPending ? nil : current.pending
            try writeSyncState(ErmaoShared.ReaderPositionDurableState(
                confirmedRevision: max(
                    current.confirmedRevision,
                    max(response.value.acceptedRevision, response.value.currentSnapshot.revision)
                ),
                pending: pending,
                terminalFailureCode: acknowledgedCurrentPending
                    ? nil
                    : current.terminalFailureCode
            ))
        }
    }

    func acceptRemotePosition(
        _ positionTransfer: SendableReaderPosition,
        snapshot: SendablePositionSnapshot
    ) throws {
        try initializeIfNeeded()
        let position = positionTransfer.value
        try requireIdentity(position)
        try withTransaction {
            try savePosition(position, ownerKey: ownerKey)
            try writeSyncState(ErmaoShared.ReaderPositionDurableState(
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
            try writeSyncState(ErmaoShared.ReaderPositionDurableState(
                confirmedRevision: current.confirmedRevision,
                pending: current.pending,
                terminalFailureCode: code
            ))
        }
    }

    func delete(resourceID: String) throws {
        try initializeIfNeeded()
        guard resourceID == self.resourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        try withTransaction {
            try run(
                "DELETE FROM reader_local_v5 WHERE owner_key = ? AND source_id = ?",
                bindings: [.text(ownerKey), .text(resourceID)]
            )
            try run(
                "DELETE FROM reader_progress_sync_v5 WHERE owner_key = ?",
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
                CREATE TABLE IF NOT EXISTS reader_local_v5 (
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
                CREATE TABLE IF NOT EXISTS reader_progress_sync_v5 (
                    owner_key TEXT PRIMARY KEY NOT NULL,
                    state_document TEXT NOT NULL
                )
                """
            )
            try recordReaderContractVersionIfNeeded()
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

    private func recordReaderContractVersionIfNeeded() throws {
        try execute(
            """
            CREATE TABLE IF NOT EXISTS reader_v5_contract_metadata (
                singleton INTEGER PRIMARY KEY NOT NULL CHECK(singleton = 1),
                contract_version INTEGER NOT NULL
            )
            """
        )
        let version = try scalarText(
            "SELECT CAST(contract_version AS TEXT) FROM reader_v5_contract_metadata WHERE singleton = 1",
            bindings: []
        )
        guard version != "5" else { return }
        try withTransaction {
            try run(
                """
                INSERT INTO reader_v5_contract_metadata(singleton, contract_version) VALUES(1, 5)
                ON CONFLICT(singleton) DO UPDATE SET contract_version = excluded.contract_version
                """,
                bindings: []
            )
        }
    }

    private func savePosition(
        _ position: ErmaoShared.ReaderPositionLocalState,
        ownerKey: String
    ) throws {
        try requireIdentity(position)
        let payload = positionCodec.encode(position: position)
        _ = try decodePosition(payload, expectedResourceID: position.resourceId)
        try run(
            """
            INSERT INTO reader_local_v5(
                owner_key, source_id, progress_document, updated_at_epoch_millis
            ) VALUES(?, ?, ?, ?)
            ON CONFLICT(owner_key, source_id) DO UPDATE SET
                progress_document = excluded.progress_document,
                updated_at_epoch_millis = excluded.updated_at_epoch_millis
            """,
            bindings: [
                .text(ownerKey),
                .text(position.resourceId),
                .text(payload),
                .int64(position.capturedAtEpochMillis),
            ]
        )
    }

    private func readSyncState() throws -> ErmaoShared.ReaderPositionDurableState {
        guard let payload = try scalarText(
            "SELECT state_document FROM reader_progress_sync_v5 WHERE owner_key = ?",
            bindings: [.text(ownerKey)]
        ) else {
            return ErmaoShared.ReaderPositionDurableState(
                confirmedRevision: 0,
                pending: nil,
                terminalFailureCode: nil
            )
        }
        // A malformed v5 sync document is a persistence failure, not an
        // empty outbox.  Propagating the codec error keeps a real pending
        // mutation from being mistaken for a successful read with no upload.
        try requireDocumentSize(payload)
        return syncCodec.decode(payload: payload)
    }

    private func writeSyncState(_ state: ErmaoShared.ReaderPositionDurableState) throws {
        let payload = syncCodec.encode(state: state)
        try requireDocumentSize(payload)
        try run(
            """
            INSERT INTO reader_progress_sync_v5(owner_key, state_document) VALUES(?, ?)
            ON CONFLICT(owner_key) DO UPDATE SET state_document = excluded.state_document
            """,
            bindings: [.text(ownerKey), .text(payload)]
        )
    }

    private func decodePosition(
        _ payload: String,
        expectedResourceID: String
    ) throws -> ErmaoShared.ReaderPositionLocalState {
        try requireDocumentSize(payload)
        let position = try positionCodec.decode(payload: payload)
        guard position.resourceId == expectedResourceID else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        return position
    }

    private func requireIdentity(_ position: ErmaoShared.ReaderPositionLocalState) throws {
        guard position.resourceId == resourceID,
              position.clientId == clientID
        else { throw IosReaderFailure(code: .persistenceFailed) }
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
