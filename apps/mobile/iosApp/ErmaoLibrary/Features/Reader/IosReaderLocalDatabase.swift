import CryptoKit
import Foundation
import SQLite3
@preconcurrency import ErmaoShared

/// Durable, device-local exact Reader positions.
///
/// The owner key deliberately excludes authorizationVersion so a successful
/// reauthentication cannot hide the position stored on this installation.
/// Cross-device synchronization is owned by `IosReaderProgressStore` and never
/// persists its transient upload state in this database.
final class IosReaderLocalDatabase: ErmaoShared.ReaderProgressStore, @unchecked Sendable {
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
            fileManager: fileManager
        )
    }

    func load(sourceId: String) async throws -> ErmaoShared.ReaderProgress? {
        try await worker.load(sourceID: sourceId)
    }

    func save(progress: ErmaoShared.ReaderProgress) async throws {
        try await worker.save(progress)
    }

    func delete(sourceId: String) async throws {
        try await worker.delete(sourceID: sourceId)
    }
}

private actor IosReaderLocalDatabaseWorker {
    private struct LegacyR4Row {
        let namespaceKey: String
        let sourceID: String
        let document: String
    }

    private static let maximumDocumentBytes = 1_048_576
    private static let sqliteTransient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private let ownerKey: String
    private let namespace: ErmaoShared.ReaderSyncNamespace
    private let clientID: String
    private let sourceID: String
    private let localFingerprint: ErmaoShared.ContentFingerprint
    private let legacyProgressRoot: URL
    private let fileManager: FileManager
    private let progressCodec = ErmaoShared.ReaderProgressJson()
    private var database: OpaquePointer?

    init(
        identity: ErmaoShared.ReaderLocalProgressIdentity,
        databaseURL: URL?,
        legacyProgressRoot: URL?,
        fileManager: FileManager
    ) throws {
        guard !identity.stableKey.isEmpty else { throw IosReaderFailure(code: .persistenceFailed) }
        ownerKey = identity.stableKey
        namespace = identity.namespace
        clientID = identity.clientId
        sourceID = identity.volumeId
        localFingerprint = identity.localContentFingerprint
        self.fileManager = fileManager

        let url: URL
        let defaultLegacyRoot: URL
        if let databaseURL {
            url = databaseURL
            defaultLegacyRoot = databaseURL.deletingLastPathComponent()
                .appendingPathComponent("Progress", isDirectory: true)
        } else {
            let support = try fileManager.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            let directory = support.appendingPathComponent("Reader", isDirectory: true)
            try fileManager.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
            )
            url = directory.appendingPathComponent("Reader.sqlite3")
            defaultLegacyRoot = directory.appendingPathComponent("Progress", isDirectory: true)
        }
        self.legacyProgressRoot = legacyProgressRoot ?? defaultLegacyRoot

        guard sqlite3_open_v2(
            url.path,
            &database,
            SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX,
            nil
        ) == SQLITE_OK else {
            if let database { sqlite3_close(database) }
            throw IosReaderFailure(code: .persistenceFailed)
        }
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
            try migrateIncompleteExactIdentity()
            try migrateLegacyR4Schema()
            try fileManager.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: url.path
            )
        } catch {
            if let database { sqlite3_close(database) }
            self.database = nil
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    deinit {
        if let database { sqlite3_close(database) }
    }

    func load(sourceID: String) throws -> ErmaoShared.ReaderProgress? {
        guard sourceID == self.sourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        if let payload = try scalarText(
            "SELECT progress_document FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
            bindings: [.text(ownerKey), .text(sourceID)]
        ) {
            let progress = try decodeProgress(payload, expectedSourceID: sourceID)
            try requireIdentity(progress)
            return progress
        }
        return try migrateLegacyProgressFile(sourceID: sourceID)
    }

    func save(_ progress: ErmaoShared.ReaderProgress) throws {
        try requireIdentity(progress)
        try withTransaction { try saveProgress(progress, ownerKey: ownerKey, preferNewer: false) }
    }

    func delete(sourceID: String) throws {
        guard sourceID == self.sourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        try run(
            "DELETE FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
            bindings: [.text(ownerKey), .text(sourceID)]
        )
    }

    private func saveProgress(
        _ progress: ErmaoShared.ReaderProgress,
        ownerKey: String,
        preferNewer: Bool
    ) throws {
        try requireIdentity(progress)
        let payload = progressCodec.encode(progress: progress)
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

    /// Migrates the short-lived v4 preview owner key (server + user) only
    /// when its exact document proves the same client and local publication.
    /// Another installation or content version is never adopted implicitly.
    private func migrateIncompleteExactIdentity() throws {
        let incompleteOwnerKey = Self.lengthPrefixed(namespace.serverIdentity, namespace.userId)
        guard incompleteOwnerKey != ownerKey,
              let payload = try scalarText(
                  "SELECT progress_document FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
                  bindings: [.text(incompleteOwnerKey), .text(sourceID)]
              )
        else { return }
        let progress = try decodeProgress(payload, expectedSourceID: sourceID)
        guard matchesIdentity(progress) else { return }
        try withTransaction {
            try saveProgress(progress, ownerKey: ownerKey, preferNewer: true)
            try run(
                "DELETE FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
                bindings: [.text(incompleteOwnerKey), .text(sourceID)]
            )
        }
    }

    /// R4 previously stored exact progress together with a durable outbox keyed
    /// by a namespace containing authorizationVersion. Exact documents are moved
    /// first. Obsolete sync tables are removed only in the same successful
    /// transaction. An unrecognizable exact row keeps the legacy table intact.
    private func migrateLegacyR4Schema() throws {
        guard try tableExists("reader_progress") else {
            try discardObsoleteSyncTables()
            return
        }
        let rows = try legacyR4Rows()
        var migratedEveryExactRow = true
        try withTransaction {
            for row in rows {
                guard let scope = Self.scope(fromLegacyNamespaceKey: row.namespaceKey),
                      let progress = try? decodeProgress(row.document, expectedSourceID: row.sourceID)
                else {
                    migratedEveryExactRow = false
                    continue
                }
                let fingerprint = progress.location.contentFingerprint
                let migratedOwnerKey = Self.lengthPrefixed(
                    scope.serverIdentity,
                    scope.userID,
                    progress.deviceId,
                    row.sourceID,
                    fingerprint.originalFileHash,
                    fingerprint.parserVersion,
                    fingerprint.normalizationVersion
                )
                guard migratedOwnerKey == ownerKey else {
                    migratedEveryExactRow = false
                    continue
                }
                try saveProgress(progress, ownerKey: ownerKey, preferNewer: true)
            }
            if migratedEveryExactRow { try execute("DROP TABLE reader_progress") }
            try discardObsoleteSyncTables()
        }
    }

    private func discardObsoleteSyncTables() throws {
        try execute("DROP TABLE IF EXISTS reader_outbox")
        try execute("DROP TABLE IF EXISTS reader_sequence_counters")
    }

    private func legacyR4Rows() throws -> [LegacyR4Row] {
        let statement = try prepare(
            "SELECT namespace_key, source_id, progress_document FROM reader_progress"
        )
        defer { sqlite3_finalize(statement) }
        var rows: [LegacyR4Row] = []
        while true {
            switch sqlite3_step(statement) {
            case SQLITE_ROW:
                guard let namespaceBytes = sqlite3_column_text(statement, 0),
                      let sourceBytes = sqlite3_column_text(statement, 1),
                      let documentBytes = sqlite3_column_text(statement, 2)
                else { throw databaseFailure() }
                rows.append(LegacyR4Row(
                    namespaceKey: String(cString: namespaceBytes),
                    sourceID: String(cString: sourceBytes),
                    document: String(cString: documentBytes)
                ))
            case SQLITE_DONE:
                return rows
            default:
                throw databaseFailure()
            }
        }
    }

    private static func scope(fromLegacyNamespaceKey value: String) -> (serverIdentity: String, userID: String)? {
        guard let values = parseLengthPrefixed(value), values.count == 3 else { return nil }
        return (values[0], values[1])
    }

    private static func parseLengthPrefixed(_ value: String) -> [String]? {
        let utf16 = value as NSString
        var cursor = 0
        var result: [String] = []
        while cursor < utf16.length {
            let colon = utf16.range(of: ":", range: NSRange(location: cursor, length: utf16.length - cursor))
            guard colon.location != NSNotFound,
                  let length = Int(utf16.substring(with: NSRange(location: cursor, length: colon.location - cursor))),
                  length >= 0,
                  colon.location + 1 + length <= utf16.length
            else { return nil }
            let start = colon.location + 1
            result.append(utf16.substring(with: NSRange(location: start, length: length)))
            cursor = start + length
        }
        return result
    }

    private static func lengthPrefixed(_ values: String...) -> String {
        values.map { "\(($0 as NSString).length):\($0)" }.joined()
    }

    /// R3 stored one KMP ReaderProgressJson document per opaque source key.
    /// Import is lazy and deletion occurs only after the SQLite commit succeeds.
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
        let payload = try String(contentsOf: legacyURL, encoding: .utf8)
        let progress = try decodeProgress(payload, expectedSourceID: sourceID)
        try withTransaction { try saveProgress(progress, ownerKey: ownerKey, preferNewer: false) }
        try fileManager.removeItem(at: legacyURL)
        return progress
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
        return progressCodec.decode(payload: payload)
    }

    private func requireIdentity(_ progress: ErmaoShared.ReaderProgress) throws {
        guard progress.sourceId == sourceID,
              matchesIdentity(progress)
        else { throw IosReaderFailure(code: .persistenceFailed) }
    }

    private func matchesIdentity(_ progress: ErmaoShared.ReaderProgress) -> Bool {
        progress.deviceId == clientID &&
            progress.location.contentFingerprint.originalFileHash == localFingerprint.originalFileHash &&
            progress.location.contentFingerprint.parserVersion == localFingerprint.parserVersion &&
            progress.location.contentFingerprint.normalizationVersion == localFingerprint.normalizationVersion
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

    private func tableExists(_ name: String) throws -> Bool {
        try scalarText(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            bindings: [.text(name)]
        ) != nil
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
