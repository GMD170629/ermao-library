import Combine
import CryptoKit
import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import UIKit

enum IosReaderTheme: String, CaseIterable, Codable, Identifiable, Sendable {
    case day, warm, green, night, black
    var id: Self { self }
}

enum IosReaderThemeMode: String, CaseIterable, Codable, Identifiable, Sendable {
    case manual, system
    var id: Self { self }
}

enum IosReaderProgressStyle: String, CaseIterable, Codable, Identifiable, Sendable {
    case auto, percent, position, remaining, hidden
    var id: Self { self }
}

enum IosReaderTapZones: String, CaseIterable, Codable, Identifiable, Sendable {
    case standard, reversed, disabled
    var id: Self { self }
}

enum IosReaderFontFamily: String, CaseIterable, Codable, Identifiable, Sendable {
    case pingfang, songti, kaiti
    var id: Self { self }

    var readium: FontFamily {
        switch self {
        case .pingfang: FontFamily(rawValue: "Shuku Sans")
        case .songti: FontFamily(rawValue: "Shuku Songti")
        case .kaiti: FontFamily(rawValue: "Shuku Kaiti")
        }
    }
}

enum IosReaderPageMargin: String, CaseIterable, Codable, Identifiable, Sendable {
    case narrow, standard, wide
    var id: Self { self }
}

enum IosReaderSpreadMode: String, CaseIterable, Codable, Identifiable, Sendable {
    case auto, single, double
    var id: Self { self }
}

enum IosReaderReadingMode: String, CaseIterable, Codable, Identifiable, Sendable {
    case paged
    case continuousScroll
    var id: Self { self }
}

enum IosReaderTextAlignment: String, CaseIterable, Codable, Identifiable, Sendable {
    case publisher, left, justify
    var id: Self { self }
}

enum IosComicDirection: String, CaseIterable, Codable, Identifiable, Sendable { case ltr, rtl; var id: Self { self } }
enum IosComicSpread: String, CaseIterable, Codable, Identifiable, Sendable { case single, double; var id: Self { self } }
enum IosComicFlow: String, CaseIterable, Codable, Identifiable, Sendable { case paginated, scrolled; var id: Self { self } }
enum IosPdfFit: String, CaseIterable, Codable, Identifiable, Sendable { case width, page; var id: Self { self } }
enum IosPdfCropMargins: String, CaseIterable, Codable, Identifiable, Sendable { case off, auto; var id: Self { self } }

struct IosReaderPreferences: Codable, Equatable, Sendable {
    var schemaVersion = 5
    var theme = IosReaderTheme.warm
    var themeMode = IosReaderThemeMode.manual
    var progressStyle = IosReaderProgressStyle.auto
    var showClock = false
    var tapZones = IosReaderTapZones.standard
    var swipePageTurn = true
    var keyboardPageTurn = true
    var volumeKeyPageTurn = false
    var keepScreenAwake = false
    var fontSize = 18
    var lineHeight = 1.9
    var pageWidth = 1350
    var fontFamily = IosReaderFontFamily.pingfang
    var fontWeight = 400
    var letterSpacing = 0.0
    var pageMargin = IosReaderPageMargin.standard
    var spreadMode = IosReaderSpreadMode.single
    var pageTurnAnimation = "slide"
    var readingMode = IosReaderReadingMode.paged
    var paragraphIndent = 2.0
    var paragraphSpacing = 0.0
    var textAlignment = IosReaderTextAlignment.publisher
    var preservePublisherStyles = false
    var smartOptimization = true
    var deduplicateIndent = true
    var indentUnindented = true
    var comicDirection = IosComicDirection.ltr
    var comicSpread = IosComicSpread.single
    var comicFlow = IosComicFlow.paginated
    var comicCoverSingle = false
    var comicPageGap = 0
    var comicZoom = 1.0
    var comicPageWidth = 1350
    var comicImageFit = "width"
    var comicImageVariant = "original"
    var comicPageTurnAnimation = "slide"
    var pdfZoom = 1.0
    var pdfPageWidth = 1350
    var pdfFit = IosPdfFit.page
    var pdfRotation = 0
    var pdfCropMargins = IosPdfCropMargins.off

    init() {}

    func readium(for colorScheme: UIUserInterfaceStyle) -> EPUBPreferences {
        let effectiveTheme = resolvedTheme(for: colorScheme)
        let colors = effectiveTheme.colors
        let columnCount: ColumnCount = switch spreadMode {
        case .auto: .auto
        case .single: .one
        case .double: .two
        }
        let pageMargins: Double = switch pageMargin {
        case .narrow: 0.5
        case .standard: 1.0
        case .wide: 1.5
        }
        let textAlign: TextAlignment? = switch textAlignment {
        case .publisher: nil
        case .left: .start
        case .justify: .justify
        }
        let readiumTheme: Theme = switch effectiveTheme {
        case .warm: .sepia
        case .night, .black: .dark
        case .day, .green: .light
        }
        return EPUBPreferences(
            backgroundColor: ReadiumNavigator.Color(hex: colors.background),
            columnCount: columnCount,
            fontFamily: fontFamily.readium,
            fontSize: Double(fontSize) / 16.0,
            fontWeight: Double(fontWeight) / 400.0,
            letterSpacing: max(0, letterSpacing),
            lineHeight: lineHeight,
            pageMargins: pageMargins,
            paragraphIndent: paragraphIndent,
            paragraphSpacing: paragraphSpacing,
            publisherStyles: preservePublisherStyles,
            scroll: readingMode == .continuousScroll,
            textAlign: textAlign,
            textColor: ReadiumNavigator.Color(hex: colors.foreground),
            theme: readiumTheme
        )
    }

    func resolvedTheme(for colorScheme: UIUserInterfaceStyle) -> IosReaderTheme {
        guard themeMode == .system else { return theme }
        return colorScheme == .dark ? .night : .day
    }
}

