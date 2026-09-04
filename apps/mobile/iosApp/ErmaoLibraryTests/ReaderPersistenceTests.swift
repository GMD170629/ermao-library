import CryptoKit
import Foundation
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
            .appendingPathComponent("reader-v5-store-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryRoot, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let temporaryRoot { try? FileManager.default.removeItem(at: temporaryRoot) }
    }

    func testProgressArrowsResolveAdjacentReflowableChaptersWithoutLooping() {
        let chapters = [
            IosReaderTocEntry(id: "one", title: "One", href: "one.xhtml", depth: 0),
            IosReaderTocEntry(id: "two", title: "Two", href: "two.xhtml", depth: 0),
            IosReaderTocEntry(id: "three", title: "Three", href: "three.xhtml", depth: 0),
        ]
        let first = resolveIosReaderAdjacentChapters(entries: chapters, currentHref: "one.xhtml")
        XCTAssertNil(first.previous)
        XCTAssertEqual(first.next?.id, "two")
        let middle = resolveIosReaderAdjacentChapters(entries: chapters, currentHref: "two.xhtml")
        XCTAssertEqual(middle.previous?.id, "one")
        XCTAssertEqual(middle.next?.id, "three")
        let last = resolveIosReaderAdjacentChapters(entries: chapters, currentHref: "three.xhtml")
        XCTAssertEqual(last.previous?.id, "two")
        XCTAssertNil(last.next)

        let fragmentChapters = [
            IosReaderTocEntry(id: "one", title: "One", href: "book.xhtml#one", depth: 0),
            IosReaderTocEntry(id: "two", title: "Two", href: "book.xhtml#two", depth: 0),
            IosReaderTocEntry(id: "three", title: "Three", href: "book.xhtml#three", depth: 0),
        ]
        let adjacent = resolveIosReaderAdjacentChapters(
            entries: fragmentChapters,
            currentHref: "book.xhtml",
            fragments: ["two"]
        )
        XCTAssertEqual(adjacent.previous?.id, "one")
        XCTAssertEqual(adjacent.next?.id, "three")
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
        XCTAssertEqual(initial.readingProgression, .ltr)
        XCTAssertEqual(initial.writingMode, .horizontal)
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
        let failureState = PreferenceFailureState()
        let writer = IosReaderPreferenceEditor(preferences: IosReaderPreferences()) { requested in
            await Task.yield()
            if failureState.shouldFail { return false }
            stored.append(requested)
            return true
        }
        writer.change { $0.fontSize = 20 }
        writer.change { $0.fontSize = 24 }
        writer.change { $0.lineHeight = 2.2 }
        await writer.flush()
        XCTAssertEqual(stored.count, 1)
        XCTAssertEqual(stored.last?.fontSize, 24)
        XCTAssertEqual(stored.last?.lineHeight, 2.2)
        failureState.shouldFail = true
        writer.change { $0.fontSize = 30 }
        await writer.flush()
        XCTAssertTrue(writer.applyFailed)
        XCTAssertEqual(writer.draft.fontSize, 24)
        XCTAssertEqual(stored.count, 1)
    }

    func testCurrentPreferenceRecordIsCanonicalAndInvalidDataIsPreserved() throws {
        let suite = "reader-preference-record-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = IosReaderPreferencesStore(serverIdentity: "server-a", userID: "alice", defaults: defaults)
        let other = IosReaderPreferencesStore(serverIdentity: "server-a", userID: "bob", defaults: defaults)
        let digest = SHA256.hash(data: Data("server-a\0alice".utf8))
        let key = "reader.preferences." + digest.map { String(format: "%02x", $0) }.joined()
        var preferences = IosReaderPreferences()
        preferences.fontSize = 20
        preferences.lineHeight = 1.85
        preferences.letterSpacing = 0.03
        preferences.preservePublisherStyles = true
        preferences.comicZoom = 1.7
        preferences.pdfZoom = 1.3
        XCTAssertTrue(store.save(preferences))
        XCTAssertEqual(store.load(), preferences)
        let stored = try XCTUnwrap(defaults.data(forKey: key))
        XCTAssertEqual(other.load(), IosReaderPreferences())
        let document = try XCTUnwrap(JSONSerialization.jsonObject(with: stored) as? [String: Any])
        XCTAssertEqual(document["schemaVersion"] as? Int, Int(ErmaoShared.ReaderPreferences.companion.SCHEMA_VERSION))
        XCTAssertEqual((document["epub"] as? [String: Any])?["readingProgression"] as? String, "ltr")
        XCTAssertEqual((document["epub"] as? [String: Any])?["writingMode"] as? String, "horizontal")
        let invalid = Data("{invalid".utf8)
        defaults.set(invalid, forKey: key)
        XCTAssertEqual(store.load(), IosReaderPreferences())
        XCTAssertEqual(defaults.data(forKey: key), invalid)
    }

    func testReadingProgressionAndWritingModeIndependentlyControlReadium() {
        var preferences = IosReaderPreferences()
        preferences.readingMode = .paged
        preferences.spreadMode = .double
        let horizontal = preferences.readium(for: .light)
        XCTAssertEqual(horizontal.readingProgression, .ltr)
        XCTAssertEqual(horizontal.verticalText, false)
        XCTAssertEqual(horizontal.scroll, false)

        preferences.writingMode = .vertical
        let vertical = preferences.readium(for: .light)
        XCTAssertEqual(vertical.readingProgression, .ltr)
        XCTAssertEqual(vertical.verticalText, true)
        XCTAssertEqual(vertical.scroll, true)

        preferences.readingProgression = .rtl
        let verticalRTL = preferences.readium(for: .light)
        XCTAssertEqual(verticalRTL.readingProgression, .rtl)
        XCTAssertEqual(verticalRTL.verticalText, true)
        XCTAssertEqual(verticalRTL.scroll, true)

        preferences.writingMode = .horizontal
        let restored = preferences.readium(for: .light)
        XCTAssertEqual(restored.readingProgression, .rtl)
        XCTAssertEqual(restored.verticalText, false)
        XCTAssertEqual(restored.scroll, false)
        XCTAssertEqual(preferences.spreadMode, .double)

        preferences.writingMode = .vertical
        let fixed = preferences.readium(for: .light, appliesTextDirectionPreferences: false)
        XCTAssertNil(fixed.readingProgression)
        XCTAssertNil(fixed.verticalText)
        XCTAssertEqual(fixed.scroll, false)
    }

    @MainActor
    func testResetClearsEveryReaderFormatPreference() async {
        var preferences = IosReaderPreferences()
        preferences.fontSize = 24
        preferences.comicPageGap = 16
        preferences.pdfRotation = 90
        preferences.theme = .night
        var saved: IosReaderPreferences?
        let editor = IosReaderPreferenceEditor(preferences: preferences) {
            saved = $0
            return true
        }

        editor.reset()
        await editor.flush()

        XCTAssertEqual(editor.draft, IosReaderPreferences())
        XCTAssertEqual(saved, IosReaderPreferences())
    }

    func testV5PositionRoundTripsWithoutCreatingPendingMutation() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: databaseURL
        )
        let position = try makePosition(resourceID: "resource-a", capturedAt: 1_786_500_000_000, percent: 99)

        try await database.savePosition(position: position)
        let restored = try await database.loadPosition(resourceId: "resource-a")
        let state = try await database.loadPositionSyncState()

        XCTAssertEqual(restored?.capturedAtEpochMillis, position.capturedAtEpochMillis)
        XCTAssertEqual(restored?.position.presentation.displayPercent, 99)
        XCTAssertEqual(restored?.position.locator.canonicalJson, position.position.locator.canonicalJson)
        XCTAssertNil(state.pending)
        await database.close()
    }

    func testV5PositionSurvivesAuthorizationVersionRollover() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        let first = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 4, resourceID: "resource-a"),
            databaseURL: databaseURL
        )
        try await first.savePosition(position: makePosition(resourceID: "resource-a", capturedAt: 100, percent: 25))
        await first.close()
        let reauthenticated = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: databaseURL
        )
        let restored = try await reauthenticated.loadPosition(resourceId: "resource-a")
        XCTAssertEqual(restored?.position.presentation.displayPercent, 25)
        await reauthenticated.close()
    }

    func testV5IdentityIncludesStableOwnerComponentsButNotAuthorizationVersion() {
        let baseline = makeIdentity(authorizationVersion: 4, resourceID: "resource-a")
        XCTAssertEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 5, resourceID: "resource-a").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                authorizationVersion: 5,
                resourceID: "resource-a",
                clientID: "other-client"
            ).stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(authorizationVersion: 5, resourceID: "resource-b").stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                authorizationVersion: 5,
                bookID: "book-b",
                resourceID: "resource-a"
            ).stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                namespace: makeNamespace(
                    authorizationVersion: 5,
                    serverIdentity: "server-b"
                ),
                resourceID: "resource-a"
            ).stableKey
        )
        XCTAssertNotEqual(
            baseline.stableKey,
            makeIdentity(
                namespace: makeNamespace(
                    authorizationVersion: 5,
                    userID: "user-b"
                ),
                resourceID: "resource-a"
            ).stableKey
        )
    }

    func testV5IdentitySeparatesInstallationsButSharesOneInstallationVolume() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        let primary = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: databaseURL
        )
        try await primary.savePosition(position: makePosition(
            resourceID: "resource-a", capturedAt: 100, percent: 10
        ))

        let anotherInstallation = try IosReaderLocalDatabase(
            identity: makeIdentity(
                authorizationVersion: 5,
                resourceID: "resource-a",
                clientID: "ios-installation-d"
            ),
            databaseURL: databaseURL
        )
        let sameInstallation = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: databaseURL
        )

        let otherInstallationPosition = try await anotherInstallation.loadPosition(
            resourceId: "resource-a"
        )
        XCTAssertNil(otherInstallationPosition)
        let sameInstallationPosition = try await sameInstallation.loadPosition(
            resourceId: "resource-a"
        )
        XCTAssertEqual(
            sameInstallationPosition?.capturedAtEpochMillis,
            100
        )
        try await sameInstallation.savePosition(position: makePosition(
            resourceID: "resource-a", capturedAt: 200, percent: 20
        ))
        let primaryPosition = try await primary.loadPosition(resourceId: "resource-a")
        XCTAssertEqual(primaryPosition?.capturedAtEpochMillis, 200)

        await sameInstallation.close()
        await anotherInstallation.close()
        await primary.close()
    }

    func testLatestLocalSaveWinsEvenWhenClientClockMovesBackward() async throws {
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        )
        try await database.savePosition(position: makePosition(resourceID: "resource-a", capturedAt: 200, percent: 99))
        try await database.savePosition(position: makePosition(resourceID: "resource-a", capturedAt: 100, percent: 25))
        let restored = try await database.loadPosition(resourceId: "resource-a")
        XCTAssertEqual(restored?.capturedAtEpochMillis, 100)
        XCTAssertEqual(restored?.position.presentation.displayPercent, 25)
        await database.close()
    }

    func testFreshV5DatabaseDoesNotReadSiblingV4Files() async throws {
        let oldURL = temporaryRoot.appendingPathComponent("Reader.sqlite3")
        try Data("legacy-v4-do-not-read".utf8).write(to: oldURL)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        )
        let position = try await database.loadPosition(resourceId: "resource-a")
        XCTAssertNil(position)
        XCTAssertEqual(try Data(contentsOf: oldURL), Data("legacy-v4-do-not-read".utf8))
        await database.close()
    }

    func testReaderV5DoesNotDeleteLegacyPdfRangeCache() async throws {
        let caches = temporaryRoot.appendingPathComponent("Caches", isDirectory: true)
        let legacyRanges = caches
            .appendingPathComponent("reader", isDirectory: true)
            .appendingPathComponent("pdf-range-v1", isDirectory: true)
        try FileManager.default.createDirectory(at: legacyRanges, withIntermediateDirectories: true)
        let marker = legacyRanges.appendingPathComponent("marker")
        try Data("legacy-range-cache".utf8).write(to: marker)

        let fileManager = ReaderPersistenceTestFileManager(cachesURL: caches)
        let store = try IosManagedPublicationStore(
            root: temporaryRoot.appendingPathComponent("Publications", isDirectory: true),
            fileManager: fileManager
        )
        try await store.removeAutomaticReplica(
            resourceID: "resource-without-replica",
            assetID: "asset",
            namespace: "server|user|5"
        )

        XCTAssertTrue(FileManager.default.fileExists(atPath: marker.path))
        XCTAssertEqual(try Data(contentsOf: marker), Data("legacy-range-cache".utf8))
    }

    @MainActor
    func testDetailPresentationLoaderReturnsLocalV5ValueAheadOfServerRefresh() async throws {
        let databaseURL = temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        let namespace = makeNamespace(authorizationVersion: 5)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, resourceID: "resource-a"),
            databaseURL: databaseURL
        )
        try await database.savePosition(position: makePosition(
            resourceID: "resource-a",
            capturedAt: 1_786_500_000_000,
            percent: 99
        ))
        await database.close()

        let suite = "reader-v5-detail-overlay-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("ios-installation-c", forKey: "reader.installation.device-id")
        let context = ContentRequestContext(
            profileID: "profile-a",
            profileDisplayName: "Server A",
            serverIdentity: "server-a",
            userID: "user-a",
            authorizationVersion: 5,
            baseURL: "https://library.example",
            acceptsInsecureTLS: false
        )

        let updates = await ReaderProgressPresentationCenter.shared.loadLocalUpdates(
            context: context,
            bookID: "book-a",
            resourceIDs: ["resource-a"],
            deviceIdentity: IosReaderDeviceIdentity(defaults: defaults),
            databaseURL: databaseURL
        )

        XCTAssertEqual(updates.count, 1)
        XCTAssertEqual(updates.first?.position.presentation.displayPercent, 99)
        XCTAssertEqual(updates.first?.position.presentation.totalProgression, 0.99)
    }

    func testUploadFailureKeepsExactV5MutationBody() async throws {
        let namespace = makeNamespace(authorizationVersion: 5)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, resourceID: "resource-a"),
            databaseURL: temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        )
        let port = RecordingReaderPositionPort(failure: TestUploadFailure.expected)
        let runtime = ErmaoShared.PublicKt.createReaderPositionSyncRuntime(
            stateStore: database,
            target: makeTarget(namespace: namespace, resourceID: "resource-a"),
            server: port
        )
        let position = try makePosition(resourceID: "resource-a", capturedAt: 300, percent: 99)
        try await runtime.store.save(position: position)
        try await runtime.store.awaitPendingUpload()
        let state = try await runtime.store.syncState()
        XCTAssertEqual(port.uploadCount, 1)
        XCTAssertEqual(state.pending?.position.locator.canonicalJson, position.position.locator.canonicalJson)
        XCTAssertEqual(state.pending?.position.presentation.displayPercent, 99)
        runtime.close()
        await database.close()
    }

    func testLocalOnlyStoreCreatesNoPendingUpload() async throws {
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        )
        let store = IosLocalOnlyReaderProgressStore(database: database)
        let position = try makePosition(resourceID: "resource-a", capturedAt: 400, percent: 99)
        try await store.save(position: position)
        let restored = try await store.load(resourceId: "resource-a")
        let state = try await store.syncState()
        XCTAssertEqual(restored?.position.presentation.displayPercent, 99)
        XCTAssertNil(state.pending)
        await database.close()
    }

    func testOlderAcknowledgementCannotClearNewerPendingMutation() async throws {
        let namespace = makeNamespace(authorizationVersion: 5)
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(namespace: namespace, resourceID: "resource-a"),
            databaseURL: temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        )
        let port = BlockingReaderPositionPort()
        let runtime = ErmaoShared.PublicKt.createReaderPositionSyncRuntime(
            stateStore: database,
            target: makeTarget(namespace: namespace, resourceID: "resource-a"),
            server: port
        )
        try await runtime.store.save(position: makePosition(resourceID: "resource-a", capturedAt: 100, percent: 10))
        await port.waitUntilFirstUploadStarts()
        try await runtime.store.save(position: makePosition(resourceID: "resource-a", capturedAt: 200, percent: 20))
        try await runtime.store.save(position: makePosition(resourceID: "resource-a", capturedAt: 300, percent: 99))
        port.releaseFirstUpload()
        try await runtime.store.awaitPendingUpload()

        XCTAssertEqual(port.uploadedTimestamps, [100, 300])
        let state = try await runtime.store.syncState()
        let restored = try await runtime.store.load(resourceId: "resource-a")
        XCTAssertNil(state.pending)
        XCTAssertEqual(restored?.position.presentation.displayPercent, 99)
        runtime.close()
        await database.close()
    }

    func testAcknowledgementTracksTheServerCurrentSnapshotRevision() async throws {
        let database = try IosReaderLocalDatabase(
            identity: makeIdentity(authorizationVersion: 5, resourceID: "resource-a"),
            databaseURL: temporaryRoot.appendingPathComponent("ReaderV5.sqlite3")
        )
        let position = try makePosition(resourceID: "resource-a", capturedAt: 400, percent: 99)
        let mutationID = "f4743f84-16dc-4202-ab50-729e4d036d16"
        let mutation = ErmaoShared.ReaderProgressMutationV5(
            resourceId: position.resourceId,
            clientId: position.clientId,
            mutationId: mutationID,
            capturedAtEpochMillis: position.capturedAtEpochMillis,
            position: position.position
        )
        try await database.commitPositionAndPending(position: position, pending: mutation)
        let currentSnapshot = ErmaoShared.ReaderProgressSnapshotV5(
            resourceId: position.resourceId,
            clientId: "android-other-installation",
            revision: 9,
            mutationId: "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
            capturedAtEpochMillis: 300,
            receivedAtEpochMillis: 500,
            position: position.position
        )
        try await database.acknowledgePosition(
            mutationId: mutationID,
            response: ErmaoShared.ReaderPositionWriteResponse(
                acceptedMutationId: mutationID,
                acceptedRevision: 4,
                currentSnapshot: currentSnapshot
            )
        )

        let state = try await database.loadPositionSyncState()
        XCTAssertEqual(state.confirmedRevision, 9)
        XCTAssertNil(state.pending)
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
        bookID: String = "book-a",
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
        bookID: String = "book-a",
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

    private func makeTarget(
        namespace: ErmaoShared.ReaderSyncNamespace,
        resourceID: String
    ) -> ErmaoShared.ReaderProgressSyncTarget {
        ErmaoShared.ReaderProgressSyncTarget(
            namespace: namespace,
            bookId: "book-a",
            resourceId: resourceID,
            sourceFormat: .epub
        )
    }

    private func makePosition(
        resourceID: String,
        capturedAt: Int64,
        percent: Double
    ) throws -> ErmaoShared.ReaderPositionLocalState {
        let locatorJSON = #"{"href":"OEBPS/Text/backcover.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":".cover","totalProgression":0.25,"vendor":{"nullable":null}},"text":{"highlight":""}}"#
        let presentation = ErmaoShared.ReaderPositionPresentation(
            displayPercent: percent,
            totalProgression: percent / 100,
            currentHref: "OEBPS/Text/backcover.xhtml",
            chapter: ErmaoShared.ReaderChapterPresentation(
                href: "OEBPS/Text/backcover.xhtml",
                title: "封底",
                index: KotlinInt(int: 19)
            ),
            page: nil,
            playback: nil
        )
        return ErmaoShared.ReaderPositionLocalState(
            resourceId: resourceID,
            clientId: "ios-installation-c",
            capturedAtEpochMillis: capturedAt,
            position: ErmaoShared.ReaderPositionReport(
                locator: try ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: locatorJSON),
                presentation: presentation
            )
        )
    }
}

