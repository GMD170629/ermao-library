import Combine
import Foundation
@preconcurrency import ErmaoShared
import ReadiumNavigator
import ReadiumShared
import UIKit

enum IosReaderTheme: String, CaseIterable, Identifiable, Sendable {
    case paper
    case night
    case system
    var id: Self { self }
}

enum IosReaderReadingMode: String, CaseIterable, Identifiable, Sendable {
    case paged
    case continuousScroll
    var id: Self { self }
}

struct IosReaderPreferences: Equatable, Sendable {
    var fontSize = 1.0
    var fontFamily: String?
    var lineHeight = 1.2
    var letterSpacing = 0.0
    var pageMargins = 1.0
    var theme = IosReaderTheme.paper
    var readingMode = IosReaderReadingMode.paged
    var publisherStyles = true
    var justifyText = false

    init() {}

    init(shared: ErmaoShared.ReaderPreferences) {
        fontSize = shared.fontSize
        fontFamily = shared.fontFamily
        lineHeight = shared.lineHeight
        letterSpacing = shared.letterSpacing
        pageMargins = shared.pageMargins
        theme = switch shared.theme.name {
        case "Night": .night
        case "System": .system
        default: .paper
        }
        readingMode = shared.readingMode.name == "ContinuousScroll" ? .continuousScroll : .paged
        publisherStyles = shared.publisherStyles
        justifyText = shared.textAlignment.name == "Justify"
    }

    var readium: EPUBPreferences {
        EPUBPreferences(
            fontFamily: fontFamily.map(FontFamily.init(rawValue:)),
            fontSize: fontSize,
            letterSpacing: max(0, letterSpacing),
            lineHeight: lineHeight,
            pageMargins: pageMargins,
            publisherStyles: publisherStyles,
            scroll: readingMode == .continuousScroll,
            textAlign: justifyText ? .justify : nil,
            theme: readiumTheme
        )
    }

    private var readiumTheme: Theme {
        switch theme {
        case .paper: .sepia
        case .night: .dark
        case .system: UITraitCollection.current.userInterfaceStyle == .dark ? .dark : .sepia
        }
    }
}

struct IosReaderTocEntry: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let href: String
    let depth: Int
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
final class IosEpubReaderSession: NSObject, ObservableObject {
    static let progressSaveDebounceMilliseconds = 500
    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: EPUBNavigatorViewController?
    @Published private(set) var progress = 0.0
    @Published private(set) var chapterTitle: String?
    @Published private(set) var restoreWarning: IosReaderFailureCode?
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var tableOfContents: [IosReaderTocEntry] = []
    @Published var controlsVisible = true
    @Published var preferences: IosReaderPreferences

    let sourceID: String
    let displayTitle: String

    private let managedStore: IosManagedPublicationStore
    private let progressStore: IosReaderProgressStore
    private let runtime: IosReadiumRuntime
    private let mapper: ReadiumSwiftLocatorMapper
    private let deviceIdentity: IosReaderDeviceIdentity
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private var publication: Publication?
    private var managedPublication: IosManagedPublication?
    private var pendingSave: Task<Void, Never>?
    private var persistenceGate = IosReaderPersistenceGate()
    private var didOpen = false

    init(
        sourceID: String,
        displayTitle: String,
        preferences: IosReaderPreferences = IosReaderPreferences(),
        managedStore: IosManagedPublicationStore,
        progressStore: IosReaderProgressStore,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4? = nil,
        runtime: IosReadiumRuntime = IosReadiumRuntime(),
        mapper: ReadiumSwiftLocatorMapper = ReadiumSwiftLocatorMapper(),
        deviceIdentity: IosReaderDeviceIdentity = IosReaderDeviceIdentity()
    ) {
        self.sourceID = sourceID
        self.displayTitle = displayTitle
        self.preferences = preferences
        self.managedStore = managedStore
        self.progressStore = progressStore
        self.remoteSnapshot = remoteSnapshot
        self.runtime = runtime
        self.mapper = mapper
        self.deviceIdentity = deviceIdentity
    }

    deinit {
        pendingSave?.cancel()
    }