extension IosReaderTheme {
    var colors: (background: String, foreground: String, accent: String) {
        switch self {
        case .day: ("#F7F7F4", "#1E293B", "#B45309")
        case .warm: ("#FDF6EA", "#2B2118", "#B45309")
        case .green: ("#E8F0E3", "#203126", "#3F6F4E")
        case .night: ("#0F172A", "#E2E8F0", "#F59E0B")
        case .black: ("#000000", "#F8FAFC", "#F59E0B")
        }
    }
}

final class IosReaderPreferencesStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key: String

    init(serverIdentity: String, userID: String, defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let digest = SHA256.hash(data: Data("\(serverIdentity)\0\(userID)".utf8))
        key = "reader.preferences.v5." + digest.map { String(format: "%02x", $0) }.joined()
    }

    func load() -> IosReaderPreferences {
        guard let data = defaults.data(forKey: key),
              let source = String(data: data, encoding: .utf8),
              let canonical = ReaderPreferencesJson().canonicalizeOrNull(payload: source),
              let decoded = try? IosReaderPreferences(canonicalJSON: canonical)
        else { return IosReaderPreferences() }
        // Do not overwrite an invalid record. Canonicalization succeeds before publication.
        if data != Data(canonical.utf8) { defaults.set(Data(canonical.utf8), forKey: key) }
        return decoded
    }

    @discardableResult
    func save(_ preferences: IosReaderPreferences) -> Bool {
        guard let canonical = try? preferences.canonicalJSON() else { return false }
        let data = Data(canonical.utf8)
        defaults.set(data, forKey: key)
        return defaults.data(forKey: key) == data
    }

    func reset() -> IosReaderPreferences {
        let preferences = IosReaderPreferences()
        save(preferences)
        return preferences
    }

    static func clearNamespace(
        serverIdentity: String,
        userID: String,
        defaults: UserDefaults = .standard
    ) {
        let digest = SHA256.hash(data: Data("\(serverIdentity)\0\(userID)".utf8))
            .map { String(format: "%02x", $0) }.joined()
        defaults.removeObject(forKey: "reader.preferences.v5.\(digest)")
    }

}

struct IosReaderBookmarkRecord: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let resourceKey: String
    let progression: Double?
    let totalProgression: Double?
    let position: Int?
    let exactLocatorJSON: String?
    let label: String
    let percent: Double
    let createdAt: String
}

private struct IosReaderBookmarkState: Codable, Equatable {
    var bookmarks: [IosReaderBookmarkRecord] = []
    var pending: [IosReaderBookmarkRecord]?
}

final class IosReaderBookmarkStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key: String

    init(
        serverIdentity: String,
        userID: String,
        resourceID: String,
        defaults: UserDefaults = .standard
    ) {
        self.defaults = defaults
        let accountDigest = SHA256.hash(data: Data("\(serverIdentity)\0\(userID)".utf8))
            .map { String(format: "%02x", $0) }.joined()
        let resourceDigest = SHA256.hash(data: Data(resourceID.utf8))
            .map { String(format: "%02x", $0) }.joined()
        key = "reader.bookmarks.v2.\(accountDigest).\(resourceDigest)"
    }

    fileprivate func load() -> IosReaderBookmarkState {
        guard let data = defaults.data(forKey: key),
              let state = try? JSONDecoder().decode(IosReaderBookmarkState.self, from: data)
        else { return IosReaderBookmarkState() }
        return state
    }

    @discardableResult
    fileprivate func save(_ state: IosReaderBookmarkState) -> Bool {
        guard let data = try? JSONEncoder().encode(state) else { return false }
        defaults.set(data, forKey: key)
        return defaults.data(forKey: key) == data
    }

    static func clearNamespace(
        serverIdentity: String,
        userID: String,
        defaults: UserDefaults = .standard
    ) {
        let accountDigest = SHA256.hash(data: Data("\(serverIdentity)\0\(userID)".utf8))
            .map { String(format: "%02x", $0) }.joined()
        let prefix = "reader.bookmarks.v2.\(accountDigest)."
        for key in defaults.dictionaryRepresentation().keys where key.hasPrefix(prefix) {
            defaults.removeObject(forKey: key)
        }
    }
}

private final class IosReaderBookmarkRemote: @unchecked Sendable {
    private let port: ErmaoShared.ReaderBookmarkSyncPort
    private let target: ErmaoShared.ReaderBookmarkSyncTarget

    init(port: ErmaoShared.ReaderBookmarkSyncPort, target: ErmaoShared.ReaderBookmarkSyncTarget) {
        self.port = port
        self.target = target
    }

    func load() async throws -> ErmaoShared.ReaderBookmarkSyncResponse {
        try await port.load(target: target)
    }

    func replace(_ bookmarks: [IosReaderBookmarkRecord]) async throws -> ErmaoShared.ReaderBookmarkSyncResponse {
        let outgoing = bookmarks.map(IosReflowableReaderSession.sharedBookmark)
        return try await port.replace(target: target, bookmarks: outgoing)
    }
}

struct IosReaderTocEntry: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let href: String?
    let depth: Int
}

struct IosReaderResumePrompt: Identifiable {
    let id = UUID()
    let capturedAtEpochMillis: Int64
    let percent: Double
    let chapterLabel: String?
    fileprivate let locator: Locator
    fileprivate let expectedEnvelope: ErmaoShared.ReadiumLocatorEnvelope
    fileprivate let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
}

enum IosReaderSessionPhase: Equatable, Sendable {
    case opening
    case reading
    case background
    case closing
    case closed
    case failed(IosReaderFailureCode)
}

struct IosReaderPersistenceGate: Equatable, Sendable {
    struct LocationSignature: Equatable, Sendable {
        let href: String
        let progression: Double?
        let totalProgression: Double?
        let position: Int?

        func representsSamePosition(as other: Self) -> Bool {
            href == other.href &&
                position == other.position &&
                Self.approximatelyEqual(progression, other.progression) &&
                Self.approximatelyEqual(totalProgression, other.totalProgression)
        }

