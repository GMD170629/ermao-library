import UIKit
import SwiftUI
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import XCTest
@preconcurrency import WebKit
@testable import ErmaoLibrary

final class ReaderSecurityTests: XCTestCase {
    func testEpubArchiveRoleResolverUsesReadiumAccessContextForUnknownMime() {
        let roles = IosEpubResourceRoleResolver()
        roles.observeParserAccess(path: "OPS/package.bin")
        roles.markControlDocument(path: "OPS/package.bin")
        roles.markReadingOrder(paths: ["OPS/chapter.bin"])

        XCTAssertEqual(roles.role(for: "OPS/package.bin"), .controlDocument)
        XCTAssertEqual(roles.role(for: "OPS/chapter.bin"), .readingOrder)
        XCTAssertEqual(roles.role(for: "OPS/image.bin"), .optionalResource)
    }

    func testReaderSafetyFailureSinkKeepsRequiredFailuresAndIsolatesOptionalResources() throws {
        let optional = ErmaoShared.PublicKt.readerSafetyOptionalResourceFailure()
        let optionalSink = IosReaderSafetyFailureSink()
        optionalSink.record(
            IosPublicationSecurityError.rejected(
                ruleId: optional.ruleId,
                errorCode: optional.errorCode
            ),
            resourceRole: .optionalResource
        )
        XCTAssertNoThrow(try optionalSink.throwIfPresent())

        let required = ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure()
        let requiredSink = IosReaderSafetyFailureSink()
        requiredSink.record(
            IosPublicationSecurityError.rejected(
                ruleId: required.ruleId,
                errorCode: required.errorCode
            ),
            resourceRole: .readingOrder
        )
        XCTAssertThrowsError(try requiredSink.throwIfPresent()) { error in
            guard case let IosPublicationSecurityError.rejected(ruleId, errorCode) = error else {
                return XCTFail("Unexpected safety sink error: \(error)")
            }
            XCTAssertEqual(ruleId, required.ruleId)
            XCTAssertEqual(errorCode, required.errorCode)
        }
    }

