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
    case pingfang, heiti, songti, yahei, kaiti
    var id: Self { self }

    var readium: FontFamily {
        switch self {
        case .pingfang, .heiti, .yahei: FontFamily(rawValue: "Shuku Sans")
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

struct IosReaderPreferences: Codable, Equatable, Sendable {
    var schemaVersion = 3
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
    var allowPublisherColors = false
    var allowPublisherFonts = false
    var smartOptimization = true
    var deduplicateIndent = true
    var indentUnindented = true

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
            backgroundColor: allowPublisherColors ? nil : ReadiumNavigator.Color(hex: colors.background),
            columnCount: columnCount,
            fontFamily: allowPublisherFonts ? nil : fontFamily.readium,
            fontSize: Double(fontSize) / 18.0,
            fontWeight: Double(fontWeight) / 400.0,
            letterSpacing: max(0, letterSpacing),
            lineHeight: preservePublisherStyles ? nil : lineHeight,
            pageMargins: pageMargins,
            paragraphIndent: paragraphIndent,
            paragraphSpacing: paragraphSpacing,
            publisherStyles: false,
            scroll: readingMode == .continuousScroll,
            textAlign: textAlign,
            textColor: allowPublisherColors ? nil : ReadiumNavigator.Color(hex: colors.foreground),
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

struct IosReaderCapabilities: Sendable {
    let bookmarks = true
    let annotations = false
    let customFonts = true
    let negativeLetterSpacing = false
    let pageWidth = false
    let swipeToggle = false
    let pageTurnAnimation = false
    let publisherStyleParts = false
    let smartOptimization = false
    let volumeKeyPageTurn = false
}

final class IosReaderPreferencesStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key: String

    init(serverIdentity: String, userID: String, defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let digest = SHA256.hash(data: Data("\(serverIdentity)\0\(userID)".utf8))
        key = "reader.preferences.v3." + digest.map { String(format: "%02x", $0) }.joined()
    }

    func load() -> IosReaderPreferences {
        guard let data = defaults.data(forKey: key) else { return IosReaderPreferences() }
        if let decoded = try? JSONDecoder().decode(IosReaderPreferences.self, from: data),
           decoded.schemaVersion == 3 {
            return decoded
        }
        return migrateLegacy(data)
    }

    func save(_ preferences: IosReaderPreferences) {
        guard let data = try? JSONEncoder().encode(preferences) else { return }
        defaults.set(data, forKey: key)
    }

    func reset() -> IosReaderPreferences {
        let preferences = IosReaderPreferences()
        save(preferences)
        return preferences
    }

    private func migrateLegacy(_ data: Data) -> IosReaderPreferences {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return IosReaderPreferences()
        }
        var result = IosReaderPreferences()
        switch object["theme"] as? String {
        case "paper": result.theme = .warm
        case "night": result.theme = .night
        case "system": result.themeMode = .system
        default: break
        }
        if let value = object["fontSize"] as? Double {
            result.fontSize = min(30, max(14, Int((value * 18).rounded())))
        }
        if let value = object["lineHeight"] as? Double {
            result.lineHeight = min(2.4, max(1.4, value))
        }
        save(result)
        return result
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
        volumeID: String,
        contentFingerprint: String,
        defaults: UserDefaults = .standard
    ) {
        self.defaults = defaults
        let namespace = "\(serverIdentity)\0\(userID)\0\(volumeID)\0\(contentFingerprint)"
        let digest = SHA256.hash(data: Data(namespace.utf8))
        key = "reader.bookmarks.v1." + digest.map { String(format: "%02x", $0) }.joined()
    }

    fileprivate func load() -> IosReaderBookmarkState {
        guard let data = defaults.data(forKey: key),
              let state = try? JSONDecoder().decode(IosReaderBookmarkState.self, from: data)
        else { return IosReaderBookmarkState() }
        return state
    }

    fileprivate func save(_ state: IosReaderBookmarkState) {
        guard let data = try? JSONEncoder().encode(state) else { return }
        defaults.set(data, forKey: key)
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
    let href: String
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
            suppressNextObservation = false
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
    @Published private(set) var startupConflict: IosReaderStartupConflict?
    @Published private(set) var startupCancelled = false
    @Published private(set) var startupActionFailed = false
    private var returningToResumeAlternative = false
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var tableOfContents: [IosReaderTocEntry] = []
    @Published private(set) var bookmarks: [IosReaderBookmarkRecord] = []
    @Published private(set) var bookmarkSyncPending = false
    @Published var controlsVisible = false
    @Published var preferences: IosReaderPreferences

    let sourceID: String
    let displayTitle: String
    let sourceFormat: ErmaoShared.ReaderSourceFormat
    let capabilities = IosReaderCapabilities()

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderProgressSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let runtime: IosReadiumRuntime
    private let mapper: ReadiumSwiftLocatorMapper
    private let deviceIdentity: IosReaderDeviceIdentity
    private let preferencesStore: IosReaderPreferencesStore?
    private let bookmarkStore: IosReaderBookmarkStore?
    private let bookmarkRemote: IosReaderBookmarkRemote?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private let namespaceKey: String
    private let workID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private var publication: Publication?
    private var openedPublication: IosOpenedReadiumPublication?
    private var managedPublication: IosManagedPublication?
    private var pendingSave: Task<Void, Never>?
    private var bookmarkSyncTask: Task<Void, Never>?
    private var persistenceGate = IosReaderPersistenceGate()
    private var expectedRestoredEnvelope: ErmaoShared.ReadiumLocatorEnvelope?
    private var didOpen = false

    init(
        sourceID: String,
        displayTitle: String,
        sourceFormat: ErmaoShared.ReaderSourceFormat = .epub,
        preferences: IosReaderPreferences = IosReaderPreferences(),
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderProgressSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        preferencesStore: IosReaderPreferencesStore? = nil,
        bookmarkStore: IosReaderBookmarkStore? = nil,
        bookmarkSyncPort: ErmaoShared.ReaderBookmarkSyncPort? = nil,
        bookmarkSyncTarget: ErmaoShared.ReaderBookmarkSyncTarget? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4? = nil,
        startupConflict: IosReaderStartupConflict? = nil,
        namespaceKey: String = "local",
        workID: String = "local",
        publishProgressUpdate: @escaping @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void = { _ in },
        runtime: IosReadiumRuntime = IosReadiumRuntime(),
        mapper: ReadiumSwiftLocatorMapper = ReadiumSwiftLocatorMapper(),
        deviceIdentity: IosReaderDeviceIdentity = IosReaderDeviceIdentity()
    ) {
        self.sourceID = sourceID
        self.displayTitle = displayTitle
        self.sourceFormat = sourceFormat
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
        self.startupConflict = startupConflict
        self.namespaceKey = namespaceKey
        self.workID = workID
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
            let managed = try await managedStore.resolve(sourceID: sourceID)
            guard managed.sourceFormat == sourceFormat else {
                throw IosReaderFailure(code: .corruptFile)
            }
            let openedPublication = try await runtime.open(managed)
            let publication = openedPublication.publication
            self.openedPublication = openedPublication
            let saved = try await progressStore.load(sourceId: sourceID)
            let initial = await restore(
                local: saved,
                remote: remoteSnapshot,
                in: publication,
                managed: managed
            )
            var config = EPUBNavigatorViewController.Configuration(
                preferences: preferences.readium(for: UITraitCollection.current.userInterfaceStyle),
                editingActions: [],
                fontFamilyDeclarations: customFontFamilyDeclarations()
            )
            config.disablePageTurnsWhileScrolling = preferences.readingMode == .continuousScroll
            let navigator = try EPUBNavigatorViewController(
                publication: publication,
                initialLocation: initial,
                config: config
            )
            let restoredLocation = initial ?? navigator.currentLocation
            persistenceGate.protectRestoredLocation(
                restoredLocation.map { locationSignature($0) }
            )
            navigator.delegate = self
            self.managedPublication = managed
            self.publication = publication
            self.navigator = navigator
            progressCoordination?.noticeHandler = { [weak self] snapshot in
                self?.showRemoteProgress(snapshot)
            }
            tableOfContents = await loadTableOfContents(publication)
            phase = .reading
            startBookmarkSynchronization()
            if let initial { reflectLocation(initial) }
            await progressCoordination?.checkForRemoteProgress()
        } catch let failure as IosReaderFailure {
            await openedPublication?.close()
            openedPublication = nil
            publication = nil
            phase = .failed(failure.code)
        } catch {
            await openedPublication?.close()
            openedPublication = nil
            publication = nil
            phase = .failed(.engineError)
        }
    }

    func goPrevious() async {
        beginUserNavigation()
        _ = await navigator?.goBackward(options: .animated)
    }

    func goNext() async {
        beginUserNavigation()
        _ = await navigator?.goForward(options: .animated)
    }

    func goLeft() async {
        beginUserNavigation()
        _ = await navigator?.goLeft(options: .animated)
    }

    func goRight() async {
        beginUserNavigation()
        _ = await navigator?.goRight(options: .animated)
    }

    func goToTOCEntry(_ entry: IosReaderTocEntry) async {
        guard let publication,
              let href = RelativeURL(string: entry.href),
              let link = publication.linkWithHREF(href)
        else { return }
        beginUserNavigation()
        _ = await navigator?.go(to: link, options: .animated)
    }

    func goToProgression(_ progression: Double) async {
        guard let publication,
              let locator = await publication.locate(progression: progression)
        else { return }
        beginUserNavigation()
        _ = await navigator?.go(to: locator, options: .animated)
    }

    func applyPreferences() {
        persistenceGate.suppressPreferenceReflow()
        navigator?.submitPreferences(
            preferences.readium(for: UITraitCollection.current.userInterfaceStyle)
        )
        preferencesStore?.save(preferences)
    }

    func resetPreferences() {
        preferences = preferencesStore?.reset() ?? IosReaderPreferences()
        applyPreferences()
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
              !(await isUnreadablePage(locator)),
              let exactJSON = locator.jsonString
        else { return }
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
        commitBookmarkMutation(next)
    }

    func removeBookmark(id: String) {
        guard bookmarks.contains(where: { $0.id == id }) else { return }
        commitBookmarkMutation(bookmarks.filter { $0.id != id })
    }

    func goToBookmark(id: String) async {
        guard let record = bookmarks.first(where: { $0.id == id }),
              let publication
        else { return }
        if let exactJSON = record.exactLocatorJSON,
           let exact = try? Locator(jsonString: exactJSON),
           publication.linkWithHREF(exact.href) != nil {
            beginUserNavigation()
            _ = await navigator?.go(to: exact, options: .animated)
            return
        }
        guard let href = RelativeURL(string: record.resourceKey),
              let link = publication.linkWithHREF(href),
              let base = await publication.locate(link)
        else { return }
        let target = base.copy(locations: { locations in
            locations.progression = record.progression
            locations.position = record.position
        })
        beginUserNavigation()
        _ = await navigator?.go(to: target, options: .animated)
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
        _ = await navigator.go(to: prompt.locator, options: .animated)
        try? await Task.sleep(for: .milliseconds(120))
        if let recaptured = await navigator.firstVisibleElementLocator(),
           let managedPublication,
           let actual = try? mapper.exactEnvelope(from: recaptured, fingerprint: managedPublication.fingerprint),
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
              let managedPublication
        else { return }
        expectedRestoredEnvelope = nil
        try? await Task.sleep(for: .milliseconds(160))
        guard let recaptured = await navigator.firstVisibleElementLocator(),
              let actual = try? mapper.exactEnvelope(from: recaptured, fingerprint: managedPublication.fingerprint)
        else { return }
        let match = ErmaoShared.PublicKt.compareExactProgressReadiumLocators(expected: expected, recaptured: actual)
        if match == ErmaoShared.ExactBlockMatch.resourcemismatch {
            restoreWarning = .locationRestoreFailed
        }
    }

    func dismissPresentationError() {
        presentationError = nil
    }

    func continueStartupAtLocalPosition() async {
        guard let conflict = startupConflict,
              let location = conflict.progress.location as? ErmaoShared.ReflowReaderLocation,
              let expected = ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location),
              let locator = try? mapper.exactLocator(from: location),
              let navigator
        else { startupActionFailed = true; return }
        persistenceGate.suppressPreferenceReflow()
        _ = await navigator.go(to: locator, options: .animated)
        try? await Task.sleep(for: .milliseconds(160))
        guard let recaptured = await navigator.firstVisibleElementLocator(),
              let managedPublication,
              let actual = try? mapper.exactEnvelope(from: recaptured, fingerprint: managedPublication.fingerprint),
              ErmaoShared.PublicKt.compareExactProgressReadiumLocators(expected: expected, recaptured: actual) == .exact
        else { startupActionFailed = true; return }
        do {
            try await progressCoordination?.continueStartupWithLocal(
                progress: conflict.progress,
                serverRevision: conflict.server.revision
            )
            startupConflict = nil
        } catch {
            startupActionFailed = true
        }
    }

    func useCloudStartupPosition() async {
        guard let conflict = startupConflict,
              let expected = conflict.server.locator as? ErmaoShared.ReflowablePublicationLocation,
              let navigator,
              let recaptured = await navigator.firstVisibleElementLocator(),
              let managedPublication,
              let actual = try? mapper.exactEnvelope(from: recaptured, fingerprint: managedPublication.fingerprint),
              ErmaoShared.PublicKt.compareExactProgressReadiumLocators(
                  expected: expected.readiumEnvelope,
                  recaptured: actual
              ) == .exact,
              let progress = try? makeProgress(from: recaptured)
        else { startupActionFailed = true; return }
        do {
            try await progressCoordination?.useServerForStartup(conflict)
            try await progressCoordination?.acceptVerifiedRemote(progress: progress, snapshot: conflict.server)
            startupConflict = nil
        } catch {
            startupActionFailed = true
        }
    }

    func cancelStartupConflict() {
        startupCancelled = true
    }

    func showControls() {
        controlsVisible = true
    }

    func enterBackground() async {
        phase = .background
        await flushProgress()
        try? await progressStore.awaitPendingUpload()
    }

    func becomeActive() {
        if phase == .background { phase = .reading }
        Task {
            try? await progressStore.retryPendingUpload()
            await progressCoordination?.checkForRemoteProgress()
        }
    }

    func close() async throws {
        guard phase != .closed else { return }
        phase = .closing
        pendingSave?.cancel()
        bookmarkSyncTask?.cancel()
        do {
            try await persistCurrentLocation()
            try? await progressStore.awaitPendingUpload()
        } catch {
            phase = .reading
            throw error
        }
        navigator?.delegate = nil
        navigator = nil
        await openedPublication?.close()
        openedPublication = nil
        publication = nil
        phase = .closed
    }

    func flushProgress() async {
        pendingSave?.cancel()
        do {
            try await persistCurrentLocation()
        } catch {
            presentationError = .persistenceFailed
        }
    }

    private func restore(
        local: ErmaoShared.ReaderProgress?,
        remote: ErmaoShared.ReaderProgressSnapshotV4?,
        in publication: Publication,
        managed: IosManagedPublication
    ) async -> Locator? {
        let openedSource = ErmaoShared.LocalReaderSource(
            sourceId: managed.sourceID,
            displayTitle: managed.displayTitle,
            format: managed.sourceFormat.readerFormat,
            contentFingerprint: managed.fingerprint.shared,
            workId: managed.workID,
            volumeId: managed.volumeID,
            sourceFormat: managed.sourceFormat
        )
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

    private func loadTableOfContents(_ publication: Publication) async -> [IosReaderTocEntry] {
        guard case let .success(links) = await publication.tableOfContents() else { return [] }
        var index = 0
        func flatten(_ links: [Link], depth: Int) -> [IosReaderTocEntry] {
            links.flatMap { link in
                index += 1
                let current = IosReaderTocEntry(
                    id: "\(index):\(link.href)",
                    title: link.title?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
                        ?? String(localized: "reader.toc.untitled"),
                    href: link.href,
                    depth: depth
                )
                return [current] + flatten(link.children, depth: depth + 1)
            }
        }
        return flatten(links, depth: 0)
    }

    private func customFontFamilyDeclarations() -> [AnyHTMLFontFamilyDeclaration] {
        guard let resourcesURL = Bundle.main.resourceURL,
              let resources = FileURL(url: resourcesURL)
        else { return [] }
        let sans = resources.appendingPath("reader/sans.woff2", isDirectory: false)
        let songti = resources.appendingPath("reader/songti.woff2", isDirectory: false)
        let kaiti = resources.appendingPath("reader/kaiti.woff2", isDirectory: false)
        return [
            CSSFontFamilyDeclaration(
                fontFamily: FontFamily(rawValue: "Shuku Sans"),
                fontFaces: [CSSFontFace(file: sans, style: .normal, weight: .variable(100 ... 900))]
            ).eraseToAnyHTMLFontFamilyDeclaration(),
            CSSFontFamilyDeclaration(
                fontFamily: FontFamily(rawValue: "Shuku Songti"),
                fontFaces: [CSSFontFace(file: songti, style: .normal, weight: .variable(100 ... 900))]
            ).eraseToAnyHTMLFontFamilyDeclaration(),
            CSSFontFamilyDeclaration(
                fontFamily: FontFamily(rawValue: "Shuku Kaiti"),
                fontFaces: [CSSFontFace(file: kaiti, style: .normal, weight: .standard(.normal))]
            ).eraseToAnyHTMLFontFamilyDeclaration(),
        ]
    }

    private func commitBookmarkMutation(_ next: [IosReaderBookmarkRecord]) {
        guard let bookmarkStore else { return }
        let ordered = next.sorted(by: Self.bookmarkOrder)
        bookmarkStore.save(IosReaderBookmarkState(bookmarks: ordered, pending: ordered))
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
        let progression = locator.locations.totalProgression ?? locator.locations.progression ?? 0
        var wire = String(format: "%.4f", (progression * 10_000).rounded() / 10_000)
        while wire.last == "0" { wire.removeLast() }
        if wire.last == "." { wire.removeLast() }
        if wire.isEmpty { wire = "0" }
        return "reflowable:epub:position:\(locator.href.string):\(wire)"
    }

    nonisolated fileprivate static func sharedBookmark(_ value: IosReaderBookmarkRecord) -> ErmaoShared.ReaderBookmark {
        ErmaoShared.ReaderBookmark(
            id: value.id,
            location: ErmaoShared.ReaderBookmarkLocation(
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
        progress = locator.locations.totalProgression ?? locator.locations.progression ?? 0
        chapterTitle = locator.title
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

    private func persistCurrentLocation() async throws {
        guard persistenceGate.hasLocalReadingActivity,
              let navigator
        else { return }
        guard let locator = await navigator.firstVisibleElementLocator() else { return }
        guard !(await isUnreadablePage(locator)) else { return }
        let progress = try makeProgress(from: locator)
        guard progress.location is ErmaoShared.ReflowReaderLocation else { return }
        try await progressStore.save(progress: progress)
        await progressCoordination?.refreshAfterSave()
        if progressCoordination?.remoteSnapshot == nil { dismissResumePrompt() }
        publishProgressUpdate(ErmaoShared.PublicKt.createReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            workId: workID,
            volumeId: sourceID,
            percent: min(100, max(0, self.progress * 100)),
            progress: progress,
            chapterTitle: chapterTitle
        ))
    }

    private func makeProgress(from locator: Locator) throws -> ErmaoShared.ReaderProgress {
        guard let managedPublication else { throw IosReaderFailure(code: .persistenceFailed) }
        let location = try mapper.sharedLocation(from: locator, fingerprint: managedPublication.fingerprint)
        return ErmaoShared.ReaderProgress(
            sourceId: sourceID,
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
        presentationError = .engineError
    }

    func navigator(_ navigator: Navigator, presentExternalURL url: URL) {
        guard ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return }
        UIApplication.shared.open(url)
    }

    func navigator(_ navigator: VisualNavigator, didTapAt point: CGPoint) {
        guard preferences.tapZones != .disabled else {
            controlsVisible.toggle()
            return
        }
        let width = max(1, self.navigator?.view.bounds.width ?? UIScreen.main.bounds.width)
        switch point.x / width {
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

    func navigator(_ navigator: VisualNavigator, didPressKey event: KeyEvent) {
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