        private static func approximatelyEqual(_ lhs: Double?, _ rhs: Double?) -> Bool {
            switch (lhs, rhs) {
            case (nil, nil): true
            case let (lhs?, rhs?): abs(lhs - rhs) < 0.000_001
            default: false
            }
        }
    }

    private(set) var hasLocalReadingActivity = false
    private var protectedRestoredLocation: LocationSignature?
    private var suppressNextObservation = false
    var canPersistCurrentLocation: Bool { hasLocalReadingActivity && !suppressNextObservation }

    mutating func protectRestoredLocation(_ signature: LocationSignature?) {
        protectedRestoredLocation = signature
    }

    mutating func suppressPreferenceReflow() {
        suppressNextObservation = true
    }

    mutating func beginUserNavigation() {
        protectedRestoredLocation = nil
        suppressNextObservation = false
        hasLocalReadingActivity = true
    }

    mutating func observeLocationChange(_ signature: LocationSignature) -> Bool {
        if suppressNextObservation {
            protectedRestoredLocation = signature
            return false
        }
        if protectedRestoredLocation?.representsSamePosition(as: signature) == true {
            return false
        }
        protectedRestoredLocation = nil
        hasLocalReadingActivity = true
        return true
    }
}

@MainActor
final class IosReflowableReaderSession: NSObject, ObservableObject {
    static let progressSaveDebounceMilliseconds = 500
    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: EPUBNavigatorViewController?
    @Published private(set) var progress = 0.0
    @Published private(set) var chapterTitle: String?
    @Published private(set) var restoreWarning: IosReaderFailureCode?
    @Published private(set) var resumePrompt: IosReaderResumePrompt?
    @Published private(set) var resumeActionFailed = false
    private var returningToResumeAlternative = false
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var tableOfContents: [IosReaderTocEntry] = []
    @Published private(set) var bookmarks: [IosReaderBookmarkRecord] = []
    @Published private(set) var bookmarkSyncPending = false
    @Published var controlsVisible = false
    @Published var activeControlPanel: IosReaderPanel?
    @Published private(set) var preferences: IosReaderPreferences

    let resourceID: String
    let displayTitle: String
    let sourceFormat: ErmaoShared.ReaderSourceFormat

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderProgressSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let runtime: IosReadiumRuntime
    private let mapper: ReadiumSwiftLocatorMapper
    private let deviceIdentity: IosReaderDeviceIdentity
    private let preferencesStore: IosReaderPreferencesStore?
    private let bookmarkStore: IosReaderBookmarkStore?
    private let bookmarkRemote: IosReaderBookmarkRemote?
    private let initialTarget: (any ErmaoShared.ReaderNavigationTarget)?
    private(set) var pendingLaunchTargetPayload: String?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private let namespaceKey: String
    private let bookID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let canonicalNavigation: [IosReaderTocEntry]
    private var publication: Publication?
    private var openedPublication: IosOpenedReadiumPublication?
    private var pendingSave: Task<Void, Never>?
    private var bookmarkSyncTask: Task<Void, Never>?
    private var persistenceGate = IosReaderPersistenceGate()
    private var expectedRestoredEnvelope: ErmaoShared.ReadiumLocatorEnvelope?
    private var didOpen = false
    private let navigationQueue = IosReaderNavigationQueue()
    private var lastHandledTapAt = TimeInterval.zero

    init(
        resourceID: String,
        displayTitle: String,
        sourceFormat: ErmaoShared.ReaderSourceFormat = .epub,
        canonicalNavigation: [IosReaderTocEntry] = [],
        preferences: IosReaderPreferences = IosReaderPreferences(),
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderProgressSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        preferencesStore: IosReaderPreferencesStore? = nil,
        bookmarkStore: IosReaderBookmarkStore? = nil,
        bookmarkSyncPort: ErmaoShared.ReaderBookmarkSyncPort? = nil,
        bookmarkSyncTarget: ErmaoShared.ReaderBookmarkSyncTarget? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4? = nil,
        initialTarget: (any ErmaoShared.ReaderNavigationTarget)? = nil,
        namespaceKey: String = "local",
        bookID: String = "local",
        publishProgressUpdate: @escaping @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void = { _ in },
        runtime: IosReadiumRuntime = IosReadiumRuntime(),
        mapper: ReadiumSwiftLocatorMapper = ReadiumSwiftLocatorMapper(),
        deviceIdentity: IosReaderDeviceIdentity = IosReaderDeviceIdentity()
    ) {
        self.resourceID = resourceID
        self.displayTitle = displayTitle
        self.sourceFormat = sourceFormat
        self.canonicalNavigation = canonicalNavigation
        self.preferences = preferences
        self.managedStore = managedStore
        self.progressStore = progressStore
        self.progressCoordination = progressCoordination
        self.preferencesStore = preferencesStore
        self.bookmarkStore = bookmarkStore
        bookmarkRemote = if let bookmarkSyncPort, let bookmarkSyncTarget {
            IosReaderBookmarkRemote(port: bookmarkSyncPort, target: bookmarkSyncTarget)
        } else {
            nil
        }
        self.remoteSnapshot = remoteSnapshot
        self.initialTarget = initialTarget
        pendingLaunchTargetPayload = initialTarget.map { ErmaoShared.PublicKt.encodeReaderLaunchTarget(target: $0) }
        self.namespaceKey = namespaceKey
        self.bookID = bookID
        self.publishProgressUpdate = publishProgressUpdate
        self.runtime = runtime
        self.mapper = mapper
        self.deviceIdentity = deviceIdentity
        let bookmarkState = bookmarkStore?.load() ?? IosReaderBookmarkState()
        bookmarks = bookmarkState.bookmarks
        bookmarkSyncPending = bookmarkState.pending != nil
    }

    deinit {
        pendingSave?.cancel()
        bookmarkSyncTask?.cancel()
    }