    @MainActor
    func testProtectedContainerAssetReachesPublicationOpenerBeforeFirstReadingOrderRead() async throws {
        let fixture = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "reader-v5-physical", withExtension: "epub")
                ?? Bundle(for: Self.self).url(forResource: "reader-v2", withExtension: "epub")
        )
        let values = try fixture.resourceValues(forKeys: [.fileSizeKey])
        let managed = IosManagedPublication(
            resourceID: "reader-safety-first-read",
            displayTitle: "Reader safety first read",
            fileURL: fixture,
            byteCount: Int64(values.fileSize ?? 0),
            bookID: nil,
            assetID: nil,
            namespace: nil,
            sourceFormat: .epub
        )
        let opened = try await IosReadiumRuntime().open(managed)
        let link = try XCTUnwrap(opened.publication.readingOrder.first)
        let resource = try XCTUnwrap(opened.publication.get(link))
        let result = await resource.read()
        let bytes = try result.get()
        await opened.close()

        XCTAssertTrue(
            String(decoding: bytes, as: UTF8.self).contains("Content-Security-Policy"),
            "The protected ContainerAsset must sanitize the first reading-order resource before the SDK read returns"
        )
    }

    func testLegacyMobiEnvelopeBindsNamespacesWithoutChangingLocatorBody() async throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "01-basic-mobi6", withExtension: "mobi"))
        let book = try IosMobiBook.open(fileURL: url)
        let index = try await book.readingOrderResourceIndex(at: 0)
        let source = try await book.readResource(at: index, offset: 0, length: 4096)
        await book.close()
        let decorated = try IosPublicationSecurityAdapter().decorate(data: source, mediaType: "application/xhtml+xml")
        let originalMarkup = String(decoding: source, as: UTF8.self)
        let markup = String(decoding: decorated, as: UTF8.self)
        XCTAssertTrue(markup.contains("xmlns=\"http://www.w3.org/1999/xhtml\""))
        XCTAssertTrue(markup.contains("xmlns:mbp=\"urn:shuku:mobipocket\""))
        XCTAssertEqual(markup.components(separatedBy: "<body>").last, originalMarkup.components(separatedBy: "<body>").last)
        XCTAssertFalse(try IosPublicationSecurityPolicy.locatorBodyProjection(data: decorated).isEmpty)
    }

    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    @MainActor
    func testPhysicalEpubLastPageUploadsTheActualReadiumLocationChangeLocator() async throws {
        let fixture = try XCTUnwrap(
            Bundle(for: Self.self).url(
                forResource: "reader-v5-physical",
                withExtension: "epub"
            )
        )
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("reader-v5-physical-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let managedStore = try IosManagedPublicationStore(
            root: root.appendingPathComponent("Publications", isDirectory: true)
        )
        _ = try await managedStore.importPublication(
            from: fixture,
            resourceID: "reader-v5-physical",
            displayTitle: "Reader v5 physical EPUB",
            sourceFormat: .epub,
            bookID: "reader-v5-book",
            assetID: "reader-v5-asset",
            namespace: "reader-v5-test",
            parserVersion: "epub-package:1",
            normalizationVersion: "shuku-epub-locator-dom-v2"
        )
        let suite = "reader-v5-physical-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let deviceIdentity = IosReaderDeviceIdentity(defaults: defaults)
        let namespace = ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: "reader-v5-server",
            userId: "reader-v5-user",
            authorizationVersion: 1
        )
        let identity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: deviceIdentity.stableDeviceId(),
            bookId: "reader-v5-book",
            resourceId: "reader-v5-physical"
        )
        let database = try IosReaderLocalDatabase(
            identity: identity,
            databaseURL: root.appendingPathComponent("ReaderV5.sqlite3")
        )
        let port = PhysicalReaderV5PositionPort()
        let target = ErmaoShared.ReaderProgressSyncTarget(
            namespace: namespace,
            bookId: "reader-v5-book",
            resourceId: "reader-v5-physical",
            sourceFormat: .epub
        )
        let runtime = ErmaoShared.PublicKt.createReaderPositionSyncRuntime(
            stateStore: database,
            target: target,
            server: port
        )
        let session = IosReflowableReaderSession(
            resourceID: "reader-v5-physical",
            displayTitle: "Reader v5 physical EPUB",
            sourceFormat: .epub,
            managedStore: managedStore,
            progressStore: runtime.store,
            namespaceKey: "reader-v5-test",
            bookID: "reader-v5-book",
            deviceIdentity: deviceIdentity
        )
        addTeardownBlock {
            try await session.close()
            runtime.close()
            await database.close()
            try? FileManager.default.removeItem(at: root)
        }

        let scene = try XCTUnwrap(
            UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        )
        let originalWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = UIHostingController(
            rootView: IosReflowableReaderView(session: session)
        )
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            originalWindow?.makeKey()
        }
        await session.open()
        for _ in 0 ..< 100 where session.navigator?.viewport == nil {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertNotNil(session.navigator?.viewport)
        let firstReadiumLocator = try XCTUnwrap(session.navigator?.currentLocation)
        let movedToLastPage = await session.seekControlProgress(1)
        XCTAssertTrue(movedToLastPage)
        try await Task.sleep(for: .milliseconds(750))
        await session.flushProgress()
        XCTAssertNil(session.presentationError)
        let readiumLocator = try XCTUnwrap(session.navigator?.currentLocation)
        let local = try await database.loadPosition(resourceId: "reader-v5-physical")
        XCTAssertNotNil(local)
        try await runtime.store.retryPendingUpload()
        try await runtime.store.awaitPendingUpload()
        let durableState = try await runtime.store.syncState()
        XCTAssertNil(durableState.terminalFailureCode)
        XCTAssertNil(durableState.pending)
        let uploaded = try XCTUnwrap(port.lastUploadedPosition)

        XCTAssertEqual(
            try canonicalJSONObjectData(uploaded.locator.canonicalJson),
            try canonicalJSONObjectData(readiumLocator.jsonString()),
            "The upload must contain the same Locator emitted by Readium at the last page"
        )

        // SYNC-06: reuse the real publication and confirmed local report.
        // No pending mutation may mask the confirmed-local fallback on reopen.
        let saved = try XCTUnwrap(local)
        XCTAssertNotNil(firstReadiumLocator.locations.position)
        XCTAssertNotNil(readiumLocator.locations.position)
        XCTAssertNotEqual(firstReadiumLocator.locations.position, readiumLocator.locations.position)
        try await session.close()
        runtime.close()
        let failures: [ErmaoShared.ReaderBootstrapResultFailure?] = [
            ErmaoShared.ReaderBootstrapResultFailure(failureCode: "NETWORK_UNAVAILABLE", recoverable: true),
            nil, // Successful bootstrap with no remote progress.
            ErmaoShared.ReaderBootstrapResultFailure(failureCode: "AUTH_REQUIRED", recoverable: false),
        ]
        for failure in failures {
            let reopenedRuntime = ErmaoShared.PublicKt.createReaderPositionSyncRuntime(
                stateStore: database, target: target, server: port
            )
            try await reopenedRuntime.store.save(position: saved)
            try await reopenedRuntime.store.awaitPendingUpload()
            let beforeReopen = try await reopenedRuntime.store.syncState()
            XCTAssertNil(beforeReopen.pending)
            XCTAssertGreaterThan(beforeReopen.confirmedRevision, 0)
            let coordination = IosReaderProgressSessionCoordination(
                runtime: reopenedRuntime, database: database, target: target, server: port,
                clientID: identity.clientId, bootstrapSnapshot: nil, bootstrapFailure: failure
            )
            let reopened = IosReflowableReaderSession(
                resourceID: "reader-v5-physical",
                displayTitle: "Reader v5 physical EPUB",
                sourceFormat: .epub,
                managedStore: managedStore,
                progressStore: reopenedRuntime.store,
                progressCoordination: coordination,
                namespaceKey: "reader-v5-test",
                bookID: "reader-v5-book",
                deviceIdentity: deviceIdentity
            )
            addTeardownBlock { try await reopened.close() }
            window.rootViewController = UIHostingController(
                rootView: IosReflowableReaderView(session: reopened)
            )
            await reopened.open()
            for _ in 0 ..< 100 where reopened.navigator?.viewport == nil {
                try await Task.sleep(for: .milliseconds(100))
            }
            XCTAssertNotNil(reopened.navigator?.viewport)
            XCTAssertEqual(reopened.phase, .reading)
            XCTAssertNil(reopened.presentationError)
            let actual = try XCTUnwrap(reopened.navigator?.currentLocation)
            let expected = failure?.recoverable == true ? readiumLocator : firstReadiumLocator
            XCTAssertEqual(actual.href, expected.href)
            XCTAssertEqual(actual.locations.position, expected.locations.position)
            try await reopened.close()
        }
    }

    @MainActor
    func testNativeTextControlsRenderBundledFontsAndThemesOnPhysicalDevice() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("reader-controls-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let file = root.appendingPathComponent("original.txt")
        // Three long original chapters exercise current, preloaded and revisited
        // resources as well as unequal blocks that repaginate after font changes.
        let paragraphs = (1 ... 240).map { index in
            "Paragraph \(index). Native text controls preserve the publication. " +
                String(repeating: "中文字体与排版。", count: 1 + index % 4)
        }.joined(separator: "\n\n")
        let content = (44 ... 46).map { "第\($0)章 原始章节\n\n" + paragraphs }.joined(separator: "\n\n")
        let original = Data(content.utf8)
        try original.write(to: file)
        let publicationRoot = root.appendingPathComponent("Publications", isDirectory: true)
        let managedStore = try IosManagedPublicationStore(root: publicationRoot)
        let managed = try await managedStore.importPublication(
            from: file, resourceID: "controls", displayTitle: "Controls", sourceFormat: .txt,
            bookID: "book", assetID: "asset", namespace: "test",
            parserVersion: "ermao-chapters:1", normalizationVersion: "shuku-txt-publication-v3"
        )
        let publicationFiles = try FileManager.default.contentsOfDirectory(atPath: publicationRoot.path).sorted()
        let suite = "reader-controls-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let preferencesStore = IosReaderPreferencesStore(serverIdentity: "controls-server", userID: "controls-user", defaults: defaults)
        let deviceIdentity = IosReaderDeviceIdentity(defaults: defaults)
        let identity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: ErmaoShared.PublicKt.createReaderSyncNamespace(
                serverIdentity: "controls-server", userId: "controls-user", authorizationVersion: 1
            ),
            clientId: deviceIdentity.stableDeviceId(), bookId: "book", resourceId: "controls"
        )
        let database = try IosReaderLocalDatabase(identity: identity, databaseURL: root.appendingPathComponent("Reader.sqlite3"))
        let progressStore = IosLocalOnlyReaderProgressStore(database: database)
        var progressUpdateCount = 0
        var preferences = IosReaderPreferences()
        preferences.pageTurnAnimation = "off"
        func makeSession(preferences: IosReaderPreferences) -> IosReflowableReaderSession {
            IosReflowableReaderSession(
                resourceID: "controls", displayTitle: "Controls", sourceFormat: .txt,
                preferences: preferences, managedStore: managedStore, progressStore: progressStore,
                preferencesStore: preferencesStore, namespaceKey: "test", bookID: "book",
                publishProgressUpdate: { _ in progressUpdateCount += 1 },
                deviceIdentity: deviceIdentity
            )
        }
        var session = makeSession(preferences: preferences)
        addTeardownBlock { [session] in
            try await session.close()
            await database.close()
        }
        await session.open()
        let unpresentedNavigator = try XCTUnwrap(session.navigator)
        XCTAssertNil(unpresentedNavigator.viewIfLoaded?.window)
        preferences.fontSize = 20
        let appliedBeforePresentation = await session.applyControlPreferences(preferences)
        XCTAssertTrue(appliedBeforePresentation, "Applying preferences must not require a first-visible locator or a mounted view")
        XCTAssertTrue(session.navigator === unpresentedNavigator)
        XCTAssertEqual(session.preferences, preferences)
        XCTAssertEqual(preferencesStore.load(), preferences)
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let originalWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        let host = UIHostingController(rootView: IosReflowableReaderView(session: session))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            originalWindow?.makeKey()
            UIApplication.shared.isIdleTimerDisabled = false
        }
        for _ in 0 ..< 50 where UIApplication.shared.applicationState != .active {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(UIApplication.shared.applicationState, .active, "Physical rendering acceptance requires the app in the foreground")
        func expectRendered(_ condition: String, _ message: String) async throws {
            for _ in 0 ..< 100 {
                if let navigator = session.navigator,
                   case let .success(value) = await navigator.evaluateJavaScript(condition),
                   value as? Bool == true { return }
                try await Task.sleep(for: .milliseconds(100))
            }
            let navigator = try XCTUnwrap(session.navigator, "The real session must publish its navigator")
            let diagnostic = await navigator.evaluateJavaScript("JSON.stringify({height:document.documentElement.scrollHeight,scrollY:window.scrollY,href:location.pathname,viewport:innerHeight,width:document.documentElement.scrollWidth,font:getComputedStyle(document.querySelector('p')).fontFamily,size:getComputedStyle(document.querySelector('p')).fontSize,line:getComputedStyle(document.querySelector('p')).lineHeight,color:getComputedStyle(document.querySelector('p')).color,rootColumn:getComputedStyle(document.documentElement).columnWidth,fonts:[...document.fonts].map(f=>({family:f.family,status:f.status}))})")
            XCTFail("\(message): \(diagnostic)")
        }

        try await expectRendered("Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - 20) < 0.7 && [...document.fonts].some(f=>f.family.includes('Shuku Sans') && f.status==='loaded')", "Preferences accepted before presentation must render through the SwiftUI session host")
        XCTAssertEqual(session.phase, .reading)
        // CSS is visible before Readium finishes the initial navigation. Wait for
        // its public viewport in the test before starting the next user edit.
        for _ in 0 ..< 100 where session.navigator?.viewport == nil {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertNotNil(session.navigator?.viewport)
        let initialProgress = try await progressStore.load(resourceId: "controls")
        XCTAssertNil(initialProgress, "Opening must not manufacture reading progress")
        XCTAssertEqual(progressUpdateCount, 0)
        preferences.fontSize = 18
        let restoredDefaultSize = await session.applyControlPreferences(preferences)
        XCTAssertTrue(restoredDefaultSize)
        XCTAssertTrue(session.navigator === unpresentedNavigator)
        try await expectRendered("Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - 18) < 0.7", "The initial 18 px size must render before the mid-chapter regression")
        let sought = await session.seekControlProgress(0.45)
        XCTAssertTrue(sought, "Move into the middle of the long chapter before testing reflow")
        await session.goNext()
        try await Task.sleep(for: .milliseconds(750))
        await session.flushProgress()
        let savedProgress = try await progressStore.load(resourceId: "controls")
        let baseline = try XCTUnwrap(savedProgress, "Normal page navigation must persist an exact location")
        let progressCodec = ErmaoShared.PublicKt.createReaderPositionJson()
        let baselinePayload = progressCodec.encode(position: baseline)
        let baselineUpdateCount = progressUpdateCount
        XCTAssertGreaterThan(session.progress, 0.4)
        XCTAssertLessThan(session.progress, 0.65)

        // Keep the native sheet open, as it is when a user changes typography.
        // Readium owns the reflow while the existing native host stays mounted.
        session.controlsVisible = true
        session.activeControlPanel = .appearance
        for _ in 0 ..< 50 where host.presentedViewController == nil {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertNotNil(host.presentedViewController)

        func applyNativePreferences() async throws {
            let previous = try XCTUnwrap(session.navigator)
            let applied = await session.applyControlPreferences(preferences)
            XCTAssertTrue(applied, "Applying native preferences through the real session must succeed: \(preferences.fontSize) px")
            XCTAssertTrue(session.navigator === previous, "Readium must apply preferences to the existing navigator")
            XCTAssertEqual(session.preferences, preferences)
            XCTAssertEqual(preferencesStore.load(), preferences, "The accepted native preferences must be persisted")
            await session.flushProgress()
            let currentProgress = try await progressStore.load(resourceId: "controls")
            XCTAssertEqual(progressCodec.encode(position: try XCTUnwrap(currentProgress)), baselinePayload,
                           "Preference reflow must not save a synthetic position or timestamp")
            XCTAssertEqual(progressUpdateCount, baselineUpdateCount, "Preference reflow must not publish reading activity")
            XCTAssertNil(session.presentationError)
        }

        for size in [30, 14] {
            preferences.fontSize = size
            try await applyNativePreferences()
            try await expectRendered("Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - \(size)) < 0.7", "Changing the font size must update the actual body CSS: \(size) px")
        }
        preferences.fontSize = 24
        preferences.lineHeight = 2.2
        try await applyNativePreferences()
        try await expectRendered("Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).lineHeight) / parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - 2.2) < 0.05", "Line height must change actual paragraph layout")
        for (family, nativeFamily) in [(IosReaderFontFamily.pingfang, "Shuku Sans"), (.kaiti, "Shuku Kaiti"), (.songti, "Shuku Songti")] {
            preferences.fontFamily = family
            try await applyNativePreferences()
            try await expectRendered("getComputedStyle(document.querySelector('p')).fontFamily.includes('\(nativeFamily)') && [...document.fonts].some(f=>f.family.includes('\(nativeFamily)') && f.status==='loaded')", "Bundled font must actually load: \(nativeFamily)")
        }
        for theme in IosReaderTheme.allCases {
            let rgb = cssRGB(theme.colors.foreground)
            preferences.theme = theme
            try await applyNativePreferences()
            try await expectRendered("getComputedStyle(document.querySelector('p')).color === '\(rgb)'", "Theme must update the paragraph immediately: \(theme)")
        }
        preferences.themeMode = .system
        try await applyNativePreferences()
        let systemThemeNavigator = try XCTUnwrap(session.navigator)
        for (appearance, theme) in [(UIUserInterfaceStyle.dark, IosReaderTheme.night), (.light, .day)] {
            session.refreshSystemAppearance(appearance)
            let rgb = cssRGB(theme.colors.foreground)
            try await expectRendered("getComputedStyle(document.querySelector('p')).color === '\(rgb)'", "System appearance must update the actual body color: \(appearance)")
            XCTAssertTrue(session.navigator === systemThemeNavigator)
            try await applyNativePreferences()
        }

        preferences = IosReaderPreferences()
        try await applyNativePreferences()
        XCTAssertEqual(session.preferences, IosReaderPreferences())
        let defaultTextColor = cssRGB(IosReaderTheme.warm.colors.foreground)
        let defaultTypography = """
        (() => {
            const style = getComputedStyle(document.querySelector('p'));
            return style.fontFamily.includes('Shuku Sans') &&
                Math.abs(parseFloat(style.fontSize) - 18) < 0.7 &&
                Math.abs(parseFloat(style.lineHeight) / parseFloat(style.fontSize) - 1.9) < 0.05 &&
                style.color === '\(defaultTextColor)';
        })()
        """
        try await expectRendered(defaultTypography, "Reset must restore the actual default font, size, line height and Warm theme")
        var nonFinitePreferences = preferences
        nonFinitePreferences.lineHeight = .nan
        XCTAssertTrue(session.canApplyControlPreferences(nonFinitePreferences), "The enabled line-height request must reach the persistence boundary")
        let navigatorBeforeStorageFailure = try XCTUnwrap(session.navigator)
        let appliedNonFinitePreferences = await session.applyControlPreferences(nonFinitePreferences)
        XCTAssertFalse(appliedNonFinitePreferences, "Non-finite preferences must be rejected when JSON persistence fails")
        XCTAssertEqual(session.preferences, preferences)
        XCTAssertEqual(preferencesStore.load(), preferences)
        XCTAssertTrue(session.navigator === navigatorBeforeStorageFailure)
        try await expectRendered(defaultTypography, "Rejected preferences must not change the rendered typography")

        preferences.readingMode = .continuousScroll
        try await applyNativePreferences()
        var navigator = try XCTUnwrap(session.navigator)
        XCTAssertEqual(UIApplication.shared.applicationState, .active, "Readium defers pagination reload while the app is inactive")
        XCTAssertTrue(navigator.settings.scroll)
        try await expectRendered("document.documentElement.scrollHeight > innerHeight && getComputedStyle(document.documentElement).columnWidth === 'auto'", "Continuous scrolling must change actual document layout")
        XCTAssertFalse(navigator.editor(of: preferences.readium(for: .light)).columnCount.isEffective)
        preferences.readingMode = .paged
        try await applyNativePreferences()
        preferences.spreadMode = .double
        try await applyNativePreferences()
        navigator = try XCTUnwrap(session.navigator)
        XCTAssertEqual(navigator.settings.columnCount, ColumnCount.two)
        try await expectRendered("document.documentElement.scrollWidth > innerWidth && getComputedStyle(document.documentElement).columnWidth !== 'auto'", "Paged layout must restore horizontal columns")

        let editor = IosReaderPreferenceEditor(preferences: preferences) { updated in
            await session.applyControlPreferences(updated)
        }
        editor.change { $0.fontSize = 20 }
        editor.change { $0.fontSize = 28 }
        editor.change { $0.lineHeight = 2.0 }
        await editor.flush()
        XCTAssertFalse(editor.applyFailed, "Rapid changes must commit their latest draft through the session")
        XCTAssertEqual(session.preferences.fontSize, 28)
        XCTAssertEqual(session.preferences.lineHeight, 2.0)
        XCTAssertEqual(preferencesStore.load(), session.preferences)
        try await expectRendered("Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - 28) < 0.7", "The last coalesced font size must render")
        let committed = session.preferences
        let committedNavigator = try XCTUnwrap(session.navigator)
        editor.change { $0.volumeKeyPageTurn = true }
        await editor.flush()
        XCTAssertTrue(editor.applyFailed, "Unsupported iOS volume-key controls must fail without replacing valid settings")
        XCTAssertEqual(editor.draft, committed)
        XCTAssertEqual(session.preferences, committed)
        XCTAssertEqual(preferencesStore.load(), committed)
        XCTAssertTrue(session.navigator === committedNavigator)

        session.activeControlPanel = nil
        await session.enterBackground()
        try await session.close()
        let finalProgress = try await progressStore.load(resourceId: "controls")
        XCTAssertEqual(progressCodec.encode(position: try XCTUnwrap(finalProgress)), baselinePayload,
                       "Background and close must not persist a preference-only reflow")
        XCTAssertEqual(progressUpdateCount, baselineUpdateCount)

        // A normal close/reopen restores local settings and the old exact anchor.
        // Subsequent setting changes must stay on this new navigator while its
        // adjacent resources are loaded with the current Readium CSS.
        session = makeSession(preferences: preferencesStore.load())
        addTeardownBlock { [session] in try await session.close() }
        host.rootView = IosReflowableReaderView(session: session)
        await session.open()
        let reopenedNavigator = try XCTUnwrap(session.navigator)
        XCTAssertEqual(session.tableOfContents.count, 3)
        try await expectRendered("Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - 28) < 0.7", "Normal reopen must apply the saved font size")

        func webViews(in view: UIView) -> [WKWebView] {
            (view as? WKWebView).map { [$0] } ?? view.subviews.flatMap { webViews(in: $0) }
        }
        func expectLoadedChapters(scrolled: Bool, size: Int) async throws {
            let script = "document.body.textContent.includes('Paragraph 240.') && Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - \(size)) < 0.7 && (getComputedStyle(document.documentElement).columnWidth === 'auto') === \(scrolled)"
            for _ in 0 ..< 100 {
                let chapters = webViews(in: reopenedNavigator.view).filter { $0.url?.pathExtension == "xhtml" }
                var correct = chapters.count >= 2
                for chapter in chapters {
                    let rendered = try? await chapter.evaluateJavaScript(script)
                    correct = correct && rendered as? Bool == true
                    correct = correct && chapter.scrollView.isPagingEnabled == !scrolled
                }
                if correct { return }
                try await Task.sleep(for: .milliseconds(100))
            }
            XCTFail("Current and preloaded chapters must all have complete text, \(size) px and scrolled=\(scrolled)")
        }
        try await expectLoadedChapters(scrolled: false, size: 28)
        for (mode, size) in [(IosReaderReadingMode.continuousScroll, 22), (.paged, 16), (.continuousScroll, 24)] {
            var updated = session.preferences
            updated.readingMode = mode
            updated.fontSize = size
            let applied = await session.applyControlPreferences(updated)
            XCTAssertTrue(applied)
            XCTAssertTrue(session.navigator === reopenedNavigator, "Settings must not rebuild the navigator")
            try await expectLoadedChapters(scrolled: mode == .continuousScroll, size: size)
            for index in [2, 0, 1] {
                let navigated = await session.goToTOCEntry(session.tableOfContents[index])
                XCTAssertTrue(navigated, "Normal TOC navigation must reach original chapter \(index + 44)")
                try await expectLoadedChapters(scrolled: mode == .continuousScroll, size: size)
                try await expectRendered("document.body.textContent.includes('Paragraph 240.') && Math.abs(parseFloat(getComputedStyle(document.querySelector('p')).fontSize) - \(size)) < 0.7", "New and revisited chapters must retain full content and typography")
            }
        }
        func expectChapter(_ index: Int, atEnd: Bool = false) async throws {
            // Input callbacks enqueue work asynchronously; wait for the public
            // location notification as well as the document's visible content.
            for _ in 0 ..< 100 where session.navigator?.currentLocation?.href.string != session.tableOfContents[index].href {
                try await Task.sleep(for: .milliseconds(100))
            }
            let edge = atEnd
                ? "Math.abs((document.scrollingElement.scrollHeight - innerHeight) - document.scrollingElement.scrollTop) <= 1"
                : "Math.abs(document.scrollingElement.scrollTop) <= 1"
            try await expectRendered(
                "document.body.textContent.includes('第\(index + 44)章') && \(edge)",
                "Scroll navigation must enter chapter \(index + 44) at its \(atEnd ? "end" : "top")"
            )
            XCTAssertEqual(session.navigator?.currentLocation?.href.string, session.tableOfContents[index].href)
            XCTAssertTrue(session.navigator === reopenedNavigator)
        }

        let openedFirstChapter = await session.goToTOCEntry(session.tableOfContents[0])
        XCTAssertTrue(openedFirstChapter)
        try await expectChapter(0)
        await session.goNext()
        try await expectRendered(
            "document.scrollingElement.scrollTop > innerHeight * 0.8 && document.scrollingElement.scrollTop < innerHeight * 0.96",
            "Scroll Next must move approximately 88 percent of the current viewport"
        )
        XCTAssertEqual(session.navigator?.currentLocation?.href.string, session.tableOfContents[0].href)
        _ = try await reopenedNavigator.evaluateJavaScript(
            "document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight - innerHeight - 20; true"
        ).get()
        await session.goNext()
        try await expectChapter(0, atEnd: true)
        await session.goNext()
        try await expectChapter(1)
        await session.goPrevious()
        try await expectChapter(0, atEnd: true)
        await session.goPrevious()
        try await expectRendered(
            "document.scrollingElement.scrollTop < document.scrollingElement.scrollHeight - innerHeight - 1",
            "Scroll Previous must move within the chapter before crossing it"
        )

        let openedMiddleChapter = await session.goToTOCEntry(session.tableOfContents[1])
        XCTAssertTrue(openedMiddleChapter)
        try await expectChapter(1)
        await session.handleKeyEvent(KeyEvent(phase: .down, key: .pageUp))
        try await expectChapter(0, atEnd: true)
        await session.handleKeyEvent(KeyEvent(phase: .down, key: .pageDown))
        try await expectChapter(1)
        await session.handleKeyEvent(KeyEvent(phase: .down, key: .pageDown))
        try await expectRendered("document.scrollingElement.scrollTop > 1", "PageDown must advance within the current chapter")
        _ = try await reopenedNavigator.evaluateJavaScript(
            "document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight - innerHeight; true"
        ).get()
        await session.handleKeyEvent(KeyEvent(phase: .down, key: .arrowRight))
        try await expectChapter(2)
        try await Task.sleep(for: .milliseconds(500))
        XCTAssertNil(session.activeControlPanel)
        XCTAssertNil(reopenedNavigator.currentSelection)
        await session.handleTap(at: CGPoint(x: 10, y: 100), width: 440)
        try await expectChapter(1, atEnd: true)
        var reversedTaps = session.preferences
        reversedTaps.tapZones = .reversed
        let reversedApplied = await session.applyControlPreferences(reversedTaps)
        XCTAssertTrue(reversedApplied)
        // Respect the existing tap debounce when issuing another physical-style tap.
        try await Task.sleep(for: .milliseconds(500))
        await session.handleTap(at: CGPoint(x: 10, y: 100), width: 440)
        try await expectChapter(2)

        let reopenedFirstChapter = await session.goToTOCEntry(session.tableOfContents[0])
        XCTAssertTrue(reopenedFirstChapter)
        try await expectChapter(0)
        await session.flushProgress()
        let chapterStartProgress = try await progressStore.load(resourceId: "controls")
        let chapterStart = try XCTUnwrap(chapterStartProgress)
        let chapterLocator = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(chapterStart.position.locator.canonicalJson.utf8))
                as? [String: Any]
        )
        XCTAssertEqual(chapterLocator["href"] as? String, session.tableOfContents[0].href)
        XCTAssertNotNil(chapterLocator["locations"],
                        "A chapter jump must persist the unmodified Readium Locator")

        var pagedPreferences = session.preferences
        pagedPreferences.readingMode = .paged
        let pagedApplied = await session.applyControlPreferences(pagedPreferences)
        XCTAssertTrue(pagedApplied)
        try await expectLoadedChapters(scrolled: false, size: 24)
        let pagedHref = reopenedNavigator.currentLocation?.href.string
        await session.goNext()
        try await expectRendered("Math.abs(window.scrollX) > 0", "Paged Next must advance one viewport within the chapter")
        XCTAssertEqual(reopenedNavigator.currentLocation?.href.string, pagedHref)
        let offsetValue = try await reopenedNavigator.evaluateJavaScript("Math.abs(window.scrollX)").get()
        let offset = try XCTUnwrap(offsetValue as? Double)
        XCTAssertGreaterThan(offset, 0)
        await session.goPrevious()
        try await expectRendered("Math.abs(window.scrollX) < \(offset)", "Paged Previous must still move back one viewport")
        XCTAssertEqual(reopenedNavigator.currentLocation?.href.string, pagedHref)
        XCTAssertTrue(session.navigator === reopenedNavigator)
        try await session.close()
        XCTAssertEqual(try Data(contentsOf: file), original)
        XCTAssertEqual(try Data(contentsOf: managed.fileURL), original)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: publicationRoot.path).sorted(), publicationFiles,
                       "Applying preferences must not create converted or unpacked publication artifacts")
        await database.close()
    }

    func testTxtDecoderPreservesTheNativeCodecOutput() throws {
        struct Contract: Decodable {
            struct DecoderResult: Decodable {
                let expectedText: String?
            }
            struct DecoderOverrides: Decodable {
                let appleFoundation: DecoderResult?

                enum CodingKeys: String, CodingKey {
                    case appleFoundation = "apple-foundation"
                }
            }
            struct Case: Decodable {
                let id: String
                let sourceHex: String
                let expectedText: String?
                let decoderOverrides: DecoderOverrides?
            }
            let schema: String
            let version: Int
            let cases: [Case]
        }
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "txt-decoding-v1", withExtension: "json"))
        let contract = try JSONDecoder().decode(Contract.self, from: Data(contentsOf: url))
        XCTAssertEqual(contract.schema, "ermao.txt-decoding")
        XCTAssertEqual(contract.version, 1)
        XCTAssertFalse(contract.cases.isEmpty)
        for example in contract.cases {
            let hex = Array(example.sourceHex)
            XCTAssertEqual(hex.count % 2, 0, example.id)
            let bytes = try stride(from: 0, to: hex.count, by: 2).map { index in
                try XCTUnwrap(UInt8(String(hex[index ..< index + 2]), radix: 16), example.id)
            }
            let expected: String?
            if let override = example.decoderOverrides?.appleFoundation {
                expected = override.expectedText
            } else {
                expected = example.expectedText
            }
            XCTAssertEqual(IosStrictTxtDecoder.decode(Data(bytes)), expected, example.id)
        }
    }

    @MainActor
    func testBlankTxtPreservesTheParserFailureAcrossTheKotlinBoundary() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).txt")
        defer { try? FileManager.default.removeItem(at: file) }
        try Data(" \n\t".utf8).write(to: file)
        let managed = IosManagedPublication(
            resourceID: "invalid-txt", displayTitle: "Blank", fileURL: file, byteCount: 3,
            bookID: "book", assetID: "asset", namespace: "test", sourceFormat: .txt
        )
        do {
            _ = try await IosReadiumRuntime().open(managed)
            XCTFail("A blank TXT publication must fail")
        } catch let failure as IosReaderFailure {
            XCTAssertEqual(failure.code, .txtEmpty)
            XCTAssertNotNil(failure.underlyingError)
        }
    }

    func testFb2RichContentMatchesServerBodiesAndPreservesOriginal() throws {
        let bundle = Bundle(for: Self.self)
        let source = try XCTUnwrap(bundle.url(forResource: "reader-contract", withExtension: "fb2"))
        let golden = try XCTUnwrap(bundle.url(forResource: "reader-contract-bodies", withExtension: "json"))
        let original = try Data(contentsOf: source)
        let expected = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: golden))
        let parsed = try IosFb2PublicationFactory.read(fileURL: source, fallbackTitle: "Fallback")

        XCTAssertEqual(parsed.document.title, "阅读 & Reading")
        XCTAssertEqual(parsed.document.language, "zh-CN")
        XCTAssertEqual(parsed.document.resources.count, expected.count)
        for resource in parsed.document.resources {
            let start = try XCTUnwrap(resource.xhtml.range(of: "<body>"))
            let end = try XCTUnwrap(resource.xhtml.range(of: "</body>"))
            XCTAssertEqual(String(resource.xhtml[start.upperBound..<end.lowerBound]), expected[resource.href])
        }
        let tableOfContents = parsed.document.tableOfContents
        XCTAssertEqual(tableOfContents.count, 2)
        let firstChapter = try XCTUnwrap(tableOfContents.first)
        XCTAssertEqual(firstChapter.title, "第一章 Chapter One")
        XCTAssertEqual(firstChapter.navigationKey, "chapter-0")
        XCTAssertEqual(firstChapter.children.count, 1)
        let nestedChapter = try XCTUnwrap(firstChapter.children.first)
        XCTAssertEqual(nestedChapter.title, "子章节")
        XCTAssertEqual(nestedChapter.navigationKey, "chapter-1")
        XCTAssertEqual(nestedChapter.href, "fb2/section-0001.xhtml#chapter-node-20")
        let notes = try XCTUnwrap(tableOfContents.dropFirst().first)
        XCTAssertEqual(notes.title, "注释 Notes")
        XCTAssertEqual(notes.navigationKey, "chapter-2")
        XCTAssertTrue(notes.children.isEmpty)
        let flattened = tableOfContents.flatMap { [$0] + $0.children }
        XCTAssertEqual(flattened.count, 3)
        XCTAssertEqual(
            flattened.map(\.navigationKey),
            ["chapter-0", "chapter-1", "chapter-2"]
        )
        XCTAssertEqual(Set(parsed.images.keys), ["fb2/images/498cc84b29cb560e15b4.png"])
        XCTAssertEqual(try Data(contentsOf: source), original)

        let upstream = try XCTUnwrap(bundle.url(forResource: "source_test_book_fb2", withExtension: "fb2"))
        XCTAssertEqual(try IosFb2PublicationFactory.read(fileURL: upstream, fallbackTitle: "Fallback").document.title,
                       "Sample FB2 book")
    }

    func testFb2UsesFoundationNamespaceAndImageDecodingSemantics() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let source = Data("<FictionBook><body><p q:href='#x'>text</p></body><binary id='image' content-type='image/png'>SGVsbG8=</binary></FictionBook>".utf8)
        try source.write(to: file)
        let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Book")
        XCTAssertEqual(parsed.images.values.first, Data("Hello".utf8))
        XCTAssertEqual(try Data(contentsOf: file), source)
    }

    func testFb2PreservesUnfamiliarImageMimeBytesWithoutAnExtension() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let source = Data("<FictionBook><body><p>text</p></body><binary id='image' content-type='image/future-format'>SGVsbG8=</binary></FictionBook>".utf8)
        try source.write(to: file)

        let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Book")

        XCTAssertEqual(parsed.images["fb2/images/6105d6cc76af400325e9"], Data("Hello".utf8))
        XCTAssertEqual(parsed.document.images.single?.mediaType, "image/future-format")
        XCTAssertEqual(try Data(contentsOf: file), source)
    }

    func testGeneratedTxtPreservesNulAndEscapesActiveMarkupWithoutXmlPrevalidation() throws {
        let xhtml = ErmaoShared.PublicKt.renderTxtXhtml(
            title: "Book", bodyText: "a\0b\0<script>alert(1)</script>"
        )
        let decorated = String(decoding: try IosPublicationSecurityPolicy.generatedChapter(xhtml), as: UTF8.self)
        XCTAssertTrue(decorated.contains("a\0b\0&lt;script&gt;"))
        XCTAssertTrue(decorated.contains("script-src 'none'"))
        XCTAssertFalse(decorated.contains("<script>"))
    }

    func testFb2ActualXmlErrorsFailClosed() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("original.fb2")
        let examples = [
            "<FictionBook><body><p>broken</body></FictionBook>",
            "<FictionBook><body><section id='x'/><section id='x'/></body></FictionBook>",
        ]
        for (index, example) in examples.enumerated() {
            let bytes = Data(example.utf8)
            try bytes.write(to: file)
            XCTAssertThrowsError(try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback"), "Invalid FB2 case \(index)")
            XCTAssertEqual(try Data(contentsOf: file), bytes)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), ["original.fb2"])
    }

    func testFb2BlocksOneInvalidEmbeddedImageWithoutRejectingPublication() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let source = Data(
            "<FictionBook><body><p>text</p></body><binary id='image' content-type='image/png'>!!!!</binary></FictionBook>".utf8
        )
        try source.write(to: file)

        let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback")

        XCTAssertTrue(parsed.images.isEmpty)
        XCTAssertTrue(parsed.document.images.isEmpty)
        XCTAssertEqual(try Data(contentsOf: file), source)
    }

    func testFb2RejectsOversizedSourceBeforeWholeFileAllocationWithGeneratedFailure() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        XCTAssertTrue(FileManager.default.createFile(atPath: file.path, contents: nil))
        let sourceByteCount = UInt64(ErmaoShared.PublicKt.readerSafetyFb2TextMaxBytes()) + 1
        let handle = try FileHandle(forWritingTo: file)
        try handle.truncate(atOffset: sourceByteCount)
        try handle.close()
        let generated = ErmaoShared.PublicKt.readerSafetyFb2StructureFailure()

        XCTAssertThrowsError(
            try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback")
        ) { error in
            guard let failure = error as? IosReaderFailure else {
                return XCTFail("Expected IosReaderFailure, got \(error)")
            }
            XCTAssertEqual(failure.safeContext["ruleId"], generated.ruleId)
            XCTAssertEqual(failure.safeContext["errorCode"], generated.errorCode)
        }
        XCTAssertEqual(
            try XCTUnwrap(file.resourceValues(forKeys: [.fileSizeKey]).fileSize),
            Int(sourceByteCount)
        )
    }

    func testGeneratedSafetyFailureKeepsRuleAndErrorContextOnIos() {
        for generated in [
            ErmaoShared.PublicKt.readerSafetyFb2StructureFailure(),
            ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure(),
            ErmaoShared.PublicKt.readerSafetyPdfRenderBudgetFailure(),
        ] {
            let failure = IosReaderFailure.safety(generated)
            XCTAssertEqual(failure.safeContext["ruleId"], generated.ruleId)
            XCTAssertEqual(failure.safeContext["errorCode"], generated.errorCode)
        }
    }

    func testFb2Utf16AndUnsectionedBody() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let encodings: [(String, String.Encoding)] = [
            ("UTF-8", .utf8), ("UTF-16", .utf16),
            ("UTF-16LE", .utf16LittleEndian), ("UTF-16BE", .utf16BigEndian),
        ]
        for (name, encoding) in encodings {
            let xml = "<?xml version='1.0' encoding='\(name)'?>" +
                "<!DOCTYPE FictionBook [<!ENTITY bodyText '中文正文'>]>" +
                "<FictionBook><body><p>&bodyText;</p></body></FictionBook>"
            let source = try XCTUnwrap(xml.data(using: encoding))
            try source.write(to: file)
            let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback")
            XCTAssertTrue(try XCTUnwrap(parsed.document.resources.first).xhtml.contains("<p>中文正文</p>"), name)
            XCTAssertEqual(try Data(contentsOf: file), source)
        }
    }

    func testFb2SafeDoctypePreservesDeclaredCharsetText() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let examples: [(String, String.Encoding, String)] = [
            ("windows-1251", .windowsCP1251, "Книга Текст"),
            ("windows-1252", .windowsCP1252, "Café €"),
        ]
        for (name, encoding, text) in examples {
            let xml = "<?xml version='1.0' encoding='\(name)'?><!DOCTYPE FictionBook>" +
                "<FictionBook><body><p>\(text)</p></body></FictionBook>"
            let source = try XCTUnwrap(xml.data(using: encoding))
            try source.write(to: file)
            let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Book")
            XCTAssertTrue(try XCTUnwrap(parsed.document.resources.first).xhtml.contains("<p>\(text)</p>"))
            XCTAssertEqual(try Data(contentsOf: file), source)
        }
    }

    func testFb2ExternalEntityIsLiteralizedWithoutCanaryContentOrFileChanges() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("original.fb2")
        let canary = directory.appendingPathComponent("canary.txt")
        let canaryText = "FB2_EXTERNAL_ENTITY_CANARY_CONTENT"
        let canaryBytes = Data(canaryText.utf8)
        try canaryBytes.write(to: canary)
        let encodings: [(String, String.Encoding)] = [
            ("UTF-8", .utf8), ("UTF-16", .utf16),
            ("UTF-16LE", .utf16LittleEndian), ("UTF-16BE", .utf16BigEndian),
        ]
        for (name, encoding) in encodings {
            for reference in ["", "&x;"] {
                let xml = "<?xml version='1.0' encoding='\(name)'?>" +
                    "<!DOCTYPE FictionBook [<!ENTITY x SYSTEM '\(canary.absoluteString)'>]>" +
                    "<FictionBook><body><p>中文\(reference)END</p></body></FictionBook>"
                let source = try XCTUnwrap(xml.data(using: encoding))
                try source.write(to: file)
                let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Book")
                let xhtml = try XCTUnwrap(parsed.document.resources.first).xhtml
                let expectedReference = reference.isEmpty ? "" : "&amp;x;"
                XCTAssertTrue(xhtml.contains("<p>中文\(expectedReference)END</p>"))
                XCTAssertFalse(xhtml.contains(canaryText))
                XCTAssertEqual(try Data(contentsOf: file), source)
            }
        }
        XCTAssertEqual(try Data(contentsOf: canary), canaryBytes)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted(), ["canary.txt", "original.fb2"])
    }

    func testFb2UnsupportedDeclaredEncodingDoesNotFallBackToUtf8() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let source = Data("<?xml version='1.0' encoding='not-a-charset'?><FictionBook><body><p>text</p></body></FictionBook>".utf8)
        try source.write(to: file)
        XCTAssertThrowsError(try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Book"))
        XCTAssertEqual(try Data(contentsOf: file), source)
    }

    func testLocatorProjectionMatchesV3GoldenSemantics() throws {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).url(
            forResource: "reader-normalization-v4",
            withExtension: "xhtml"
        ))
        let markup = try String(contentsOf: fixture, encoding: .utf8)

        XCTAssertEqual(
            try IosPublicationSecurityPolicy.locatorBodyProjection(data: Data(markup.utf8)),
            [
                ["path": "/body[1]", "localName": "body"],
                ["path": "/body[1]/h1[1]", "localName": "h1", "id": "chapter-title", "text": "天地玄黄"],
            ]
        )
    }

    func testDecoratedChapterQuotesCspAndRemainsStrictXhtml() throws {
        let markup = #"""
        <?xml version="1.0" encoding="utf-8" standalone="no"?>
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
        <html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title></head><body><p>Readable text</p></body></html>
        """#
        let secured = try IosPublicationSecurityPolicy.decorate(data: Data(markup.utf8))
        let decorated = String(decoding: secured, as: UTF8.self)

        XCTAssertTrue(decorated.contains(#"http-equiv="Content-Security-Policy" content="default-src 'none';"#))
        XCTAssertFalse(decorated.contains(#"content=default-src"#))
        XCTAssertTrue(decorated.contains(#"encoding="utf-8" standalone="no""#))

        let parser = XMLParser(data: secured)
        parser.shouldResolveExternalEntities = false
        XCTAssertTrue(parser.parse(), "Decorated XHTML must remain well formed: \(String(describing: parser.parserError))")
    }

    @MainActor
    func testReflowableResourceFailurePresentsReadErrorWithoutOverwritingFirstFailure() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("reader-resource-error-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let defaultsName = "reader-resource-error-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: defaultsName))
        defer { defaults.removePersistentDomain(forName: defaultsName) }
        let deviceIdentity = IosReaderDeviceIdentity(defaults: defaults)
        let identity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: ErmaoShared.PublicKt.createReaderSyncNamespace(
                serverIdentity: "error-server", userId: "error-user", authorizationVersion: 1
            ),
            clientId: deviceIdentity.stableDeviceId(), bookId: "book", resourceId: "resource"
        )
        let database = try IosReaderLocalDatabase(
            identity: identity,
            databaseURL: root.appendingPathComponent("Reader.sqlite3")
        )
        let session = IosReflowableReaderSession(
            resourceID: "resource",
            displayTitle: "Resource",
            managedStore: try IosManagedPublicationStore(root: root.appendingPathComponent("Publications")),
            progressStore: IosLocalOnlyReaderProgressStore(database: database),
            deviceIdentity: deviceIdentity
        )
        let navigator = ReaderSecurityNavigator()
        let failedHref = try XCTUnwrap(RelativeURL(path: "chapter-missing.xhtml"))

        session.navigator(
            navigator,
            didFailToLoadResourceAt: failedHref,
            withError: .decoding("synthetic chapter decode failure")
        )
        XCTAssertEqual(session.presentationError, .readFailed)
        session.navigator(navigator, presentError: .copyForbidden)
        XCTAssertEqual(session.presentationError, .readFailed, "A later navigator error must not overwrite the first failure")

        try await session.close()
        await database.close()
    }

    @MainActor
    func testGeneratedChapterCspBlocksScriptsEventsConnectionsAndEmbeddedContentInWebKit() async throws {
        let configuration = WKWebViewConfiguration()
        let requests = ReaderSecuritySchemeHandler()
        configuration.setURLSchemeHandler(requests, forURLScheme: "reader-test")
        let webView = WKWebView(frame: CGRect(x: 0, y: 0, width: 390, height: 844), configuration: configuration)
        let loaded = expectation(description: "WebKit loaded the generated chapter")
        let delegate = ReaderSecurityNavigationDelegate(loaded: loaded)
        webView.navigationDelegate = delegate
        let hostile = #"<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body><p>Readable text</p><script>window.inlineRan=true</script><script src="reader-test://publication/script.js"></script><button id="event" onclick="window.eventRan=true">Click</button><img src="reader-test://external/image.png" onerror="window.eventRan=true"/><iframe src="reader-test://publication/frame"></iframe><object data="reader-test://publication/object"></object><embed src="reader-test://publication/embed"/></body></html>"#
        let secured = try IosPublicationSecurityPolicy.generatedChapter(hostile)
        webView.load(secured, mimeType: "application/xhtml+xml", characterEncodingName: "utf-8", baseURL: try XCTUnwrap(URL(string: "reader-test://publication/chapter.xhtml")))
        await fulfillment(of: [loaded], timeout: 10)

        let renderedSafely = try await webView.evaluateJavaScript(#"(()=>{document.getElementById('event').click();const blocked=['iframe','object','embed'].every(selector=>{const element=document.querySelector(selector);return element===null||getComputedStyle(element).display==='none'});return document.body.textContent.includes('Readable text')&&!window.inlineRan&&!window.eventRan&&blocked})()"#)
        XCTAssertEqual(renderedSafely as? Bool, true)
        try await webView.evaluateJavaScript(#"(()=>{window.connectionBlocked=null;fetch('reader-test://external/data').then(()=>{window.connectionBlocked=false},()=>{window.connectionBlocked=true});return true})()"#)
        var connectionBlocked = false
        for _ in 0 ..< 50 where !connectionBlocked {
            connectionBlocked = try await webView.evaluateJavaScript("window.connectionBlocked === true") as? Bool == true
            if !connectionBlocked { try await Task.sleep(for: .milliseconds(20)) }
        }
        XCTAssertTrue(connectionBlocked)
        XCTAssertEqual(requests.count, 0, "No external or embedded resource may reach the transport")
        webView.stopLoading()
        webView.navigationDelegate = nil
    }

    @MainActor
    func testManagedStoragePreservesUnparseableAndEmptyOriginalsAcrossReopen() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try IosManagedPublicationStore(root: root.appendingPathComponent("managed"))
        for format: ErmaoShared.ReaderSourceFormat in [.txt, .epub, .fb2, .mobi, .pdf, .cbz] {
            var inputs = [Data(), Data("A\0B\0".utf8)]
            if format == .epub {
                inputs.append(Data("Truncated publication; no zip directory".utf8))
            }
            for (index, bytes) in inputs.enumerated() {
                let resourceID = "\(format.wireValue)-\(index)"
                let file = root.appendingPathComponent(resourceID).appendingPathExtension(format.wireValue)
                try bytes.write(to: file)
                let managed = try await store.importPublication(
                    from: file, resourceID: resourceID, displayTitle: "Fixture", sourceFormat: format,
                    parserVersion: "test-parser", normalizationVersion: "test-normalization"
                )
                let reopened = try await store.resolve(resourceID: resourceID)
                if format == .epub {
                    let expected = ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure()
                    for publication in [managed, reopened] {
                        do {
                            _ = try await IosEpubArchiveSafetyPreflight.verify(fileURL: publication.fileURL)
                            XCTFail("Expected corrupt EPUB rejection")
                        } catch {
                            let failure = try XCTUnwrap(error as? IosReaderFailure)
                            XCTAssertEqual(failure.code, .parseFailed)
                            XCTAssertEqual(failure.safeContext["ruleId"], expected.ruleId)
                            XCTAssertEqual(failure.safeContext["errorCode"], expected.errorCode)
                            XCTAssertNotNil(failure.underlyingError)
                        }
                    }
                }
                XCTAssertEqual(try Data(contentsOf: managed.fileURL), bytes)
                XCTAssertEqual(try Data(contentsOf: reopened.fileURL), bytes)
                XCTAssertEqual(try Data(contentsOf: file), bytes)
            }
        }
    }

    func testSecurityPolicySanitizesAuthorMarkupBeforeDecoratingHead() throws {
        let secured = try IosPublicationSecurityPolicy.decorate(data: Data("<html><head></head><body><p>Text</p></body></html>".utf8))
        let policy = String(decoding: secured, as: UTF8.self)
        XCTAssertTrue(policy.contains("style-src 'self' readium://assets"))
        XCTAssertTrue(policy.contains("font-src 'self' readium://assets"))
        XCTAssertTrue(policy.contains("script-src 'none'"))
        XCTAssertTrue(policy.contains("connect-src 'none'"))
        XCTAssertFalse(policy.contains("readium:;"))

        let unsafe = #"<html><head><meta http-equiv="refresh" content="0;https://bad.example"/><style>body{background:url('https://bad.example/a.png')}</style></head><body onload="steal()"><script>steal()</script><iframe src="chapter.xhtml"></iframe><img src="https://bad.example/cover.jpg"/><a href="https://example.com/help">Help</a><a href="javascript:steal()">Bad</a><img src="images/local.jpg"/></body></html>"#
        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(unsafe)

        XCTAssertFalse(decorated.contains("<script>steal()</script>"))
        XCTAssertFalse(decorated.contains("<iframe"))
        XCTAssertFalse(decorated.contains("onload=\"steal()\""))
        XCTAssertFalse(decorated.contains("javascript:steal()"))
        XCTAssertFalse(decorated.lowercased().contains("http-equiv=\"refresh\""))
        XCTAssertTrue(decorated.contains("<a href=\"https://example.com/help\">Help</a>"))
        XCTAssertTrue(decorated.contains("script-src 'none'"))
    }

    func testStandardEpubDoctypeAndNonbreakingSpaceRemainReadable() throws {
        let markup = #"""
        <?xml version="1.0"?>
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
          "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
        <html xmlns="http://www.w3.org/1999/xhtml"><head><title>EPUB</title></head>
        <body><h1 id="chapter">Chapter&nbsp;One</h1></body></html>
        """#

        let projection = try IosPublicationSecurityPolicy.locatorBodyProjection(
            data: Data(markup.utf8)
        )
        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(markup)

        XCTAssertEqual(projection.last?["text"], "Chapter One")
        XCTAssertTrue(decorated.contains("<!DOCTYPE html PUBLIC"))
        XCTAssertTrue(decorated.contains("Chapter&nbsp;One"))
    }

    func testInvalidOrOversizedMarkupFailsClosedWithoutBlankDocument() {
        let oversized = "<html><head></head><body>" +
            String(repeating: "x", count: 64 * 1_024 * 1_024 + 1) +
            "</body></html>"
        XCTAssertThrowsError(try IosPublicationSecurityAdapter().decorateMarkup(oversized))
        XCTAssertThrowsError(
            try IosPublicationSecurityAdapter().decorateMarkup(
                "<html><body><p>Missing head</p></body></html>"
            )
        )
        XCTAssertThrowsError(
            try IosPublicationSecurityAdapter().decorateMarkup(
                #"<!DOCTYPE html SYSTEM "https://attacker.invalid/book.dtd"><html><head></head><body><p>Body</p></body></html>"#
            )
        )
    }

    func testFakeHeadInsideCommentAndCdataCannotCaptureSecurityDecoration() throws {
        let markup = #"""
        <?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml">
        <!-- <head><script>fake()</script></head> -->
        <head><title>Real</title></head>
        <body><script><![CDATA["<head>fake</head>"]]></script><p>Body</p></body>
        </html>
        """#

        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(markup)
        let profile = try XCTUnwrap(decorated.range(of: "Content-Security-Policy"))
        let comment = try XCTUnwrap(decorated.range(of: "<!-- <head>"))
        let title = try XCTUnwrap(decorated.range(of: "<title>Real</title>"))

        XCTAssertGreaterThan(profile.lowerBound, comment.lowerBound)
        XCTAssertLessThan(profile.lowerBound, title.lowerBound)
        XCTAssertFalse(decorated.contains(#"<![CDATA["<head>fake</head>"]]>"#))
    }

    func testEpubArchivePreflightUsesGeneratedStructureAndBudgetFailures() throws {
        let structure = ErmaoShared.PublicKt.readerSafetyEpubArchiveStructureFailure()
        let safe = IosEpubArchiveSafetyPreflight.EntryFacts(
            path: "OPS/chapter.xhtml",
            isDirectory: false,
            isSymbolicLink: false,
            isEncrypted: false,
            uncompressedSize: 16,
            compressedSize: 16,
            crc32: 0,
            localHeaderOffset: 0,
            dataOffset: 30,
            physicalEndOffset: 46
        )
        XCTAssertNoThrow(
            try IosEpubArchiveSafetyPreflight.verifyMetadata([safe], archiveLength: 1_024)
        )

        let structuralCases = [
            [IosEpubArchiveSafetyPreflight.EntryFacts(
                path: "../chapter.xhtml", isDirectory: false, isSymbolicLink: false,
                isEncrypted: false, uncompressedSize: 16, compressedSize: 16, crc32: 0,
                localHeaderOffset: 0, dataOffset: 30, physicalEndOffset: 46
            )],
            [IosEpubArchiveSafetyPreflight.EntryFacts(
                path: "OPS/link", isDirectory: false, isSymbolicLink: true,
                isEncrypted: false, uncompressedSize: 16, compressedSize: 16, crc32: 0,
                localHeaderOffset: 0, dataOffset: 30, physicalEndOffset: 46
            )],
        ]
        let escapedResult = try IosEpubArchiveSafetyPreflight.verifyMetadata(
            structuralCases[0],
            archiveLength: 1_024
        )
        XCTAssertEqual(
            escapedResult.quarantineFor(path: "../chapter.xhtml")?.ruleId,
            structure.ruleId
        )
        let symlinkResult = try IosEpubArchiveSafetyPreflight.verifyMetadata(
            structuralCases[1],
            archiveLength: 1_024
        )
        XCTAssertEqual(
            symlinkResult.quarantineFor(path: "OPS/link")?.ruleId,
            structure.ruleId
        )

        let encrypted = IosEpubArchiveSafetyPreflight.EntryFacts(
            path: "OPS/secret", isDirectory: false, isSymbolicLink: false,
            isEncrypted: true, uncompressedSize: 16, compressedSize: 16, crc32: 0,
            localHeaderOffset: 0, dataOffset: 30, physicalEndOffset: 46
        )
        XCTAssertNoThrow(
            try IosEpubArchiveSafetyPreflight.verifyMetadata([encrypted], archiveLength: 1_024)
        )

        let overlapping = IosEpubArchiveSafetyPreflight.EntryFacts(
            path: "OPS/next.xhtml", isDirectory: false, isSymbolicLink: false,
            isEncrypted: false, uncompressedSize: 16, compressedSize: 16, crc32: 0,
            localHeaderOffset: 40, dataOffset: 70, physicalEndOffset: 86
        )
        let overlapResult = try IosEpubArchiveSafetyPreflight.verifyMetadata(
            [safe, overlapping], archiveLength: 1_024
        )
        XCTAssertEqual(
            overlapResult.quarantinedResources["OPS/chapter.xhtml"]?.ruleId,
            ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure().ruleId
        )
        XCTAssertEqual(
            overlapResult.quarantinedResources["OPS/next.xhtml"]?.ruleId,
            ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure().ruleId
        )

        let duplicateResult = try IosEpubArchiveSafetyPreflight.verifyMetadata(
            [safe, safe], archiveLength: 1_024
        )
        XCTAssertEqual(
            duplicateResult.quarantinedResources["OPS/chapter.xhtml"]?.ruleId,
            ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure().ruleId
        )

        let container = Data(
            #"<?xml version="1.0"?><container><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>"#.utf8
        )
        XCTAssertEqual(
            try IosEpubArchiveSafetyPreflight.rootfilePaths(from: container),
            ["OPS/package.opf"]
        )

        let countLimit = ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryMaxCount()
        assertEpubSafetyFailure(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryCountFailure()) {
            var entries: [IosEpubArchiveSafetyPreflight.EntryFacts] = []
            for index in 0 ... countLimit {
                let offset = UInt64(index) * 2
                entries.append(IosEpubArchiveSafetyPreflight.EntryFacts(
                    path: "OPS/\(index)", isDirectory: false, isSymbolicLink: false,
                    isEncrypted: false, uncompressedSize: 0, compressedSize: 0, crc32: 0,
                    localHeaderOffset: offset, dataOffset: offset, physicalEndOffset: offset
                ))
            }
            try IosEpubArchiveSafetyPreflight.verifyMetadata(entries, archiveLength: UInt64.max)
        }

        assertEpubSafetyFailure(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryBytesFailure()) {
            let oversized = IosEpubArchiveSafetyPreflight.EntryFacts(
                path: safe.path, isDirectory: false, isSymbolicLink: false, isEncrypted: false,
                uncompressedSize: UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryMaxBytes() + 1),
                compressedSize: 1, crc32: 0, localHeaderOffset: 0, dataOffset: 30,
                physicalEndOffset: 31
            )
            try IosEpubArchiveSafetyPreflight.verifyMetadata([oversized], archiveLength: UInt64.max)
        }

        assertEpubSafetyFailure(ErmaoShared.PublicKt.readerSafetyEpubArchiveCompressionRatioFailure()) {
            let ratio = IosEpubArchiveSafetyPreflight.EntryFacts(
                path: safe.path, isDirectory: false, isSymbolicLink: false, isEncrypted: false,
                uncompressedSize: UInt64(
                    ErmaoShared.PublicKt.readerSafetyEpubArchiveCompressionRatioMax() + 1
                ),
                compressedSize: 1, crc32: 0, localHeaderOffset: 0, dataOffset: 30,
                physicalEndOffset: 31
            )
            try IosEpubArchiveSafetyPreflight.verifyMetadata([ratio], archiveLength: UInt64.max)
        }
    }

    private func assertEpubSafetyFailure(
        _ expected: ErmaoShared.ReaderSafetyFailure,
        action: () throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertThrowsError(try action(), file: file, line: line) { error in
            guard let failure = error as? IosReaderFailure else {
                return XCTFail("Expected IosReaderFailure, got \(error)", file: file, line: line)
            }
            XCTAssertEqual(failure.safeContext["ruleId"], expected.ruleId, file: file, line: line)
            XCTAssertEqual(failure.safeContext["errorCode"], expected.errorCode, file: file, line: line)
        }
    }
}

private final class PhysicalReaderV5PositionPort: ErmaoShared.ReaderPositionServerPort, @unchecked Sendable {
    private let lock = NSLock()
    private var uploads: [ErmaoShared.ReaderPositionUpload] = []

    var lastUploadedPosition: ErmaoShared.ReaderPositionReport? {
        withLock { uploads.last?.mutation.position }
    }

    func push(
        upload: ErmaoShared.ReaderPositionUpload
    ) async throws -> ErmaoShared.ReaderPositionPushResult {
        let revision = withLock {
            uploads.append(upload)
            return Int64(uploads.count)
        }
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

private func canonicalJSONObjectData(_ json: String) throws -> Data {
    let value = try JSONSerialization.jsonObject(with: Data(json.utf8))
    return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
}

private func cssRGB(_ hex: String) -> String {
    let value = UInt64(hex.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0
    return "rgb(\((value >> 16) & 0xff), \((value >> 8) & 0xff), \(value & 0xff))"
}

@MainActor
private final class ReaderSecuritySchemeHandler: NSObject, WKURLSchemeHandler {
    private(set) var count = 0

    func webView(_ webView: WKWebView, start urlSchemeTask: any WKURLSchemeTask) {
        count += 1
        urlSchemeTask.didFailWithError(URLError(.cannotConnectToHost))
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: any WKURLSchemeTask) {}
}

@MainActor
private final class ReaderSecurityNavigationDelegate: NSObject, WKNavigationDelegate {
    let loaded: XCTestExpectation

    init(loaded: XCTestExpectation) { self.loaded = loaded }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded.fulfill() }
}

private final class ReaderSecurityNavigator: Navigator {
    let publication = Publication(
        manifest: Manifest(metadata: Metadata(title: "Reader security test"), readingOrder: [])
    )
    var currentLocation: Locator? { nil }

    func go(to locator: Locator, options: NavigatorGoOptions) async -> Bool { false }
    func go(to link: ReadiumShared.Link, options: NavigatorGoOptions) async -> Bool { false }
    func goForward(options: NavigatorGoOptions) async -> Bool { false }
    func goBackward(options: NavigatorGoOptions) async -> Bool { false }
}
