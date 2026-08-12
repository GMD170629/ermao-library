import CryptoKit
import Foundation
import SQLite3
import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

final class ReaderPersistenceTests: XCTestCase {
    private var temporaryRoot: URL!

    override func setUpWithError() throws {
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
        temporaryRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("reader-store-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryRoot, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let temporaryRoot { try? FileManager.default.removeItem(at: temporaryRoot) }
    }

    func testReaderUsesFiveHundredMillisecondTrailingSave() {
        XCTAssertEqual(IosEpubReaderSession.progressSaveDebounceMilliseconds, 500)
    }

    func testBootstrapLocationCannotBecomeFakeLocalExact() {
        var gate = IosReaderPersistenceGate()
        let remote = IosReaderPersistenceGate.LocationSignature(
            href: "chapter.xhtml",
            progression: 0.5,
            totalProgression: 0.6,
            position: 12
        )
        let navigated = IosReaderPersistenceGate.LocationSignature(
            href: "chapter.xhtml",
            progression: 0.7,
            totalProgression: 0.8,
            position: 13
        )
        gate.protectRestoredLocation(remote)

        XCTAssertFalse(gate.observeLocationChange(remote))
        XCTAssertFalse(gate.observeLocationChange(remote))
        XCTAssertFalse(gate.hasLocalReadingActivity)

        XCTAssertTrue(gate.observeLocationChange(navigated))
        XCTAssertTrue(gate.hasLocalReadingActivity)
    }

    func testExactProgressRoundTripsWithoutCreatingDurableSyncState() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, volumeID: "volume-a"),
            databaseURL: databaseURL
        )
        let progress = decodeProgress(sourceID: "volume-a", updatedAt: 1_775_988_123_456)

        try await store.save(progress: progress)
        let restored = try await store.load(sourceId: "volume-a")

        XCTAssertEqual(restored?.updatedAtEpochMillis, 1_775_988_123_456)
        XCTAssertTrue(
            (restored?.location as? ErmaoShared.ReflowReaderLocation)?
                .engineLocator?.payload.canonicalJson.contains("chapter.xhtml") == true
        )
        XCTAssertFalse(try tableExists("reader_outbox", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_sequence_counters", databaseURL: databaseURL))
    }

    func testExactProgressSurvivesAuthorizationVersionRollover() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let v4 = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, volumeID: "volume-a"),
            databaseURL: databaseURL
        )
        try await v4.save(progress: decodeProgress(sourceID: "volume-a", updatedAt: 1_775_988_123_456))

        let v5 = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, volumeID: "volume-a"),
            databaseURL: databaseURL
        )
        let restored = try await v5.load(sourceId: "volume-a")

        XCTAssertEqual(restored?.sourceId, "volume-a")
        XCTAssertEqual(restored?.updatedAtEpochMillis, 1_775_988_123_456)
    }

    func testExactIdentityIncludesEveryStableLocalOwnerComponentButNotAuthorizationVersion() {
        let baseline = makeIdentity(authorizationVersion: 4, volumeID: "volume-a")
        XCTAssertEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 5, volumeID: "volume-a").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, volumeID: "volume-a", clientID: "other-client").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, volumeID: "volume-b").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                authorizationVersion: 4,
                volumeID: "volume-a",
                fileHash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ).stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, volumeID: "volume-a", parserVersion: "readium-swift:3.8.1").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, volumeID: "volume-a", normalizationVersion: "epub-v2").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                namespace: makeNamespace(
                    authorizationVersion: 4,
                    serverIdentity: "server-b"
                ),
                volumeID: "volume-a"
            ).stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                namespace: makeNamespace(
                    authorizationVersion: 4,
                    userID: "user-b"
                ),
                volumeID: "volume-a"
            ).stableKey
        )
    }

    func testExactIdentitySeparatesClientAndLocalContentVersion() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let primary = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, volumeID: "volume-a"),
            databaseURL: databaseURL
        )
        try await primary.save(progress: decodeProgress(sourceID: "volume-a", updatedAt: 100))

        let anotherClient = try IosReaderLocalDatabase(
            identity: makeIdentity(
                authorizationVersion: 4,
                volumeID: "volume-a",
                clientID: "ios-installation-d"
            ),
            databaseURL: databaseURL
        )
        let anotherContent = try IosReaderLocalDatabase(
            identity: makeIdentity(
                authorizationVersion: 4,
                volumeID: "volume-a",
                fileHash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            databaseURL: databaseURL
        )

        let otherClientBeforeSave = try await anotherClient.load(sourceId: "volume-a")
        let otherContentBeforeSave = try await anotherContent.load(sourceId: "volume-a")
        XCTAssertNil(otherClientBeforeSave)
        XCTAssertNil(otherContentBeforeSave)

        try await anotherContent.save(progress: decodeProgress(
            sourceID: "volume-a",
            updatedAt: 200,
            fileHash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ))
        let originalRestored = try await primary.load(sourceId: "volume-a")
        let otherContentRestored = try await anotherContent.load(sourceId: "volume-a")
        XCTAssertEqual(originalRestored?.updatedAtEpochMillis, 100)
        XCTAssertEqual(otherContentRestored?.updatedAtEpochMillis, 200)
    }

    func testLatestLocalSaveOverwritesEvenWhenWallClockMovesBackward() async throws {
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, volumeID: "volume-a"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        try await store.save(progress: decodeProgress(sourceID: "volume-a", updatedAt: 200))
        try await store.save(progress: decodeProgress(sourceID: "volume-a", updatedAt: 100))

        let restored = try await store.load(sourceId: "volume-a")
        XCTAssertEqual(restored?.updatedAtEpochMillis, 100)
    }

    func testLegacyR4SQLiteMigratesExactBeforeDroppingSyncTables() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let namespace = makeNamespace(authorizationVersion: 4)
        try createLegacyR4Database(
            at: databaseURL,
            namespaceKey: namespace.stableKey,
            sourceID: "legacy-r4-volume",
            payload: progressPayload(sourceID: "legacy-r4-volume", updatedAt: 1_775_988_323_456)
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, volumeID: "legacy-r4-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "legacy-r4-volume")

        XCTAssertEqual(migrated?.updatedAtEpochMillis, 1_775_988_323_456)
        XCTAssertTrue(try tableExists("reader_local_exact", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_progress", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_outbox", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_sequence_counters", databaseURL: databaseURL))

        let reauthenticated = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, volumeID: "legacy-r4-volume"),
            databaseURL: databaseURL
        )
        let afterReauthentication = try await reauthenticated.load(sourceId: "legacy-r4-volume")
        XCTAssertEqual(afterReauthentication?.updatedAtEpochMillis, 1_775_988_323_456)
    }

    func testIncompleteExactKeyMigratesOnlyMatchingClientAndContentThenDeletesOldRow() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let oldOwnerKey = "8:server-a6:user-a"
        try createIncompleteExactDatabase(
            at: databaseURL,
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            payload: progressPayload(sourceID: "preview-volume", updatedAt: 444)
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 9, volumeID: "preview-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "preview-volume")

        XCTAssertEqual(migrated?.updatedAtEpochMillis, 444)
        XCTAssertFalse(try exactRowExists(
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            databaseURL: databaseURL
        ))
    }

    func testIncompleteExactKeyFromAnotherClientIsNotAdoptedOrDeleted() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let oldOwnerKey = "8:server-a6:user-a"
        try createIncompleteExactDatabase(
            at: databaseURL,
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            payload: progressPayload(
                sourceID: "preview-volume",
                updatedAt: 444,
                clientID: "another-installation"
            )
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 9, volumeID: "preview-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "preview-volume")

        XCTAssertNil(migrated)
        XCTAssertTrue(try exactRowExists(
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            databaseURL: databaseURL
        ))
    }

    func testIncompleteExactKeyFromAnotherContentVersionIsNotAdoptedOrDeleted() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let oldOwnerKey = "8:server-a6:user-a"
        try createIncompleteExactDatabase(
            at: databaseURL,
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            payload: progressPayload(
                sourceID: "preview-volume",
                updatedAt: 444,
                fileHash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 9, volumeID: "preview-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "preview-volume")

        XCTAssertNil(migrated)
        XCTAssertTrue(try exactRowExists(
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            databaseURL: databaseURL
        ))
    }

    func testUnrecognizedLegacyR4ExactTableIsRetained() throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        try createLegacyR4Database(
            at: databaseURL,
            namespaceKey: "not-a-length-prefixed-namespace",
            sourceID: "legacy-r4-volume",
            payload: progressPayload(sourceID: "legacy-r4-volume", updatedAt: 1_775_988_323_456)
        )

        _ = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, volumeID: "legacy-r4-volume"),
            databaseURL: databaseURL
        )

        XCTAssertTrue(try tableExists("reader_progress", databaseURL: databaseURL))
    }

    func testLegacyProgressFileMigratesThenDeletesDocument() async throws {
        let legacyRoot = temporaryRoot.appendingPathComponent("Progress", isDirectory: true)
        try FileManager.default.createDirectory(at: legacyRoot, withIntermediateDirectories: true)
        let legacyURL = legacyProgressURL(sourceID: "legacy-volume", root: legacyRoot)
        try Data(progressPayload(sourceID: "legacy-volume", updatedAt: 1_775_988_323_456).utf8)
            .write(to: legacyURL)
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, volumeID: "legacy-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3"),
            legacyProgressRoot: legacyRoot
        )

        let migrated = try await store.load(sourceId: "legacy-volume")

        XCTAssertEqual(migrated?.sourceId, "legacy-volume")
        XCTAssertFalse(FileManager.default.fileExists(atPath: legacyURL.path))
    }

    func testInvalidLegacyProgressFileIsNeverDeleted() async throws {
        let legacyRoot = temporaryRoot.appendingPathComponent("Progress", isDirectory: true)
        try FileManager.default.createDirectory(at: legacyRoot, withIntermediateDirectories: true)
        let legacyURL = legacyProgressURL(sourceID: "expected-volume", root: legacyRoot)
        try Data(progressPayload(sourceID: "another-volume", updatedAt: 1_775_988_323_456).utf8)
            .write(to: legacyURL)
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, volumeID: "expected-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3"),
            legacyProgressRoot: legacyRoot
        )

        do {
            _ = try await store.load(sourceId: "expected-volume")
            XCTFail("Invalid legacy progress must fail migration")
        } catch {
            XCTAssertTrue(FileManager.default.fileExists(atPath: legacyURL.path))
        }
    }

    func testUploadFailureIsDiscardedAfterExactLocalCommit() async throws {
        let namespace = makeNamespace(authorizationVersion: 4)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, volumeID: "upload-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        let port = RecordingReaderProgressPort(failure: TestUploadFailure.expected)
        let store = IosReaderProgressStore(
            database: database,
            target: makeTarget(namespace: namespace, volumeID: "upload-volume"),
            syncPort: port
        )
        let progress = decodeProgress(sourceID: "upload-volume", updatedAt: 1_775_988_523_456)

        try await store.save(progress: progress)
        try await store.awaitPendingUpload()
        let restored = try await store.load(sourceId: "upload-volume")

        XCTAssertEqual(restored?.updatedAtEpochMillis, progress.updatedAtEpochMillis)
        XCTAssertEqual(port.uploadCount, 1)
        XCTAssertEqual(port.lastPercent, 50)
        XCTAssertEqual(port.lastServerFingerprint, "server-version-a")
        XCTAssertEqual(
            port.lastLocalContentHash,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        XCTAssertTrue(port.lastLocatorPayload?.contains("chapter.xhtml") == true)
    }

    func testSingleFlightUploadKeepsOnlyLatestWaitingLocation() async throws {
        let namespace = makeNamespace(authorizationVersion: 4)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, volumeID: "single-flight-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        let port = BlockingReaderProgressPort()
        let store = IosReaderProgressStore(
            database: database,
            target: makeTarget(namespace: namespace, volumeID: "single-flight-volume"),
            syncPort: port
        )

        try await store.save(progress: decodeProgress(sourceID: "single-flight-volume", updatedAt: 100))
        await port.waitUntilFirstUploadStarts()
        try await store.save(progress: decodeProgress(sourceID: "single-flight-volume", updatedAt: 200))
        try await store.save(progress: decodeProgress(sourceID: "single-flight-volume", updatedAt: 300))
        port.releaseFirstUpload()
        try await store.awaitPendingUpload()

        XCTAssertEqual(port.uploadedTimestamps, [100, 300])
        let restored = try await store.load(sourceId: "single-flight-volume")
        XCTAssertEqual(restored?.updatedAtEpochMillis, 300)
    }

    private func makeNamespace(
        authorizationVersion: Int64,
        serverIdentity: String = "server-a",
        userID: String = "user-a"
    ) -> ErmaoShared.ReaderSyncNamespace {
        ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: serverIdentity,
            userId: userID,
            authorizationVersion: authorizationVersion
        )
    }

    private func makeIdentity(
        authorizationVersion: Int64,
        volumeID: String,
        clientID: String = "ios-installation-c",
        fileHash: String = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        parserVersion: String = "readium-swift:3.8.0",
        normalizationVersion: String = "epub-native-sanitized-v1"
    ) -> ErmaoShared.ReaderLocalProgressIdentity {
        makeIdentity(
            namespace: makeNamespace(authorizationVersion: authorizationVersion),
            volumeID: volumeID,
            clientID: clientID,
            fileHash: fileHash,
            parserVersion: parserVersion,
            normalizationVersion: normalizationVersion
        )
    }

    private func makeIdentity(
        namespace: ErmaoShared.ReaderSyncNamespace,
        volumeID: String,
        clientID: String = "ios-installation-c",
        fileHash: String = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        parserVersion: String = "readium-swift:3.8.0",
        normalizationVersion: String = "epub-native-sanitized-v1"
    ) -> ErmaoShared.ReaderLocalProgressIdentity {
        ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: clientID,
            volumeId: volumeID,
            localContentFingerprint: ErmaoShared.ContentFingerprint(
                originalFileHash: fileHash,
                parserVersion: parserVersion,
                normalizationVersion: normalizationVersion
            )
        )
    }

    private func decodeProgress(
        sourceID: String,
        updatedAt: Int64,
        clientID: String = "ios-installation-c",
        fileHash: String = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ) -> ErmaoShared.ReaderProgress {
        ErmaoShared.ReaderProgressJson().decode(payload: progressPayload(
            sourceID: sourceID,
            updatedAt: updatedAt,
            clientID: clientID,
            fileHash: fileHash
        ))
    }

    private func makeTarget(
        namespace: ErmaoShared.ReaderSyncNamespace,
        volumeID: String
    ) -> ErmaoShared.ReaderProgressSyncTarget {
        ErmaoShared.ReaderProgressSyncTarget(
            namespace: namespace,
            workId: "work-a",
            volumeId: volumeID,
            sourceFormat: .epub,
            serverContentFingerprint: ErmaoShared.ReaderServerContentFingerprint(value: "server-version-a")
        )
    }

    private func progressPayload(
        sourceID: String,
        updatedAt: Int64,
        clientID: String = "ios-installation-c",
        fileHash: String = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ) -> String {
        #"{"schema":"ermao.reader-progress","version":1,"sourceId":"\#(sourceID)","location":{"kind":"reflow","resourceKey":"chapter.xhtml","progression":0.5,"engineLocator":{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"progression":0.5}},"contentFingerprint":{"originalFileHash":"\#(fileHash)","parserVersion":"readium-swift:3.8.0","normalizationVersion":"epub-native-sanitized-v1"}},"updatedAtEpochMillis":\#(updatedAt),"deviceId":"\#(clientID)"}"#
    }

    private func legacyProgressURL(sourceID: String, root: URL) -> URL {
        let key = SHA256.hash(data: Data(sourceID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return root.appendingPathComponent(key).appendingPathExtension("json")
    }

    private func createLegacyR4Database(
        at url: URL,
        namespaceKey: String,
        sourceID: String,
        payload: String
    ) throws {
        var database: OpaquePointer?
        guard sqlite3_open(url.path, &database) == SQLITE_OK, let database else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        defer { sqlite3_close(database) }
        try execute(
            "CREATE TABLE reader_progress(namespace_key TEXT NOT NULL, source_id TEXT NOT NULL, progress_document TEXT NOT NULL, PRIMARY KEY(namespace_key, source_id))",
            database: database
        )
        try execute(
            "CREATE TABLE reader_outbox(namespace_key TEXT PRIMARY KEY NOT NULL, outbox_document TEXT NOT NULL)",
            database: database
        )
        try execute(
            "CREATE TABLE reader_sequence_counters(identity_key TEXT PRIMARY KEY NOT NULL, last_client_sequence INTEGER NOT NULL)",
            database: database
        )
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(
            database,
            "INSERT INTO reader_progress(namespace_key, source_id, progress_document) VALUES(?, ?, ?)",
            -1,
            &statement,
            nil
        ) == SQLITE_OK, let statement else { throw IosReaderFailure(code: .persistenceFailed) }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, namespaceKey, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        sqlite3_bind_text(statement, 2, sourceID, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        sqlite3_bind_text(statement, 3, payload, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        guard sqlite3_step(statement) == SQLITE_DONE else { throw IosReaderFailure(code: .persistenceFailed) }
    }

    private func createIncompleteExactDatabase(
        at url: URL,
        ownerKey: String,
        sourceID: String,
        payload: String
    ) throws {
        var database: OpaquePointer?
        guard sqlite3_open(url.path, &database) == SQLITE_OK, let database else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        defer { sqlite3_close(database) }
        try execute(
            "CREATE TABLE reader_local_exact(owner_key TEXT NOT NULL, source_id TEXT NOT NULL, progress_document TEXT NOT NULL, updated_at_epoch_millis INTEGER NOT NULL, PRIMARY KEY(owner_key, source_id))",
            database: database
        )
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(
            database,
            "INSERT INTO reader_local_exact(owner_key, source_id, progress_document, updated_at_epoch_millis) VALUES(?, ?, ?, 444)",
            -1,
            &statement,
            nil
        ) == SQLITE_OK, let statement else { throw IosReaderFailure(code: .persistenceFailed) }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, ownerKey, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        sqlite3_bind_text(statement, 2, sourceID, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        sqlite3_bind_text(statement, 3, payload, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        guard sqlite3_step(statement) == SQLITE_DONE else { throw IosReaderFailure(code: .persistenceFailed) }
    }

    private func exactRowExists(ownerKey: String, sourceID: String, databaseURL: URL) throws -> Bool {
        var database: OpaquePointer?
        guard sqlite3_open(databaseURL.path, &database) == SQLITE_OK, let database else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        defer { sqlite3_close(database) }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(
            database,
            "SELECT 1 FROM reader_local_exact WHERE owner_key = ? AND source_id = ?",
            -1,
            &statement,
            nil
        ) == SQLITE_OK, let statement else { throw IosReaderFailure(code: .persistenceFailed) }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, ownerKey, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        sqlite3_bind_text(statement, 2, sourceID, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        return sqlite3_step(statement) == SQLITE_ROW
    }

    private func tableExists(_ name: String, databaseURL: URL) throws -> Bool {
        var database: OpaquePointer?
        guard sqlite3_open(databaseURL.path, &database) == SQLITE_OK, let database else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        defer { sqlite3_close(database) }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(
            database,
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            -1,
            &statement,
            nil
        ) == SQLITE_OK, let statement else { throw IosReaderFailure(code: .persistenceFailed) }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_text(statement, 1, name, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        return sqlite3_step(statement) == SQLITE_ROW
    }

    private func execute(_ sql: String, database: OpaquePointer) throws {
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }
}

private enum TestUploadFailure: Error {
    case expected
}

private final class RecordingReaderProgressPort: ErmaoShared.ReaderProgressSyncPort, @unchecked Sendable {
    private let lock = NSLock()
    private let failure: Error?
    private var uploads: [ErmaoShared.ReaderProgressUpload] = []

    init(failure: Error? = nil) {
        self.failure = failure
    }

    var uploadCount: Int { withLock { uploads.count } }
    var lastPercent: Double? { withLock { uploads.last?.snapshot.percent } }
    var lastServerFingerprint: String? {
        withLock { uploads.last?.snapshot.serverContentFingerprint.value }
    }
    var lastLocalContentHash: String? {
        withLock { uploads.last?.snapshot.anchor?.contentFingerprint?.originalFileHash }
    }
    var lastLocatorPayload: String? {
        withLock { uploads.last?.snapshot.anchor?.engineLocator?.payload.canonicalJson }
    }

    func push(upload: ErmaoShared.ReaderProgressUpload) async throws -> ErmaoShared.ReaderProgressPushResult {
        withLock { uploads.append(upload) }
        if let failure { throw failure }
        return ErmaoShared.ReaderProgressPushResultAccepted(snapshot: upload.snapshot)
    }

    private func withLock<T>(_ operation: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return operation()
    }
}

private final class BlockingReaderProgressPort: ErmaoShared.ReaderProgressSyncPort, @unchecked Sendable {
    private let lock = NSLock()
    private var uploads: [Int64] = []
    private var firstContinuation: CheckedContinuation<Void, Never>?

    var uploadedTimestamps: [Int64] { withLock { uploads } }

    func push(upload: ErmaoShared.ReaderProgressUpload) async throws -> ErmaoShared.ReaderProgressPushResult {
        let shouldBlock = withLock {
            uploads.append(upload.snapshot.updatedAtEpochMillis)
            return uploads.count == 1
        }
        if shouldBlock {
            await withCheckedContinuation { continuation in
                withLock { firstContinuation = continuation }
            }
        }
        return ErmaoShared.ReaderProgressPushResultAccepted(snapshot: upload.snapshot)
    }

    func waitUntilFirstUploadStarts() async {
        while withLock({ uploads.isEmpty || firstContinuation == nil }) { await Task.yield() }
    }

    func releaseFirstUpload() {
        let continuation = withLock {
            let current = firstContinuation
            firstContinuation = nil
            return current
        }
        continuation?.resume()
    }

    private func withLock<T>(_ operation: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return operation()
    }
}