    func open() async {
        guard !didOpen else { return }
        didOpen = true
        phase = .opening
        do {
            let managed = try await managedStore.resolve(resourceID: resourceID, namespace: namespaceKey)
            guard managed.sourceFormat == sourceFormat else { throw IosReaderFailure(code: .corruptFile) }
            let openedPublication = try await runtime.open(managed)
            let openedSource = ErmaoShared.LocalReaderSource(
                resourceId: managed.resourceID, displayTitle: managed.displayTitle,
                format: managed.sourceFormat.readerFormat, bookId: managed.bookID,
                assetId: managed.assetID, sourceFormat: managed.sourceFormat
            )
            let publication = openedPublication.publication
            self.openedPublication = openedPublication
            let saved = try? await progressStore.load(sourceId: resourceID)
            let initial: Locator?
            if let initialTarget {
                guard let target = initialTarget as? ErmaoShared.ReaderNavigationTargetReflowable,
                      RelativeURL(string: target.href) != nil,
                      let locator = await publication.locate(Link(href: target.href))
                else { throw IosReaderFailure(code: .locationRestoreFailed) }
                initial = locator
            } else {
                initial = await restore(local: saved, remote: remoteSnapshot, in: publication, openedSource: openedSource)
            }
            let navigator = try makeIosReflowableNavigator(
                publication: publication, preferences: preferences.readium(for: systemAppearance), location: initial
            )
            let restoredLocation = initial ?? navigator.currentLocation
            persistenceGate.protectRestoredLocation(
                restoredLocation.map { locationSignature($0) }
            )
            self.publication = publication
            installControlNavigator(navigator)
            submittedControlPreferences = preferences.readium(for: systemAppearance)
            progressCoordination?.noticeHandler = { [weak self] snapshot in
                self?.showRemoteProgress(snapshot)
            }
            tableOfContents = await mergedNavigation(publication: publication)
            phase = .reading
            pendingLaunchTargetPayload = nil
            startBookmarkSynchronization()
            if let initial { reflectLocation(initial) }
            progressCoordination?.beginDeferredSynchronization()
        } catch let failure as IosReaderFailure {
            await failOpening(failure)
        } catch {
            await failOpening(IosReaderFailure(code: .engineError, underlyingError: error as NSError))
        }
    }

    func failureDescription(for code: IosReaderFailureCode) -> String { code.localizedDescription }

    private func failOpening(_ failure: IosReaderFailure) async {
        await openedPublication?.close()
        openedPublication = nil
        publication = nil
        phase = .failed(failure.code)
    }

    func goPrevious() async {
        await turnPage(.previous)
    }

    func goNext() async {
        await turnPage(.next)
    }

    func goLeft() async {
        await turnPage(navigator?.presentation.readingProgression == .rtl ? .next : .previous)
    }

    func goRight() async {
        await turnPage(navigator?.presentation.readingProgression == .rtl ? .previous : .next)
    }

    private enum PageTurnDirection { case previous, next }

    private func turnPage(_ direction: PageTurnDirection) async {
        _ = await navigationQueue.enqueue { [weak self] in
            guard let self, self.controlReady, let navigator = self.navigator else { return false }
            if navigator.presentation.scroll {
                let readingOrder = navigator.publication.readingOrder
                guard let href = navigator.currentLocation?.href,
                      let currentIndex = readingOrder.firstIndexWithHREF(href) else { return false }
                let targetIndex = currentIndex + (direction == .previous ? -1 : 1)
                guard readingOrder.indices.contains(targetIndex) else { return false }
                let target = readingOrder[targetIndex]
                // A resource link without a fragment asks Readium to locate its
                // start. Do not go backward to the end and then scroll again.
                return await self.executeLinkNavigation(Link(
                    href: target.url().removingFragment().string, title: target.title
                ))
            }
            self.beginUserNavigation()
            switch direction {
            case .previous: return await navigator.goBackward(options: self.navigationOptions)
            case .next: return await navigator.goForward(options: self.navigationOptions)
            }
        }
    }

    func goToTOCEntry(_ entry: IosReaderTocEntry) async -> Bool {
        guard let href = entry.href else { return false }
        return await navigationQueue.enqueue { [weak self] in
            guard let self else { return false }
            return await self.executeLinkNavigation(Link(href: href, title: entry.title))
        }
    }

    private func executeLinkNavigation(_ link: Link) async -> Bool {
        let canonicalHref = link.href
        guard controlReady, RelativeURL(string: canonicalHref) != nil else { return false }
        if await navigationHrefMatches(canonicalHref) {
            return true
        }
        beginUserNavigation()
        pendingLaunchTargetPayload = ErmaoShared.PublicKt.encodeReaderLaunchTarget(target: ErmaoShared.ReaderNavigationTargetReflowable(href: canonicalHref))
        guard await navigator?.go(to: link, options: navigationOptions) == true else { return false }
        for _ in 0 ..< 30 {
            if await navigationHrefMatches(canonicalHref) {
                pendingLaunchTargetPayload = nil
                return true
            }
            try? await Task.sleep(for: .milliseconds(50))
        }
        return false
    }

    func goToProgression(_ progression: Double) async -> Bool {
        guard let publication, let navigator,
              let locator = await publication.locate(progression: progression)
        else { return false }
        beginUserNavigation()
        guard await navigator.go(to: locator, options: navigationOptions) else { return false }
        return await verifyNavigation(to: locator, in: navigator)
    }

    private func verifyNavigation(to target: Locator, in navigator: EPUBNavigatorViewController) async -> Bool {
        for _ in 0 ..< 40 {
            guard !Task.isCancelled else { return false }
            if let expected = try? mapper.exactEnvelope(from: target),
               let visible = await navigator.firstVisibleElementLocator(),
               let actual = try? mapper.exactEnvelope(from: visible),
               ErmaoShared.PublicKt.compareExactProgressReadiumLocators(expected: expected, recaptured: actual) == .exact {
                return true
            }
            if target.locations.fragments.isEmpty, target.text.highlight == nil,
               navigator.currentLocation?.href.normalized == target.href.normalized {
                if let position = target.locations.position, navigator.viewport?.positions?.contains(position) == true { return true }
                if let progression = target.locations.progression,
                   navigator.viewport?.resources.first(where: { $0.href.isEquivalentTo(target.href) })?.progression.contains(progression) == true { return true }
            }
            do { try await Task.sleep(for: .milliseconds(75)) } catch { return false }
        }
        return false
    }