private enum TestUploadFailure: Error {
    case expected
}

private final class RecordingReaderPositionPort: ErmaoShared.ReaderPositionServerPort, @unchecked Sendable {
    private let lock = NSLock()
    private let failure: Error?
    private var uploads: [ErmaoShared.ReaderPositionUpload] = []

    init(failure: Error? = nil) { self.failure = failure }

    var uploadCount: Int { withLock { uploads.count } }

    func push(upload: ErmaoShared.ReaderPositionUpload) async throws -> ErmaoShared.ReaderPositionPushResult {
        withLock { uploads.append(upload) }
        if let failure { throw failure }
        return accepted(upload: upload, revision: Int64(uploadCount))
    }

    func load(
        target: ErmaoShared.ReaderProgressSyncTarget,
        etag: String?
    ) async throws -> ErmaoShared.ReaderPositionQueryResult {
        ErmaoShared.ReaderPositionQueryResultCurrent(snapshot: nil, etag: etag)
    }

    private func withLock<T>(_ operation: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return operation()
    }
}

private final class BlockingReaderPositionPort: ErmaoShared.ReaderPositionServerPort, @unchecked Sendable {
    private let lock = NSLock()
    private var uploads: [ErmaoShared.ReaderPositionUpload] = []
    private var firstContinuation: CheckedContinuation<Void, Never>?

