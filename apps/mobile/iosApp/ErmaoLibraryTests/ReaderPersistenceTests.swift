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

    @MainActor
    func testReaderUsesFiveHundredMillisecondTrailingSave() {
        XCTAssertEqual(IosReflowableReaderSession.progressSaveDebounceMilliseconds, 500)
    }

    func testReaderPreferencesMatchWebDefaultsAndPersistPerServerUser() {
        let suite = "reader-preferences-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let first = IosReaderPreferencesStore(serverIdentity: "server-a", userID: "user-a", defaults: defaults)
        let anotherUser = IosReaderPreferencesStore(serverIdentity: "server-a", userID: "user-b", defaults: defaults)

        let initial = first.load()
        XCTAssertEqual(initial.theme, .warm)
        XCTAssertEqual(initial.fontSize, 18)
        XCTAssertEqual(initial.lineHeight, 1.9)
        XCTAssertEqual(initial.spreadMode, .single)
        XCTAssertEqual(initial.readingMode, .paged)

        var changed = initial
        changed.theme = .green
        changed.fontSize = 24
        changed.comicDirection = .rtl
        changed.comicSpread = .double
        changed.comicCoverSingle = true
        changed.comicPageGap = 16
        changed.pdfZoom = 1.4
        changed.pdfFit = .width
        changed.pdfRotation = 90
        changed.pdfCropMargins = .auto
        XCTAssertTrue(first.save(changed))
        XCTAssertEqual(first.load(), changed)
        XCTAssertEqual(anotherUser.load(), IosReaderPreferences())
        XCTAssertEqual(first.reset(), IosReaderPreferences())
    }

    @MainActor
    func testPreferenceWriterCoalescesAndRollsBackFailure() async {
        var stored: [IosReaderPreferences] = []
        var shouldFail = false
        let writer = IosReaderPreferenceEditor(preferences: IosReaderPreferences()) { requested in
            await Task.yield()
            if shouldFail { return false }
            stored.append(requested)
            return true
        }
        writer.change { $0.fontSize = 20 }
        writer.change { $0.fontSize = 24 }
        writer.change { $0.lineHeight = 2.2 }
        await writer.flush()
        XCTAssertEqual(stored.last?.fontSize, 24)
        XCTAssertEqual(stored.last?.lineHeight, 2.2)
        XCTAssertEqual(stored.count, 1)
        shouldFail = true
        writer.change { $0.fontSize = 30 }
        await writer.flush()
        XCTAssertTrue(writer.applyFailed)
        XCTAssertEqual(writer.draft.fontSize, 24)
        XCTAssertEqual(stored.count, 1)
    }

    func testScopedResetPreservesOtherReaderPreferences() {
        var preferences = IosReaderPreferences()
        preferences.fontSize = 24
        preferences.comicPageGap = 16
        preferences.pdfRotation = 90
        preferences.theme = .night
        let text = preferences.reset(for: .reflowable)
        XCTAssertEqual(text.fontSize, 18)
        XCTAssertEqual(text.comicPageGap, 16)
        XCTAssertEqual(text.pdfRotation, 90)
        XCTAssertEqual(text.theme, .warm)
        XCTAssertEqual(preferences.reset(for: .comic).fontSize, 24)
        XCTAssertEqual(preferences.reset(for: .pdf).comicPageGap, 16)
    }

    func testEveryReflowCallbackAndFlushRemainSuppressedUntilUserNavigation() {
        var gate = IosReaderPersistenceGate()
        gate.beginUserNavigation()
        gate.suppressPreferenceReflow()
        for position in 1 ... 5 {
            XCTAssertFalse(gate.observeLocationChange(.init(href: "chapter.xhtml", progression: Double(position) / 10, totalProgression: nil, position: position)))
        }
        XCTAssertFalse(gate.canPersistCurrentLocation)
        gate.beginUserNavigation()
        XCTAssertTrue(gate.canPersistCurrentLocation)
    }

    func testPreferenceReflowObservationDoesNotBecomeUserNavigation() {
        var gate = IosReaderPersistenceGate()
        gate.protectRestoredLocation(.init(
            href: "chapter.xhtml",
            progression: 0.5,
            totalProgression: 0.6,
            position: 12
        ))
        gate.suppressPreferenceReflow()

        XCTAssertFalse(gate.observeLocationChange(.init(
            href: "chapter.xhtml",
            progression: 0.45,
            totalProgression: 0.6,
            position: 12
        )))
        XCTAssertFalse(gate.hasLocalReadingActivity)
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
            identity: makeIdentity(authorizationVersion: 4, resourceID: "volume-a"),
            databaseURL: databaseURL
        )
        let progress = try decodeProgress(sourceID: "volume-a", updatedAt: 1_775_988_123_456)

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
            identity: makeIdentity(authorizationVersion: 4, resourceID: "volume-a"),
            databaseURL: databaseURL
        )
        try await v4.save(progress: try decodeProgress(sourceID: "volume-a", updatedAt: 1_775_988_123_456))

        let v5 = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "volume-a"),
            databaseURL: databaseURL
        )
        let restored = try await v5.load(sourceId: "volume-a")

        XCTAssertEqual(restored?.resourceId, "volume-a")
        XCTAssertEqual(restored?.updatedAtEpochMillis, 1_775_988_123_456)
    }

    func testExactIdentityIncludesEveryStableLocalOwnerComponentButNotAuthorizationVersion() {
        let baseline = makeIdentity(authorizationVersion: 4, resourceID: "volume-a")
        XCTAssertEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 5, resourceID: "volume-a").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, resourceID: "volume-a", clientID: "other-client").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, resourceID: "volume-b").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 4, bookID: "work-b", resourceID: "volume-a").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                namespace: makeNamespace(
                    authorizationVersion: 4,
                    serverIdentity: "server-b"
                ),
                resourceID: "volume-a"
            ).stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                namespace: makeNamespace(
                    authorizationVersion: 4,
                    userID: "user-b"
                ),
                resourceID: "volume-a"
            ).stableKey
        )
    }

    func testExactIdentitySeparatesClientButKeepsProgressForTheVolume() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let primary = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "volume-a"),
            databaseURL: databaseURL
        )
        try await primary.save(progress: try decodeProgress(sourceID: "volume-a", updatedAt: 100))

        let anotherClient = try IosReaderLocalDatabase(
            identity: makeIdentity(
                authorizationVersion: 4,
                resourceID: "volume-a",
                clientID: "ios-installation-d"
            ),
            databaseURL: databaseURL
        )
        let sameVolume = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "volume-a"),
            databaseURL: databaseURL
        )

        let otherClientBeforeSave = try await anotherClient.load(sourceId: "volume-a")
        let sameVolumeBeforeSave = try await sameVolume.load(sourceId: "volume-a")
        XCTAssertNil(otherClientBeforeSave)
        XCTAssertEqual(sameVolumeBeforeSave?.updatedAtEpochMillis, 100)

        try await sameVolume.save(progress: try decodeProgress(
            sourceID: "volume-a",
            updatedAt: 200
        ))
        let originalRestored = try await primary.load(sourceId: "volume-a")
        let sameVolumeRestored = try await sameVolume.load(sourceId: "volume-a")
        XCTAssertEqual(originalRestored?.updatedAtEpochMillis, 200)
        XCTAssertEqual(sameVolumeRestored?.updatedAtEpochMillis, 200)
    }

    func testLatestLocalSaveOverwritesEvenWhenWallClockMovesBackward() async throws {
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "volume-a"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        try await store.save(progress: try decodeProgress(sourceID: "volume-a", updatedAt: 200))
        try await store.save(progress: try decodeProgress(sourceID: "volume-a", updatedAt: 100))

        let restored = try await store.load(sourceId: "volume-a")
        XCTAssertEqual(restored?.updatedAtEpochMillis, 100)
    }

    func testLegacyR4SQLiteIsDiscardedWithSyncTables() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let namespace = makeNamespace(authorizationVersion: 4)
        try createLegacyR4Database(
            at: databaseURL,
            namespaceKey: namespace.stableKey,
            sourceID: "legacy-r4-volume",
            payload: progressPayload(sourceID: "legacy-r4-volume", updatedAt: 1_775_988_323_456)
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, resourceID: "legacy-r4-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "legacy-r4-volume")

        XCTAssertNil(migrated)
        XCTAssertTrue(try tableExists("reader_local_exact", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_progress", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_outbox", databaseURL: databaseURL))
        XCTAssertFalse(try tableExists("reader_sequence_counters", databaseURL: databaseURL))

        let reauthenticated = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "legacy-r4-volume"),
            databaseURL: databaseURL
        )
        let afterReauthentication = try await reauthenticated.load(sourceId: "legacy-r4-volume")
        XCTAssertNil(afterReauthentication)
    }

    func testIncompleteExactKeyIsDiscardedAtTheUnionBoundary() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let oldOwnerKey = "8:server-a6:user-a"
        try createIncompleteExactDatabase(
            at: databaseURL,
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            payload: progressPayload(sourceID: "preview-volume", updatedAt: 444)
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 9, resourceID: "preview-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "preview-volume")

        XCTAssertNil(migrated)
        XCTAssertFalse(try exactRowExists(
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            databaseURL: databaseURL
        ))
    }

    func testIncompleteExactKeyFromAnotherClientIsDiscarded() async throws {
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
            identity: makeIdentity(authorizationVersion: 9, resourceID: "preview-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "preview-volume")

        XCTAssertNil(migrated)
        XCTAssertFalse(try exactRowExists(
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            databaseURL: databaseURL
        ))
    }

    func testIncompleteExactKeyIsDiscarded() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        let oldOwnerKey = "8:server-a6:user-a"
        try createIncompleteExactDatabase(
            at: databaseURL,
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            payload: progressPayload(
                sourceID: "preview-volume",
                updatedAt: 444
            )
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 9, resourceID: "preview-volume"),
            databaseURL: databaseURL
        )
        let migrated = try await store.load(sourceId: "preview-volume")

        XCTAssertNil(migrated)
        XCTAssertFalse(try exactRowExists(
            ownerKey: oldOwnerKey,
            sourceID: "preview-volume",
            databaseURL: databaseURL
        ))
    }

    func testUnrecognizedLegacyR4ExactTableIsDiscarded() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        try createLegacyR4Database(
            at: databaseURL,
            namespaceKey: "not-a-length-prefixed-namespace",
            sourceID: "legacy-r4-volume",
            payload: progressPayload(sourceID: "legacy-r4-volume", updatedAt: 1_775_988_323_456)
        )

        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "legacy-r4-volume"),
            databaseURL: databaseURL
        )
        _ = try await store.load(sourceId: "legacy-r4-volume")

        XCTAssertFalse(try tableExists("reader_progress", databaseURL: databaseURL))
    }

    func testLegacyProgressFileIsDiscarded() async throws {
        let legacyRoot = temporaryRoot.appendingPathComponent("Progress", isDirectory: true)
        try FileManager.default.createDirectory(at: legacyRoot, withIntermediateDirectories: true)
        let legacyURL = legacyProgressURL(sourceID: "legacy-volume", root: legacyRoot)
        try Data(progressPayload(sourceID: "legacy-volume", updatedAt: 1_775_988_323_456).utf8)
            .write(to: legacyURL)
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "legacy-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3"),
            legacyProgressRoot: legacyRoot
        )

        let migrated = try await store.load(sourceId: "legacy-volume")

        XCTAssertNil(migrated)
        XCTAssertFalse(FileManager.default.fileExists(atPath: legacyURL.path))
    }

    func testInvalidLegacyProgressFileIsDiscarded() async throws {
        let legacyRoot = temporaryRoot.appendingPathComponent("Progress", isDirectory: true)
        try FileManager.default.createDirectory(at: legacyRoot, withIntermediateDirectories: true)
        let legacyURL = legacyProgressURL(sourceID: "expected-volume", root: legacyRoot)
        try Data(progressPayload(sourceID: "another-volume", updatedAt: 1_775_988_323_456).utf8)
            .write(to: legacyURL)
        let store = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "expected-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3"),
            legacyProgressRoot: legacyRoot
        )

        let loaded = try await store.load(sourceId: "expected-volume")
        XCTAssertNil(loaded)
        XCTAssertFalse(FileManager.default.fileExists(atPath: legacyURL.path))
    }

    func testUploadFailureKeepsDurableExactPendingMutation() async throws {
        let namespace = makeNamespace(authorizationVersion: 4)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, resourceID: "upload-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        let port = RecordingReaderProgressPort(failure: TestUploadFailure.expected)
        let runtime = ErmaoShared.PublicKt.createReaderProgressSyncRuntime(
            stateStore: database,
            target: makeTarget(namespace: namespace, resourceID: "upload-volume"),
            server: port
        )
        let store = runtime.store
        let progress = try decodeProgress(sourceID: "upload-volume", updatedAt: 1_775_988_523_456)

        try await store.save(progress: progress)
        try await store.awaitPendingUpload()
        let restored = try await store.load(sourceId: "upload-volume")
        let state = try await store.syncState()

        XCTAssertEqual(restored?.updatedAtEpochMillis, progress.updatedAtEpochMillis)
        XCTAssertEqual(port.uploadCount, 1)
        XCTAssertNotNil(state.pending)
        XCTAssertEqual(state.pending?.capturedAtEpochMillis, progress.updatedAtEpochMillis)
        XCTAssertTrue(port.lastLocatorPayload?.contains("chapter.xhtml") == true)
        runtime.close()
        await database.close()
    }

    func testLocalOnlyProgressStorePersistsWithoutCreatingPendingUpload() async throws {
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "offline-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        let store = IosLocalOnlyReaderProgressStore(database: database)
        let progress = try decodeProgress(sourceID: "offline-volume", updatedAt: 1_775_988_623_456)

        try await store.save(progress: progress)
        try await store.retryPendingUpload()
        try await store.awaitPendingUpload()

        let restored = try await store.load(sourceId: "offline-volume")
        let state = try await store.syncState()
        XCTAssertEqual(restored?.updatedAtEpochMillis, progress.updatedAtEpochMillis)
        XCTAssertNil(state.pending)
        await database.close()
    }

    func testSingleFlightUploadKeepsOnlyLatestWaitingLocation() async throws {
        let namespace = makeNamespace(authorizationVersion: 4)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, resourceID: "single-flight-volume"),
            databaseURL: temporaryRoot.appendingPathComponent("Reader.sqlite3")
        )
        let port = BlockingReaderProgressPort()
        let runtime = ErmaoShared.PublicKt.createReaderProgressSyncRuntime(
            stateStore: database,
            target: makeTarget(namespace: namespace, resourceID: "single-flight-volume"),
            server: port
        )
        let store = runtime.store

        try await store.save(progress: try decodeProgress(sourceID: "single-flight-volume", updatedAt: 100))
        await port.waitUntilFirstUploadStarts()
        try await store.save(progress: try decodeProgress(sourceID: "single-flight-volume", updatedAt: 200))
        try await store.save(progress: try decodeProgress(sourceID: "single-flight-volume", updatedAt: 300))
        port.releaseFirstUpload()
        try await store.awaitPendingUpload()

        XCTAssertEqual(port.uploadedTimestamps, [100, 300])
        let restored = try await store.load(sourceId: "single-flight-volume")
        XCTAssertEqual(restored?.updatedAtEpochMillis, 300)
        runtime.close()
        await database.close()
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
        bookID: String = "work-a",
        resourceID: String,
        clientID: String = "ios-installation-c"
    ) -> ErmaoShared.ReaderLocalProgressIdentity {
        makeIdentity(
            namespace: makeNamespace(authorizationVersion: authorizationVersion),
            bookID: bookID,
            resourceID: resourceID,
            clientID: clientID
        )
    }

    private func makeIdentity(
        namespace: ErmaoShared.ReaderSyncNamespace,
        bookID: String = "work-a",
        resourceID: String,
        clientID: String = "ios-installation-c"
    ) -> ErmaoShared.ReaderLocalProgressIdentity {
        ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: clientID,
            bookId: bookID,
            resourceId: resourceID
        )
    }

    private func decodeProgress(
        sourceID: String,
        updatedAt: Int64,
        clientID: String = "ios-installation-c"
    ) throws -> ErmaoShared.ReaderProgress {
        try ErmaoShared.PublicKt.createReaderProgressJson().decode(payload: progressPayload(
            sourceID: sourceID,
            updatedAt: updatedAt,
            clientID: clientID
        ))
    }

    private func makeTarget(
        namespace: ErmaoShared.ReaderSyncNamespace,
        resourceID: String
    ) -> ErmaoShared.ReaderProgressSyncTarget {
        ErmaoShared.ReaderProgressSyncTarget(
            namespace: namespace,
            bookId: "work-a",
            resourceId: resourceID,
            sourceFormat: .epub
        )
    }

    private func progressPayload(
        sourceID: String,
        updatedAt: Int64,
        clientID: String = "ios-installation-c"
    ) -> String {
        ##"{"schema":"ermao.reader-progress","version":7,"resourceId":"\##(sourceID)","location":{"kind":"reflow","resourceKey":"chapter.xhtml","progression":0.5,"engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#reader-block","progression":0.5},"text":{"highlight":"Reader block"}}}},"updatedAtEpochMillis":\##(updatedAt),"deviceId":"\##(clientID)","percent":50.0}"##
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

private final class RecordingReaderProgressPort: ErmaoShared.ReaderProgressServerPort, @unchecked Sendable {
    private let lock = NSLock()
    private let failure: Error?
    private var uploads: [ErmaoShared.ReaderProgressUpload] = []

    init(failure: Error? = nil) {
        self.failure = failure
    }

    var uploadCount: Int { withLock { uploads.count } }
    var lastLocatorPayload: String? {
        withLock {
            (uploads.last?.mutation.locator as? ErmaoShared.ReflowablePublicationLocation)?
                .readiumEnvelope.payload.canonicalJson
        }
    }

    func push(upload: ErmaoShared.ReaderProgressUpload) async throws -> ErmaoShared.ReaderProgressPushResult {
        withLock { uploads.append(upload) }
        if let failure { throw failure }
        return ErmaoShared.ReaderProgressPushResultAccepted(
            snapshot: ErmaoShared.ReaderProgressSnapshotV4(
                resourceId: upload.target.resourceId,
                clientId: upload.mutation.clientId,
                revision: upload.mutation.baseRevision + 1,
                locator: upload.mutation.locator,
                displayPercent: 50,
                receivedAtEpochMillis: upload.mutation.capturedAtEpochMillis,
                capturedAtEpochMillis: KotlinLong(longLong: upload.mutation.capturedAtEpochMillis)
            )
        )
    }

    func load(
        target: ErmaoShared.ReaderProgressSyncTarget,
        etag: String?
    ) async throws -> ErmaoShared.ReaderProgressQueryResult {
        ErmaoShared.ReaderProgressQueryResultCurrent(snapshot: nil, etag: etag)
    }

    private func withLock<T>(_ operation: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return operation()
    }
}

private final class BlockingReaderProgressPort: ErmaoShared.ReaderProgressServerPort, @unchecked Sendable {
    private let lock = NSLock()
    private var uploads: [Int64] = []
    private var firstContinuation: CheckedContinuation<Void, Never>?

    var uploadedTimestamps: [Int64] { withLock { uploads } }

    func push(upload: ErmaoShared.ReaderProgressUpload) async throws -> ErmaoShared.ReaderProgressPushResult {
        let shouldBlock = withLock {
            uploads.append(upload.mutation.capturedAtEpochMillis)
            return uploads.count == 1
        }
        if shouldBlock {
            await withCheckedContinuation { continuation in
                withLock { firstContinuation = continuation }
            }
        }
        return ErmaoShared.ReaderProgressPushResultAccepted(
            snapshot: ErmaoShared.ReaderProgressSnapshotV4(
                resourceId: upload.target.resourceId,
                clientId: upload.mutation.clientId,
                revision: upload.mutation.baseRevision + 1,
                locator: upload.mutation.locator,
                displayPercent: 50,
                receivedAtEpochMillis: upload.mutation.capturedAtEpochMillis,
                capturedAtEpochMillis: KotlinLong(longLong: upload.mutation.capturedAtEpochMillis)
            )
        )
    }

    func load(
        target: ErmaoShared.ReaderProgressSyncTarget,
        etag: String?
    ) async throws -> ErmaoShared.ReaderProgressQueryResult {
        ErmaoShared.ReaderProgressQueryResultCurrent(snapshot: nil, etag: etag)
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