    private var controlInputToken: InputObservableToken?
    private var undoBookmarks: [IosReaderBookmarkRecord]?

    var canUndoControlBookmark: Bool { undoBookmarks != nil }
    func undoControlBookmark() {
        guard let previous = undoBookmarks else { return }
        commitBookmarkMutation(previous)
        undoBookmarks = nil
    }

    private var navigationOptions: NavigatorGoOptions {
        preferences.pageTurnAnimation == "slide" && !UIAccessibility.isReduceMotionEnabled ? .animated : .none
    }

    private var systemAppearance: UIUserInterfaceStyle = .light
    private var submittedControlPreferences: EPUBPreferences?

    func refreshSystemAppearance(_ style: UIUserInterfaceStyle) {
        systemAppearance = style
        guard preferences.themeMode == .system, navigator != nil,
              submittedControlPreferences != preferences.readium(for: style) else { return }
        if !executeControlPreferences(preferences) {
            presentationError = .engineError
        }
    }

    private func installControlNavigator(_ navigator: EPUBNavigatorViewController) {
        navigator.delegate = self
        controlInputToken = navigator.addObserver(.drag(onStart: { [weak self] _ in
            guard let self, self.activeControlPanel == nil, self.navigator?.currentSelection == nil else { return false }
            self.beginUserNavigation()
            return false
        }))
        self.navigator = navigator
    }

    func applyControlPreferences(_ updated: IosReaderPreferences) async -> Bool {
        executeControlPreferences(updated)
    }

    private func executeControlPreferences(_ updated: IosReaderPreferences) -> Bool {
        guard let navigator, controlReady, canApplyControlPreferences(updated),
              preferencesStore?.save(updated) != false else { return false }
        let native = updated.readium(for: systemAppearance)
        if native != submittedControlPreferences {
            pendingSave?.cancel()
            persistenceGate.suppressPreferenceReflow()
            // Readium owns reflow and location retention. A changed first-visible
            // paragraph after pagination is not a failed settings submission.
            navigator.submitPreferences(native)
            submittedControlPreferences = native
        }
        preferences = updated
        return true
    }

    func isCurrentLocationBookmarked() async -> Bool {
        guard let locator = await navigator?.firstVisibleElementLocator() else { return false }
        return bookmarks.contains { record in
            record.resourceKey == locator.href.string &&
                abs((record.progression ?? 0) - (locator.locations.progression ?? 0)) < 0.0001
        }
    }

    var currentBookmarkActive: Bool {
        guard let locator = navigator?.currentLocation else { return false }
        return bookmarks.contains { record in
            record.resourceKey == locator.href.string &&
                abs((record.progression ?? 0) - (locator.locations.progression ?? 0)) < 0.0001
        }
    }

    func toggleCurrentBookmark() async {
        guard let locator = await navigator?.firstVisibleElementLocator(),
              !(await isUnreadablePage(locator))
        else { return }
        let exactJSON: String
        do { exactJSON = try locator.jsonString() }
        catch {
            presentationError = .persistenceFailed
            return
        }
        let id = bookmarkID(locator)
        let next: [IosReaderBookmarkRecord]
        if bookmarks.contains(where: { $0.id == id }) {
            next = bookmarks.filter { $0.id != id }
        } else {
            next = bookmarks + [IosReaderBookmarkRecord(
                id: id,
                resourceKey: locator.href.string,
                progression: locator.locations.progression,
                totalProgression: locator.locations.totalProgression,
                position: locator.locations.position,
                exactLocatorJSON: exactJSON,
                label: locator.title ?? chapterTitle ?? displayTitle,
                percent: min(100, max(0, (locator.locations.totalProgression ?? progress) * 100)),
                createdAt: ISO8601DateFormatter().string(from: Date())
            )]
        }
        undoBookmarks = bookmarks
        commitBookmarkMutation(next)
    }

    func removeBookmark(id: String) {
        guard bookmarks.contains(where: { $0.id == id }) else { return }
        undoBookmarks = bookmarks
        commitBookmarkMutation(bookmarks.filter { $0.id != id })
    }

    @discardableResult
    func goToBookmark(id: String) async -> Bool {
        guard let record = bookmarks.first(where: { $0.id == id }),
              let publication, let navigator
        else { return false }
        if let exactJSON = record.exactLocatorJSON,
           let exact = try? Locator(jsonString: exactJSON),
           publication.linkWithHREF(exact.href) != nil {
            beginUserNavigation()
            guard await navigator.go(to: exact, options: navigationOptions) else { return false }
            return await verifyNavigation(to: exact, in: navigator)
        }
        guard let href = RelativeURL(string: record.resourceKey),
              let link = publication.linkWithHREF(href),
              let base = await publication.locate(link)
        else { return false }
        let target = base.copy(locations: { locations in
            locations.progression = record.progression
            locations.position = record.position
        })
        beginUserNavigation()
        guard await navigator.go(to: target, options: navigationOptions) else { return false }
        return await verifyNavigation(to: target, in: navigator)
    }

    func dismissRestoreWarning() {
        restoreWarning = nil
    }

    func dismissResumePrompt() {
        resumePrompt = nil
        resumeActionFailed = false
    }