    var uploadedTimestamps: [Int64] { withLock { uploads.map(\.mutation.capturedAtEpochMillis) } }

    func push(upload: ErmaoShared.ReaderPositionUpload) async throws -> ErmaoShared.ReaderPositionPushResult {
        let shouldBlock = withLock {
            uploads.append(upload)
            return uploads.count == 1
        }
        if shouldBlock {
            await withCheckedContinuation { continuation in
                withLock { firstContinuation = continuation }
            }
        }
        return accepted(upload: upload, revision: Int64(withLock { uploads.count }))
    }

    func load(
        target: ErmaoShared.ReaderProgressSyncTarget,
        etag: String?
    ) async throws -> ErmaoShared.ReaderPositionQueryResult {
        ErmaoShared.ReaderPositionQueryResultCurrent(snapshot: nil, etag: etag)
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

private final class ReaderPersistenceTestFileManager: FileManager {
    private let cachesURL: URL

    init(cachesURL: URL) {
        self.cachesURL = cachesURL
        super.init()
    }

    override func url(
        for directory: SearchPathDirectory,
        in domain: SearchPathDomainMask,
        appropriateFor url: URL?,
        create shouldCreate: Bool
    ) throws -> URL {
        if directory == .cachesDirectory { return cachesURL }
        return try super.url(for: directory, in: domain, appropriateFor: url, create: shouldCreate)
    }
}

private func accepted(
    upload: ErmaoShared.ReaderPositionUpload,
    revision: Int64
) -> ErmaoShared.ReaderPositionPushResult {
    let snapshot = ErmaoShared.ReaderProgressSnapshotV5(
        resourceId: upload.target.resourceId,
        clientId: upload.mutation.clientId,
        revision: revision,
        mutationId: upload.mutation.mutationId,
        capturedAtEpochMillis: upload.mutation.capturedAtEpochMillis,
        receivedAtEpochMillis: upload.mutation.capturedAtEpochMillis,
        position: upload.mutation.position
    )
    return ErmaoShared.ReaderPositionPushResultAccepted(
        response: ErmaoShared.ReaderPositionWriteResponse(
            acceptedMutationId: upload.mutation.mutationId,
            acceptedRevision: revision,
            currentSnapshot: snapshot
        )
    )
}

@MainActor
private final class PreferenceFailureState {
    var shouldFail = false
}