    func open() async {
        guard !didOpen else { return }
        didOpen = true
        phase = .opening
        do {
            let managed = try await managedStore.resolve(sourceID: sourceID)
            let publication = try await runtime.open(managed)
            let saved = try await progressStore.load(sourceId: sourceID)
            let initial = await restore(
                local: saved,
                remote: remoteSnapshot,
                in: publication,
                managed: managed
            )
            var config = EPUBNavigatorViewController.Configuration(
                preferences: preferences.readium,
                editingActions: []
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
            tableOfContents = await loadTableOfContents(publication)
            phase = .reading
            if let initial { reflectLocation(initial) }
        } catch let failure as IosReaderFailure {
            phase = .failed(failure.code)
        } catch {
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
              let link = publication.linkWithHREF(entry.href)
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
        navigator?.submitPreferences(preferences.readium)
    }

    func dismissRestoreWarning() {
        restoreWarning = nil
    }

    func dismissPresentationError() {
        presentationError = nil
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
    }

    func close() async throws {
        guard phase != .closed else { return }
        phase = .closing
        pendingSave?.cancel()
        do {
            try await persistCurrentLocation()
            try? await progressStore.awaitPendingUpload()
        } catch {
            phase = .reading
            throw error
        }
        navigator?.delegate = nil
        navigator = nil
        publication?.close()
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
            format: .epub,
            contentFingerprint: managed.fingerprint.shared,
            workId: managed.workID,
            volumeId: managed.volumeID
        )
        let plan = ErmaoShared.PublicKt.planReaderProgressRestore(
            localProgress: local,
            remoteSnapshot: remote,
            openedSource: openedSource
        )
        if let selectedLocal = plan.localProgress {
            if plan.usesLocalExact {
                return await restoreLocal(
                    selectedLocal,
                    in: publication,
                    fingerprint: managed.fingerprint
                )
            }
            guard let location = selectedLocal.location as? ErmaoShared.ReflowReaderLocation,
                  let percent = location.totalProgression?.doubleValue
                    ?? selectedLocal.percent.map { $0.doubleValue / 100 }
                    ?? location.progression?.doubleValue
            else { return nil }
            restoreWarning = .locationRestoreFailed
            return await publication.locate(progression: percent)
        }
        if let selectedRemote = plan.remoteSnapshot {
            let mayUseStructuredAnchors = plan.candidates.contains {
                !($0 is ErmaoShared.ReaderRestoreTotalProgression)
            }
            return await restoreRemote(
                selectedRemote,
                mayUseStructuredAnchors: mayUseStructuredAnchors,
                in: publication
            )
        }
        return nil
    }

    private func restoreLocal(
        _ saved: ErmaoShared.ReaderProgress,
        in publication: Publication,
        fingerprint: IosContentFingerprint
    ) async -> Locator? {
        guard let location = saved.location as? ErmaoShared.ReflowReaderLocation else { return nil }
        let sameFingerprint = IosContentFingerprint(shared: location.contentFingerprint) == fingerprint
        if sameFingerprint {
            if let exact = try? mapper.exactLocator(from: location) { return exact }
            if let resource = await mapper.resourceProgressionLocator(from: location, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return resource
            }
            if let quote = await mapper.quotedTextLocator(from: location, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return quote
            }
            if let position = await mapper.positionLocator(from: location, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return position
            }
        }
        let percent = location.totalProgression?.doubleValue
            ?? saved.percent.map { $0.doubleValue / 100 }
            ?? location.progression?.doubleValue
        if let percent,
           let approximate = await publication.locate(progression: percent) {
            restoreWarning = .locationRestoreFailed
            return approximate
        }
        restoreWarning = .locationRestoreFailed
        return nil
    }

    private func restoreRemote(
        _ snapshot: ErmaoShared.ReaderProgressSnapshotV4,
        mayUseStructuredAnchors: Bool,
        in publication: Publication
    ) async -> Locator? {
        if mayUseStructuredAnchors, let anchor = snapshot.anchor {
            if let engine = try? mapper.publicEngineLocator(from: anchor, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return engine
            }
            if let resource = await mapper.resourceProgressionLocator(from: anchor, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return resource
            }
            if let quote = await mapper.quotedTextLocator(from: anchor, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return quote
            }
            if let position = await mapper.positionLocator(from: anchor, publication: publication) {
                restoreWarning = .locationRestoreFailed
                return position
            }
        }
        let percent = min(100, max(0, snapshot.percent)) / 100
        if let approximate = await publication.locate(progression: percent) {
            restoreWarning = .locationRestoreFailed
            return approximate
        }
        restoreWarning = .locationRestoreFailed
        return nil
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

    private func beginUserNavigation() {
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
              let locator = navigator?.currentLocation,
              let managedPublication
        else { return }
        let location = try mapper.sharedLocation(from: locator, fingerprint: managedPublication.fingerprint)
        let progress = ErmaoShared.ReaderProgress(
            sourceId: sourceID,
            location: location,
            updatedAtEpochMillis: Int64(Date().timeIntervalSince1970 * 1_000),
            deviceId: deviceIdentity.stableDeviceId(),
            percent: KotlinDouble(double: min(100, max(0, self.progress * 100)))
        )
        try await progressStore.save(progress: progress)
    }
}

extension IosEpubReaderSession: EPUBNavigatorDelegate {
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
        controlsVisible.toggle()
    }

    func navigator(_ navigator: VisualNavigator, didPressKey event: KeyEvent) {
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