    func returnToResumeAlternative() async {
        guard let prompt = resumePrompt, let navigator else { return }
        resumeActionFailed = false
        returningToResumeAlternative = true
        defer { returningToResumeAlternative = false }
        beginUserNavigation(dismissResumePrompt: false)
        persistenceGate.suppressPreferenceReflow()
        _ = await navigator.go(to: prompt.locator, options: navigationOptions)
        try? await Task.sleep(for: .milliseconds(120))
        if let recaptured = await navigator.firstVisibleElementLocator(),
           publication != nil,
           let actual = try? mapper.exactEnvelope(from: recaptured),
           ErmaoShared.PublicKt.compareExactProgressReadiumLocators(
               expected: prompt.expectedEnvelope,
               recaptured: actual
           ) == .exact {
            if let snapshot = prompt.remoteSnapshot,
               let progress = try? makeProgress(from: recaptured) {
                try? await progressCoordination?.acceptVerifiedRemote(progress: progress, snapshot: snapshot)
            }
            dismissResumePrompt()
            return
        }
        resumeActionFailed = true
    }

    func verifyRestoredLocationAfterPresentation() async {
        guard let expected = expectedRestoredEnvelope,
              let navigator,
              publication != nil
        else { return }
        expectedRestoredEnvelope = nil
        try? await Task.sleep(for: .milliseconds(160))
        guard let recaptured = await navigator.firstVisibleElementLocator(),
              let actual = try? mapper.exactEnvelope(from: recaptured)
        else { return }
        let match = ErmaoShared.PublicKt.compareExactProgressReadiumLocators(expected: expected, recaptured: actual)
        if match == ErmaoShared.ExactBlockMatch.resourcemismatch {
            restoreWarning = .locationRestoreFailed
        }
    }

    func dismissPresentationError() {
        presentationError = nil
    }

    func showControls() {
        controlsVisible = true
    }

    func handleTap(at point: CGPoint, width: CGFloat) {
        guard activeControlPanel == nil, navigator?.currentSelection == nil else { return }
        let now = Date.timeIntervalSinceReferenceDate
        guard now - lastHandledTapAt >= 0.15 else { return }
        lastHandledTapAt = now
        guard preferences.tapZones != .disabled else {
            controlsVisible.toggle()
            return
        }
        switch point.x / max(1, width) {
        case ..<0.3:
            Task {
                if preferences.tapZones == .reversed { await goRight() } else { await goLeft() }
            }
        case 0.7...:
            Task {
                if preferences.tapZones == .reversed { await goLeft() } else { await goRight() }
            }
        default:
            controlsVisible.toggle()
        }
    }

    func enterBackground() async {
        phase = .background
        await flushProgress()
        try? await progressStore.retryPendingUpload()
        try? await progressStore.awaitPendingUpload()
    }

    func becomeActive() {
        if phase == .background { phase = .reading }
        Task {
            if let progressCoordination {
                await progressCoordination.recoverPendingAndCheckRemote()
            } else {
                try? await progressStore.retryPendingUpload()
                try? await progressStore.awaitPendingUpload()
            }
        }
    }

    func close() async throws {
        guard phase != .closed else { return }
        phase = .closing
        pendingSave?.cancel()
        bookmarkSyncTask?.cancel()
        try? await persistCurrentLocation(waitForSynchronization: false)
        progressCoordination?.close()
        navigator?.delegate = nil
        if let controlInputToken { navigator?.removeObserver(controlInputToken) }
        controlInputToken = nil
        navigator = nil
        await openedPublication?.close()
        openedPublication = nil
        publication = nil
        phase = .closed
    }

    func flushProgress() async {
        pendingSave?.cancel()
        try? await persistCurrentLocation()
    }

    private func mergedNavigation(publication: Publication) async -> [IosReaderTocEntry] {
        let publicationLinks: [Link]
        switch await publication.tableOfContents() {
        case let .success(links): publicationLinks = links
        case .failure: publicationLinks = []
        }
        let publicationEntries = publicationLinks.enumerated().map { index, link in
            let title = link.title?.trimmingCharacters(in: .whitespacesAndNewlines)
            return IosReaderTocEntry(
                id: "publication:\(index)",
                title: title?.isEmpty == false ? title ?? String(index + 1) : String(index + 1),
                href: String(describing: link.href),
                depth: 0
            )
        }
        guard !canonicalNavigation.isEmpty else { return publicationEntries }
        let canonicalHrefs = Set(canonicalNavigation.map(\.href))
        return canonicalNavigation + publicationEntries.filter { !canonicalHrefs.contains($0.href) }
    }

    private func restore(
        local: ErmaoShared.ReaderProgress?,
        remote: ErmaoShared.ReaderProgressSnapshotV4?,
        in publication: Publication,
        openedSource: any ErmaoShared.ReaderSource
    ) async -> Locator? {
        let decision = ErmaoShared.PublicKt.decideReaderResume(
            localProgress: local,
            remoteSnapshot: remote,
            openedSource: openedSource
        )
        if let alternative = decision.alternative {
            resumePrompt = makeResumePrompt(alternative, publication: publication)
        }
        guard let selected = decision.selected else {
            if local != nil || remote != nil { restoreWarning = .locationRestoreFailed }
            return nil
        }
        if let selectedLocal = selected.localProgress {
            return await restoreLocal(selectedLocal)
        }
        if let selectedRemote = selected.remoteSnapshot {
            return await restoreRemote(selectedRemote, in: publication)
        }
        return nil
    }

    private func showRemoteProgress(_ snapshot: ErmaoShared.ReaderProgressSnapshotV4?) {
        guard let snapshot, let publication else {
            if progressCoordination?.remoteSnapshot == nil { dismissResumePrompt() }
            return
        }
        resumePrompt = makeResumePrompt(snapshot, publication: publication)
        resumeActionFailed = false
    }

    private func makeResumePrompt(
        _ snapshot: ErmaoShared.ReaderProgressSnapshotV4,
        publication: Publication
    ) -> IosReaderResumePrompt? {
        guard let location = snapshot.locator as? ErmaoShared.ReflowablePublicationLocation,
              let locator = try? mapper.exactLocator(from: location.readiumEnvelope, publication: publication)
        else { return nil }
        return IosReaderResumePrompt(
            capturedAtEpochMillis: snapshot.effectiveCapturedAtEpochMillis,
            percent: snapshot.displayPercent,
            chapterLabel: locator.title,
            locator: locator,
            expectedEnvelope: location.readiumEnvelope,
            remoteSnapshot: snapshot
        )
    }

