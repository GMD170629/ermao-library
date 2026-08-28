import UIKit
import SwiftUI
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import XCTest
@preconcurrency import WebKit
@testable import ErmaoLibrary

final class ReaderSecurityTests: XCTestCase {
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
            parserVersion: "shuku-txt-parser-v1", normalizationVersion: "shuku-txt-publication-v2"
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
            let diagnostic = await navigator.evaluateJavaScript("JSON.stringify({height:document.documentElement.scrollHeight,viewport:innerHeight,width:document.documentElement.scrollWidth,font:getComputedStyle(document.querySelector('p')).fontFamily,size:getComputedStyle(document.querySelector('p')).fontSize,line:getComputedStyle(document.querySelector('p')).lineHeight,color:getComputedStyle(document.querySelector('p')).color,rootColumn:getComputedStyle(document.documentElement).columnWidth,fonts:[...document.fonts].map(f=>({family:f.family,status:f.status}))})")
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
        let initialProgress = try await progressStore.load(sourceId: "controls")
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
        let savedProgress = try await progressStore.load(sourceId: "controls")
        let baseline = try XCTUnwrap(savedProgress, "Normal page navigation must persist an exact location")
        let progressCodec = ErmaoShared.PublicKt.createReaderProgressJson()
        let baselinePayload = try progressCodec.encode(progress: baseline)
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
            let currentProgress = try await progressStore.load(sourceId: "controls")
            XCTAssertEqual(try progressCodec.encode(progress: XCTUnwrap(currentProgress)), baselinePayload,
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
        for (theme, rgb) in [(IosReaderTheme.day, "rgb(30, 41, 59)"), (.warm, "rgb(43, 33, 24)"), (.green, "rgb(32, 49, 38)"), (.black, "rgb(248, 250, 252)"), (.night, "rgb(226, 232, 240)")] {
            preferences.theme = theme
            try await applyNativePreferences()
            try await expectRendered("getComputedStyle(document.querySelector('p')).color === '\(rgb)'", "Theme must update the paragraph immediately: \(theme)")
        }
        preferences.themeMode = .system
        try await applyNativePreferences()
        let systemThemeNavigator = try XCTUnwrap(session.navigator)
        for (appearance, rgb) in [(UIUserInterfaceStyle.dark, "rgb(226, 232, 240)"), (.light, "rgb(30, 41, 59)")] {
            session.refreshSystemAppearance(appearance)
            try await expectRendered("getComputedStyle(document.querySelector('p')).color === '\(rgb)'", "System appearance must update the actual body color: \(appearance)")
            XCTAssertTrue(session.navigator === systemThemeNavigator)
            try await applyNativePreferences()
        }

        preferences = IosReaderPreferences()
        try await applyNativePreferences()
        XCTAssertEqual(session.preferences, IosReaderPreferences())
        let defaultTypography = #"""
        (() => {
            const style = getComputedStyle(document.querySelector('p'));
            return style.fontFamily.includes('Shuku Sans') &&
                Math.abs(parseFloat(style.fontSize) - 18) < 0.7 &&
                Math.abs(parseFloat(style.lineHeight) / parseFloat(style.fontSize) - 1.9) < 0.05 &&
                style.color === 'rgb(43, 33, 24)';
        })()
        """#
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
        let finalProgress = try await progressStore.load(sourceId: "controls")
        XCTAssertEqual(try progressCodec.encode(progress: XCTUnwrap(finalProgress)), baselinePayload,
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
    func testOnlineFailurePreservesItsReasonAndStageWithoutReadingAnOriginalFile() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("reader-online-errors-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try IosManagedPublicationStore(root: root)
        let manifestPath = "/api/reader/v4/resources/online-errors/publication/manifest.json"
        let positionsPath = manifestPath.replacingOccurrences(of: "manifest.json", with: "positions.json")
        let source = ErmaoShared.RemoteReflowableReaderSource(
            resourceId: "online-errors", displayTitle: "Online error fixture",
            bookId: "book", assetId: "original", sourceFormat: .txt,
            namespace: ErmaoShared.PublicKt.createReaderSyncNamespace(
                serverIdentity: "server", userId: "user", authorizationVersion: 1
            ),
            manifestApiPath: manifestPath,
            positionsApiPath: positionsPath
        )
        func makeSession(port: StubOnlinePublicationPort) -> IosReflowableReaderSession {
            IosReflowableReaderSession(
                resourceID: source.resourceId, displayTitle: source.displayTitle, sourceFormat: .txt,
                onlineSource: source,
                onlinePublication: ErmaoShared.OnlinePublicationSession(source: source, port: port),
                managedStore: store, progressStore: IosNonBlockingReaderProgressStore()
            )
        }
        let failures: [(String, IosReaderFailureCode)] = [
            ("PUBLICATION_TXT_NUL_CHARACTER", .txtNulCharacter),
            ("PUBLICATION_TXT_ENCODING_UNSUPPORTED", .txtEncodingUnsupported),
            ("PUBLICATION_TXT_EMPTY", .txtEmpty),
            ("PUBLICATION_NOT_FOUND", .publicationUnavailable),
            ("UNAUTHORIZED", .unauthorized),
            ("FORBIDDEN", .forbidden),
            ("BINARY_CONTENT_TYPE_MISSING", .invalidResponse),
            ("SERVER_FAILURE", .serverUnavailable),
            ("REQUEST_TIMEOUT", .requestTimeout),
            ("TLS_FAILURE", .tlsFailure),
            ("RATE_LIMITED", .rateLimited),
            ("TRANSPORT_FAILURE", .engineError),
        ]
        for (sourceCode, expected) in failures {
            let port = StubOnlinePublicationPort(code: sourceCode)
            let session = makeSession(port: port)
            await session.open()
            XCTAssertEqual(session.phase, .failed(expected), sourceCode)
            let failure = try XCTUnwrap(session.onlineFailure, sourceCode)
            XCTAssertEqual(failure.onlineContext?.sourceCode, sourceCode)
            XCTAssertEqual(failure.onlineContext?.stage, "manifest")
            XCTAssertNotNil(failure.underlyingError)
            XCTAssertNil(session.navigator)
            XCTAssertEqual(port.requestedPaths, [manifestPath])
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
            XCTAssertFalse(session.failureDescription(for: expected).contains("已下载"))
            try await session.close()
        }
        let nativeParserFailures = [
            (
                manifest: #"{"readingOrder":[{"href":"chapter.xhtml","type":"application/xhtml+xml"}]}"#,
                positions: #"{"positions":[{"href":"chapter.xhtml","type":"application/xhtml+xml"}]}"#,
                stage: "manifest", code: "PUBLICATION_MANIFEST_INVALID"
            ),
            (
                manifest: #"{"metadata":{"title":"Fixture"},"readingOrder":[{"href":"chapter.xhtml","type":"not a media type"}]}"#,
                positions: #"{"positions":[{"href":"chapter.xhtml","type":"not a media type"}]}"#,
                stage: "positions", code: "PUBLICATION_POSITIONS_INVALID"
            ),
        ]
        for example in nativeParserFailures {
            let port = StubOnlinePublicationPort(contents: [manifestPath: example.manifest, positionsPath: example.positions])
            let session = makeSession(port: port)
            await session.open()
            XCTAssertEqual(session.phase, .failed(.invalidResponse), example.code)
            let failure = try XCTUnwrap(session.onlineFailure, example.code)
            XCTAssertEqual(failure.onlineContext?.sourceCode, example.code)
            XCTAssertEqual(failure.onlineContext?.stage, example.stage)
            XCTAssertNotNil(failure.underlyingError)
            XCTAssertNil(session.navigator)
            XCTAssertEqual(port.requestedPaths, [manifestPath, positionsPath])
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
            try await session.close()
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
        XCTAssertEqual(parsed.document.tableOfContents.first?.children.first?.href,
                       "fb2/section-0001.xhtml#fb2-node-000002")
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

    func testGeneratedTxtPreservesNulAndEscapesActiveMarkupWithoutXmlPrevalidation() throws {
        let publication = try ErmaoShared.TxtPublicationNormalizer().normalize(
            decodedText: "a\0b\0<script>alert(1)</script>", publicationTitle: "Book"
        )
        let resource = try XCTUnwrap(publication.resources.first)
        let decorated = String(decoding: IosPublicationSecurityPolicy.generatedChapter(resource.xhtml), as: UTF8.self)
        XCTAssertTrue(decorated.contains("a\0b\0&lt;script&gt;"))
        XCTAssertTrue(decorated.contains("script-src 'none'"))
        XCTAssertFalse(decorated.contains("<script>"))
    }

    func testFb2ActualXmlAndBase64ErrorsFailClosed() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("original.fb2")
        let examples = [
            "<FictionBook><body><p>broken</body></FictionBook>",
            "<!DOCTYPE FictionBook [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><FictionBook><body><p>&x;</p></body></FictionBook>",
            "<FictionBook><body><section id='x'/><section id='x'/></body></FictionBook>",
            "<FictionBook><body><p>text</p></body><binary id='image' content-type='image/png'>!!!!</binary></FictionBook>",
        ]
        for (index, example) in examples.enumerated() {
            let bytes = Data(example.utf8)
            try bytes.write(to: file)
            XCTAssertThrowsError(try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback"), "Invalid FB2 case \(index)")
            XCTAssertEqual(try Data(contentsOf: file), bytes)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), ["original.fb2"])
    }

    func testFb2Utf16AndUnsectionedBody() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let xml = "<?xml version='1.0' encoding='UTF-16'?><FictionBook><body><p>中文正文</p></body></FictionBook>"
        try XCTUnwrap(xml.data(using: .utf16)).write(to: file)
        let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback")
        XCTAssertTrue(try XCTUnwrap(parsed.document.resources.first).xhtml.contains("<p>中文正文</p>"))
    }

    func testLocatorProjectionMatchesV2GoldenSemantics() throws {
        let markup = #"""
        <?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml"><head><title>Projection</title></head>
        <body><h1 id="chapter-title">&#22825;&#22320;&#29572;&#40644;</h1><form>
        <p id="target">Cafe&#769;   &#23431;&#23449;&#27946;&#33618;</p>
        <p>duplicate text</p><p>duplicate text</p></form><iframe src="remote"></iframe></body></html>
        """#

        XCTAssertEqual(
            try IosPublicationSecurityPolicy.locatorBodyProjection(data: Data(markup.utf8)),
            [
                ["path": "/body[1]", "localName": "body"],
                ["path": "/body[1]/h1[1]", "localName": "h1", "id": "chapter-title", "text": "天地玄黄"],
                ["path": "/body[1]/form[1]", "localName": "form"],
                ["path": "/body[1]/form[1]/p[1]", "localName": "p", "id": "target", "text": "Café 宇宙洪荒"],
                ["path": "/body[1]/form[1]/p[2]", "localName": "p", "text": "duplicate text"],
                ["path": "/body[1]/form[1]/p[3]", "localName": "p", "text": "duplicate text"],
                ["path": "/body[1]/iframe[1]", "localName": "iframe"],
            ]
        )
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
        let hostile = #"<html><head></head><body><p>Readable text</p><script>window.inlineRan=true</script><script src="reader-test://publication/script.js"></script><button id="event" onclick="window.eventRan=true">Click</button><img src="reader-test://external/image.png" onerror="window.eventRan=true"/><iframe src="reader-test://publication/frame"></iframe><object data="reader-test://publication/object"></object><embed src="reader-test://publication/embed"/></body></html>"#
        let secured = IosPublicationSecurityPolicy.generatedChapter(hostile)
        webView.load(secured, mimeType: "text/html", characterEncodingName: "utf-8", baseURL: try XCTUnwrap(URL(string: "reader-test://publication/chapter")))
        await fulfillment(of: [loaded], timeout: 10)
        let blocked = try await webView.callAsyncJavaScript(#"document.getElementById('event').click();let connectionBlocked=false;try{await fetch('reader-test://external/data')}catch{connectionBlocked=true}return !window.inlineRan&&!window.eventRan&&connectionBlocked&&getComputedStyle(document.querySelector('iframe')).display==='none'"#, arguments: [:], in: nil, contentWorld: .page)
        XCTAssertEqual(blocked as? Bool, true)
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
            for (index, bytes) in [Data(), Data("A\0B\0".utf8)].enumerated() {
                let resourceID = "\(format.wireValue)-\(index)"
                let file = root.appendingPathComponent(resourceID).appendingPathExtension(format.wireValue)
                try bytes.write(to: file)
                let managed = try await store.importPublication(
                    from: file, resourceID: resourceID, displayTitle: "Fixture", sourceFormat: format,
                    parserVersion: "test-parser", normalizationVersion: "test-normalization"
                )
                let reopened = try await store.resolve(resourceID: resourceID)
                XCTAssertEqual(try Data(contentsOf: managed.fileURL), bytes)
                XCTAssertEqual(try Data(contentsOf: reopened.fileURL), bytes)
                XCTAssertEqual(try Data(contentsOf: file), bytes)
            }
        }
    }

    func testSecurityPolicyDecoratesOnlyHeadAndPreservesAuthorBody() throws {
        let secured = try IosPublicationSecurityPolicy.decorate(data: Data("<html><head></head><body><p>Text</p></body></html>".utf8))
        let policy = String(decoding: secured, as: UTF8.self)
        XCTAssertTrue(policy.contains("style-src 'self' readium://assets"))
        XCTAssertTrue(policy.contains("font-src 'self' readium://assets"))
        XCTAssertTrue(policy.contains("script-src 'none'"))
        XCTAssertTrue(policy.contains("connect-src 'none'"))
        XCTAssertFalse(policy.contains("readium:;"))

        let unsafe = #"<html><head><meta http-equiv="refresh" content="0;https://bad.example"/><style>body{background:url('https://bad.example/a.png')}</style></head><body onload="steal()"><script>steal()</script><iframe src="chapter.xhtml"></iframe><img src="https://bad.example/cover.jpg"/><a href="https://example.com/help">Help</a><a href="javascript:steal()">Bad</a><img src="images/local.jpg"/></body></html>"#
        let originalBody = try XCTUnwrap(unsafe.range(of: #"(?s)<body.*</body>"#, options: .regularExpression))

        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(unsafe)

        let decoratedBody = try XCTUnwrap(decorated.range(of: #"(?s)<body.*</body>"#, options: .regularExpression))
        XCTAssertEqual(String(unsafe[originalBody]), String(decorated[decoratedBody]))
        XCTAssertTrue(decorated.contains("<script>steal()</script>"))
        XCTAssertTrue(decorated.contains("<iframe"))
        XCTAssertTrue(decorated.contains("onload=\"steal()\""))
        XCTAssertTrue(decorated.contains("javascript:steal()"))
        XCTAssertFalse(decorated.lowercased().contains("http-equiv=\"refresh\""))
        XCTAssertTrue(decorated.contains("data-shuku-security-profile=\"ios-v2\""))
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
        let profile = try XCTUnwrap(decorated.range(of: "data-shuku-security-profile=\"ios-v2\""))
        let comment = try XCTUnwrap(decorated.range(of: "<!-- <head>"))
        let title = try XCTUnwrap(decorated.range(of: "<title>Real</title>"))

        XCTAssertGreaterThan(profile.lowerBound, comment.lowerBound)
        XCTAssertLessThan(profile.lowerBound, title.lowerBound)
        XCTAssertTrue(decorated.contains(#"<![CDATA["<head>fake</head>"]]>"#))
    }
}

private final class StubOnlinePublicationPort: ErmaoShared.PublicationResourcePort, @unchecked Sendable {
    private let code: String
    private let contents: [String: String]
    private let lock = NSLock()
    private var paths: [String] = []

    init(code: String) {
        self.code = code
        contents = [:]
    }

    init(contents: [String: String]) {
        code = "UNEXPECTED_TEST_REQUEST"
        self.contents = contents
    }

    var requestedPaths: [String] {
        lock.lock()
        defer { lock.unlock() }
        return paths
    }

    func read(apiPath: String, maximumBytes: Int32, mediaTypes: Set<String>) async throws -> any ErmaoShared.OnlinePublicationReadResult {
        recordPath(apiPath)
        if let text = contents[apiPath] {
            let bytes = KotlinByteArray(size: Int32(text.utf8.count))
            for (index, byte) in text.utf8.enumerated() {
                bytes.set(index: Int32(index), value: Int8(bitPattern: byte))
            }
            return ErmaoShared.OnlinePublicationReadResultContent(bytes: bytes)
        }
        return ErmaoShared.OnlinePublicationReadResultFailure(code: code, stage: nil, cause: nil, source: "server")
    }

    func close() {}

    private func recordPath(_ path: String) {
        lock.lock()
        defer { lock.unlock() }
        paths.append(path)
    }
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