    private func makeResumePrompt(
        _ target: ErmaoShared.ReaderResumeTarget,
        publication: Publication
    ) -> IosReaderResumePrompt? {
        let locator: Locator?
        let envelope: ErmaoShared.ReadiumLocatorEnvelope?
        if let local = target.localProgress,
           let location = local.location as? ErmaoShared.ReflowReaderLocation {
            locator = try? mapper.exactLocator(from: location)
            envelope = ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location)
        } else if let remote = target.remoteSnapshot {
            let reflowable = remote.locator as? ErmaoShared.ReflowablePublicationLocation
            locator = reflowable.flatMap {
                try? mapper.exactLocator(from: $0.readiumEnvelope, publication: publication)
            }
            envelope = reflowable?.readiumEnvelope
        } else {
            return nil
        }
        guard let locator, let envelope else { return nil }
        return IosReaderResumePrompt(
            capturedAtEpochMillis: target.capturedAtEpochMillis,
            percent: target.displayPercent,
            chapterLabel: locator.title,
            locator: locator,
            expectedEnvelope: envelope,
            remoteSnapshot: target.remoteSnapshot
        )
    }

    private func restoreLocal(_ saved: ErmaoShared.ReaderProgress) async -> Locator? {
        guard let location = saved.location as? ErmaoShared.ReflowReaderLocation else { return nil }
        guard let envelope = ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location),
              let exact = try? mapper.exactLocator(from: location)
        else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        expectedRestoredEnvelope = envelope
        return exact
    }

    private func restoreRemote(
        _ snapshot: ErmaoShared.ReaderProgressSnapshotV4,
        in publication: Publication
    ) async -> Locator? {
        guard let reflowable = snapshot.locator as? ErmaoShared.ReflowablePublicationLocation,
              let exact = try? mapper.exactLocator(
                  from: reflowable.readiumEnvelope,
                  publication: publication
              )
        else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        expectedRestoredEnvelope = reflowable.readiumEnvelope
        return exact
    }

    private func navigationHrefMatches(_ expected: String) async -> Bool {
        guard let navigator else { return false }
        let locator: Locator?
        if expected.contains("#") {
            locator = await navigator.firstVisibleElementLocator()
        } else {
            locator = navigator.currentLocation
        }
        guard let locator else { return false }
        return ErmaoShared.PublicKt.matchesReaderNavigationHref(
            currentHref: locator.href.normalized.string, expectedHref: expected,
            fragments: Set(locator.locations.fragments), cssSelector: locator.locations["cssSelector"]?.string
        )
    }

    private func commitBookmarkMutation(_ next: [IosReaderBookmarkRecord]) {
        guard let bookmarkStore else { return }
        let ordered = next.sorted(by: Self.bookmarkOrder)
        guard bookmarkStore.save(IosReaderBookmarkState(bookmarks: ordered, pending: ordered)) else {
            presentationError = .persistenceFailed
            return
        }
        bookmarks = ordered
        bookmarkSyncPending = true
        bookmarkSyncTask?.cancel()
        bookmarkSyncTask = Task { [weak self] in await self?.flushBookmarkOutbox() }
    }

    private func startBookmarkSynchronization() {
        guard bookmarkStore != nil, bookmarkRemote != nil else { return }
        bookmarkSyncTask?.cancel()
        bookmarkSyncTask = Task { [weak self] in
            await self?.refreshBookmarksFromServer()
            guard !Task.isCancelled else { return }
            await self?.flushBookmarkOutbox()
        }
    }

    private func refreshBookmarksFromServer() async {
        guard let bookmarkStore, let bookmarkRemote else { return }
        guard let response = try? await bookmarkRemote.load(),
              response.succeeded
        else { return }
        let local = bookmarkStore.load()
        guard local.pending == nil else { return }
        var byID = Dictionary(uniqueKeysWithValues: local.bookmarks.map { ($0.id, $0) })
        response.bookmarks.forEach { remote in
            if byID[remote.id] == nil { byID[remote.id] = Self.localBookmark(remote) }
        }
        let merged = byID.values.sorted(by: Self.bookmarkOrder)
        bookmarkStore.save(IosReaderBookmarkState(bookmarks: merged, pending: nil))
        bookmarks = merged
    }

    private func flushBookmarkOutbox() async {
        guard let bookmarkStore, let bookmarkRemote else { return }
        while !Task.isCancelled {
            let before = bookmarkStore.load()
            guard let pending = before.pending else { return }
            guard let response = try? await bookmarkRemote.replace(pending),
                  response.succeeded else { return }
            let latest = bookmarkStore.load()
            guard latest.pending == pending else { continue }
            let localByID = Dictionary(uniqueKeysWithValues: latest.bookmarks.map { ($0.id, $0) })
            let acknowledged = response.bookmarks.map { localByID[$0.id] ?? Self.localBookmark($0) }
                .sorted(by: Self.bookmarkOrder)
            bookmarkStore.save(IosReaderBookmarkState(bookmarks: acknowledged, pending: nil))
            bookmarks = acknowledged
            bookmarkSyncPending = false
            return
        }
    }

    private func bookmarkID(_ locator: Locator) -> String {
        let progression = resolvedTotalProgression(locator) ?? 0
        var wire = String(format: "%.4f", (progression * 10_000).rounded() / 10_000)
        while wire.last == "0" { wire.removeLast() }
        if wire.last == "." { wire.removeLast() }
        if wire.isEmpty { wire = "0" }
        return "reflowable:epub:position:\(locator.href.string):\(wire)"
    }

    nonisolated fileprivate static func sharedBookmark(_ value: IosReaderBookmarkRecord) -> ErmaoShared.ReaderBookmark {
        ErmaoShared.ReaderBookmark(
            id: value.id,
            location: ErmaoShared.ReaderBookmarkLocation.companion.reflow(
                resourceKey: value.resourceKey,
                progression: value.progression.map(KotlinDouble.init(double:))
            ),
            label: value.label,
            percent: value.percent,
            createdAt: value.createdAt
        )
    }

    private static func localBookmark(_ value: ErmaoShared.ReaderBookmark) -> IosReaderBookmarkRecord {
        IosReaderBookmarkRecord(
            id: value.id,
            resourceKey: value.location.resourceKey,
            progression: value.location.progression?.doubleValue,
            totalProgression: nil,
            position: nil,
            exactLocatorJSON: nil,
            label: value.label,
            percent: value.percent,
            createdAt: value.createdAt
        )
    }

    private static func bookmarkOrder(_ lhs: IosReaderBookmarkRecord, _ rhs: IosReaderBookmarkRecord) -> Bool {
        if lhs.percent != rhs.percent { return lhs.percent < rhs.percent }
        if lhs.createdAt != rhs.createdAt { return lhs.createdAt < rhs.createdAt }
        return lhs.id < rhs.id
    }

    private func locationChanged(_ locator: Locator) {
        reflectLocation(locator)
        guard persistenceGate.observeLocationChange(locationSignature(locator)) else { return }
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(Self.progressSaveDebounceMilliseconds))
            guard !Task.isCancelled else { return }
            await self?.flushProgress()
        }
    }

    private func reflectLocation(_ locator: Locator) {
        progress = resolvedTotalProgression(locator)
            ?? remoteSnapshot.map { min(1, max(0, $0.displayPercent / 100)) }
            ?? progress
        chapterTitle = locator.title
    }

    private func resolvedTotalProgression(_ locator: Locator) -> Double? {
        ErmaoShared.PublicKt.resolveReflowableTotalProgressionFromNavigation(
            orderedResourceHrefs: canonicalNavigation.map { $0.href ?? "" },
            resourceHref: locator.href.normalized.string,
            resourceProgression: locator.locations.progression.map(KotlinDouble.init(double:)),
            totalProgression: locator.locations.totalProgression.map(KotlinDouble.init(double:))
        )?.doubleValue
    }

    private func beginUserNavigation(dismissResumePrompt: Bool = true) {
        persistenceGate.beginUserNavigation()
    }

    private func locationSignature(_ locator: Locator) -> IosReaderPersistenceGate.LocationSignature {
        IosReaderPersistenceGate.LocationSignature(
            href: locator.href.normalized.string,
            progression: locator.locations.progression,
            totalProgression: locator.locations.totalProgression,
            position: locator.locations.position
        )
    }

    private func persistCurrentLocation(waitForSynchronization: Bool = true) async throws {
        guard persistenceGate.canPersistCurrentLocation,
              let navigator
        else { return }
        guard let locator = await navigator.firstVisibleElementLocator() else { return }
        guard !(await isUnreadablePage(locator)) else { return }
        let progress = try makeProgress(from: locator)
        guard progress.location is ErmaoShared.ReflowReaderLocation else { return }
        try await progressStore.save(progress: progress)
        if waitForSynchronization {
            await progressCoordination?.refreshAfterSave()
        }
        if progressCoordination?.remoteSnapshot == nil { dismissResumePrompt() }
        publishProgressUpdate(ErmaoShared.PublicKt.createReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            bookId: bookID,
            resourceId: resourceID,
            percent: min(100, max(0, self.progress * 100)),
            progress: progress,
            chapterTitle: chapterTitle
        ))
    }

    private func makeProgress(from locator: Locator) throws -> ErmaoShared.ReaderProgress {
        guard publication != nil else { throw IosReaderFailure(code: .persistenceFailed) }
        let location = try mapper.sharedLocation(from: locator)
        return ErmaoShared.ReaderProgress(
            resourceId: resourceID,
            location: location,
            updatedAtEpochMillis: Int64(Date().timeIntervalSince1970 * 1_000),
            deviceId: deviceIdentity.stableDeviceId(),
            percent: KotlinDouble(double: min(100, max(0, self.progress * 100)))
        )
    }

    private func isUnreadablePage(_ locator: Locator) async -> Bool {
        guard let publication,
              let link = publication.linkWithHREF(locator.href),
              let resource = publication.get(link),
              case let .success(content) = await resource.read()
        else { return false }
        return content.range(
            of: Data("data-shuku-resource-error=\"RESOURCE_UNREADABLE\"".utf8)
        ) != nil
    }
}

extension IosReflowableReaderSession: EPUBNavigatorDelegate {
    func navigator(_ navigator: Navigator, locationDidChange locator: Locator) {
        locationChanged(locator)
    }

    func navigator(_ navigator: Navigator, presentError error: NavigatorError) {
        presentationError = presentationError ?? .engineError
    }

    func navigator(_ navigator: Navigator, presentExternalURL url: URL) {
        guard ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return }
        UIApplication.shared.open(url)
    }

    func navigator(_ navigator: VisualNavigator, didTapAt point: CGPoint) {
        handleTap(
            at: point,
            width: self.navigator?.view.bounds.width ?? UIScreen.main.bounds.width
        )
    }

    func navigator(_ navigator: VisualNavigator, didPressKey event: KeyEvent) {
        if event.key == .escape, activeControlPanel != nil { activeControlPanel = nil; return }
        guard activeControlPanel == nil, self.navigator?.currentSelection == nil else { return }
        guard preferences.keyboardPageTurn else {
            if event.key == .escape { showControls() }
            return
        }
        switch event.key {
        case .arrowLeft: Task { await goLeft() }
        case .arrowRight: Task { await goRight() }
        case .pageUp: Task { await goPrevious() }
        case .pageDown, .space: Task { await goNext() }
        case .escape: showControls()
        default: break
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
