import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import UIKit

@MainActor
final class IosPdfReaderSession: NSObject, ObservableObject {
    private let navigationQueue = IosReaderNavigationQueue()
    static let progressSaveDebounceMilliseconds = 500

    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: PDFNavigatorViewController?
    @Published private(set) var pdfiumNavigator: IosPdfiumNavigatorViewController?
    @Published private(set) var pageIndex = 0
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var restoreWarning: IosReaderFailureCode?
    @Published private(set) var remoteProgressSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    @Published private(set) var tableOfContents: [IosReaderTocEntry] = []
    @Published var controlsVisible = false
    @Published var activeControlPanel: IosReaderPanel?
    @Published private(set) var preferences: IosReaderPreferences

    let resourceID: String
    let displayTitle: String
    @Published private(set) var canonicalPageCount: Int
    private let pageTitleHints: [String]
    private let remoteSource: ErmaoShared.RemoteByteRangeReaderSource?
    private let rangeCache: ErmaoShared.PdfRangeMemory?
    private let rangeServer: (any ErmaoShared.PdfRangeServerPort)?
    private let preferencesStore: IosReaderPreferencesStore

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderProgressSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let initialTarget: (any ErmaoShared.ReaderNavigationTarget)?
    private(set) var pendingLaunchTargetPayload: String?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private let namespaceKey: String
    private let bookID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let deviceIdentity: IosReaderDeviceIdentity
    private var managedPublication: IosManagedPublication?
    private var openedPublication: IosOpenedReadiumPublication?
    private var positions: [Locator] = []
    private var tapNavigation: IosPdfTapNavigation?
    private var pendingSave: Task<Void, Never>?
    private var expectedRestoredPage: Int?
    private var hasReadingActivity = false
    private var suppressNextPersistence = false
    private var didOpen = false

    init(
        resourceID: String,
        displayTitle: String,
        pageCountHint: Int?,
        pageTitleHints: [String],
        preferences: IosReaderPreferences,
        preferencesStore: IosReaderPreferencesStore,
        remoteSource: ErmaoShared.RemoteByteRangeReaderSource? = nil,
        rangeCache: ErmaoShared.PdfRangeMemory? = nil,
        rangeServer: (any ErmaoShared.PdfRangeServerPort)? = nil,
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderProgressSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?,
        initialTarget: (any ErmaoShared.ReaderNavigationTarget)? = nil,
        namespaceKey: String,
        bookID: String,
        publishProgressUpdate: @escaping @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void,
        deviceIdentity: IosReaderDeviceIdentity
    ) {
        self.resourceID = resourceID
        self.displayTitle = displayTitle
        canonicalPageCount = max(1, pageCountHint ?? pageTitleHints.count)
        self.pageTitleHints = pageTitleHints
        self.preferences = preferences
        self.preferencesStore = preferencesStore
        self.remoteSource = remoteSource
        self.rangeCache = rangeCache
        self.rangeServer = rangeServer
        self.managedStore = managedStore
        self.progressStore = progressStore
        self.progressCoordination = progressCoordination
        self.remoteSnapshot = remoteSnapshot
        self.initialTarget = initialTarget
        pendingLaunchTargetPayload = initialTarget.map { ErmaoShared.PublicKt.encodeReaderLaunchTarget(target: $0) }
        self.namespaceKey = namespaceKey
        self.bookID = bookID
        self.publishProgressUpdate = publishProgressUpdate
        self.deviceIdentity = deviceIdentity
    }

    deinit {
        pendingSave?.cancel()
    }

    var pageLabel: String { "\(pageIndex + 1) / \(canonicalPageCount)" }
    var progress: Double {
        canonicalPageCount <= 1 ? 1 : Double(pageIndex) / Double(canonicalPageCount - 1)
    }

    func open() async {
        guard !didOpen else { return }
        didOpen = true
        do {
            if let remoteSource {
                try await openRemote(remoteSource)
                return
            }
            let managed = try await managedStore.resolve(
                resourceID: resourceID,
                namespace: namespaceKey
            )
            guard managed.sourceFormat == .pdf else { throw IosReaderFailure(code: .corruptFile) }
            let opened = try await IosReadiumRuntime().open(managed)
            managedPublication = managed
            openedPublication = opened
            let parsedPositions: [Locator]
            switch await opened.publication.positions() {
            case let .success(value): parsedPositions = value
            case .failure: throw IosReaderFailure(code: .parseFailed)
            }
            guard !parsedPositions.isEmpty else {
                throw IosReaderFailure(code: .corruptFile)
            }
            canonicalPageCount = parsedPositions.count
            positions = parsedPositions
            tableOfContents = normalizedPageTitles(count: parsedPositions.count).enumerated().map { index, title in
                IosReaderTocEntry(
                    id: "pdf:\(index)",
                    title: title,
                    href: String(describing: parsedPositions[index].href),
                    depth: 0
                )
            }
            let local = try? await progressStore.load(sourceId: resourceID)
            let openedSource = ErmaoShared.LocalReaderSource(
                resourceId: managed.resourceID,
                displayTitle: managed.displayTitle,
                format: managed.sourceFormat.readerFormat,
                bookId: managed.bookID,
                assetId: managed.assetID,
                sourceFormat: managed.sourceFormat
            )
            let initialPage = try restorePage(local: local, remote: remoteSnapshot, source: openedSource)
            let navigator = try PDFNavigatorViewController(
                publication: opened.publication,
                initialLocation: initialPage.map { parsedPositions[$0] },
                config: PDFNavigatorViewController.Configuration(
                    preferences: PDFPreferences(scroll: false, spread: .never)
                )
            )
            navigator.delegate = self
            tapNavigation = IosPdfTapNavigation(navigator: navigator) { [weak self] point in
                self?.handleTap(at: point)
            }
            self.navigator = navigator
            progressCoordination?.noticeHandler = { [weak self] snapshot in
                guard snapshot?.locator is ErmaoShared.PdfPublicationLocation else { return }
                self?.remoteProgressSnapshot = snapshot
            }
            pageIndex = initialPage ?? 0
            phase = .reading
            pendingLaunchTargetPayload = nil
            await progressCoordination?.checkForRemoteProgress()
        } catch let failure as IosReaderFailure {
            await releaseRuntime()
            phase = .failed(failure.code)
        } catch {
            await releaseRuntime()
            phase = .failed(.engineError)
        }
    }

    func goPrevious() async {
        if let pdfiumNavigator { _ = pdfiumNavigator.goPrevious() }
        else { _ = await navigator?.goBackward(options: .animated) }
    }
    func goNext() async {
        if let pdfiumNavigator { _ = pdfiumNavigator.goNext() }
        else { _ = await navigator?.goForward(options: .animated) }
    }

    func goToPage(_ index: Int) async -> Bool {
        await navigationQueue.enqueue { [weak self] in
            guard let self else { return false }
            return await self.executePageNavigation(index)
        }
    }

    private func executePageNavigation(_ index: Int) async -> Bool {
        guard index >= 0, index < canonicalPageCount else { return false }
        pendingLaunchTargetPayload = ErmaoShared.PublicKt.encodeReaderLaunchTarget(target: ErmaoShared.ReaderNavigationTargetPdf(pageIndex: Int32(index)))
        if let pdfiumNavigator {
            if pageIndex == index { return true }
            guard pdfiumNavigator.goToPage(index) else { return false }
            await verifyCurrentPage(expected: index)
            if pageIndex == index { pendingLaunchTargetPayload = nil }
            return pageIndex == index
        }
        guard positions.indices.contains(index), let navigator else { return false }
        if pageIndex == index { return true }
        guard await navigator.go(to: positions[index], options: .animated) else { return false }
        await verifyCurrentPage(expected: index)
        return pageIndex == index
    }

    func goToTOCEntry(_ entry: IosReaderTocEntry) async -> Bool {
        if entry.id.hasPrefix("pdf:"),
           let index = Int(entry.id.dropFirst("pdf:".count)) {
            return await goToPage(index)
        }
        guard let publication = openedPublication?.publication,
              let canonicalHref = entry.href,
              let href = RelativeURL(string: canonicalHref),
              let link = publication.linkWithHREF(href),
              let navigator
        else { return false }
        return await navigator.go(to: link, options: .animated)
    }

    func zoomIn() {
        if let pdfiumNavigator { pdfiumNavigator.zoomIn(); return }
        guard let view = navigator?.pdfView else { return }
        view.scaleFactor = min(view.maxScaleFactor, view.scaleFactor * 1.25)
    }

    func zoomOut() {
        if let pdfiumNavigator { pdfiumNavigator.zoomOut(); return }
        guard let view = navigator?.pdfView else { return }
        view.scaleFactor = max(view.minScaleFactor, view.scaleFactor / 1.25)
    }

    func zoomToFit() {
        if let pdfiumNavigator { pdfiumNavigator.zoomToFit(); return }
        guard let navigator else { return }
        navigator.submitPreferences(PDFPreferences(scroll: false, spread: .never))
    }

    func applyPreferences(_ updated: IosReaderPreferences) async -> Bool {
        guard canApplyControlPreferences(updated) else { return false }
        guard preferencesStore.save(updated) else { return false }
        let zoomChanged = preferences.pdfZoom != updated.pdfZoom
        preferences = updated
        if zoomChanged { applySavedZoom() }
        return true
    }

    private func applySavedZoom() {
        if let pdfiumNavigator { pdfiumNavigator.setZoom(preferences.pdfZoom); return }
        guard let view = navigator?.pdfView else { return }
        let fittedScale = view.scaleFactorForSizeToFit
        guard fittedScale > 0 else { return }
        view.minScaleFactor = min(view.minScaleFactor, fittedScale * 0.6)
        view.maxScaleFactor = max(view.maxScaleFactor, fittedScale * 2.4)
        view.scaleFactor = fittedScale * preferences.pdfZoom
    }

    func verifyRestoredLocationAfterPresentation() async {
        applySavedZoom()
        guard let expected = expectedRestoredPage else { return }
        expectedRestoredPage = nil
        try? await Task.sleep(for: .milliseconds(180))
        await verifyCurrentPage(expected: expected)
    }

    func showControls() { controlsVisible = true }
    func dismissPresentationError() { presentationError = nil }
    func dismissRestoreWarning() { restoreWarning = nil }
    func dismissRemoteProgressNotice() {
        progressCoordination?.dismissRemoteNotice()
        remoteProgressSnapshot = nil
    }

    func goToRemoteProgress() async {
        guard let snapshot = remoteProgressSnapshot,
              let remote = snapshot.locator as? ErmaoShared.PdfPublicationLocation,
              (0 ..< canonicalPageCount).contains(Int(remote.pageIndex))
        else { return }
        let expected = Int(remote.pageIndex)
        suppressNextPersistence = true
        _ = await goToPage(expected)
        guard pageIndex == expected else { suppressNextPersistence = false; return }
        guard let progress = makeProgress(index: expected) else { return }
        try? await progressCoordination?.acceptVerifiedRemote(progress: progress, snapshot: snapshot)
        remoteProgressSnapshot = nil
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
        try? await persistCurrentPage()
        try? await progressStore.retryPendingUpload()
        try? await progressStore.awaitPendingUpload()
        await releaseRuntime()
        phase = .closed
    }

    func flushProgress() async {
        pendingSave?.cancel()
        try? await persistCurrentPage()
    }

    private func restorePage(
        local: ErmaoShared.ReaderProgress?,
        remote: ErmaoShared.ReaderProgressSnapshotV4?,
        source: ErmaoShared.ReaderSource
    ) throws -> Int? {
        if let initialTarget {
            guard let target = initialTarget as? ErmaoShared.ReaderNavigationTargetPdf,
                  (0 ..< canonicalPageCount).contains(Int(target.pageIndex))
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
            expectedRestoredPage = Int(target.pageIndex)
            return Int(target.pageIndex)
        }
        let decision = ErmaoShared.PublicKt.decideReaderResume(
            localProgress: local,
            remoteSnapshot: remote,
            openedSource: source
        )
        guard let selected = decision.selected else {
            if local != nil || remote != nil { restoreWarning = .locationRestoreFailed }
            return nil
        }
        let index: Int
        if let value = selected.localProgress?.location as? ErmaoShared.PdfReaderLocation {
            guard IosPdfPositionPolicy.accepts(pageProgression: value.pageProgression)
            else {
                restoreWarning = .locationRestoreFailed
                return nil
            }
            index = Int(value.pageIndex)
        } else if let value = selected.remoteSnapshot?.locator as? ErmaoShared.PdfPublicationLocation {
            guard IosPdfPositionPolicy.accepts(pageProgression: value.pageProgression) else {
                restoreWarning = .locationRestoreFailed
                return nil
            }
            index = Int(value.pageIndex)
        } else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        guard (0 ..< canonicalPageCount).contains(index) else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        expectedRestoredPage = index
        return index
    }

    private func pageIndex(for locator: Locator) -> Int? {
        guard let position = locator.locations.position else { return nil }
        return IosPdfPositionPolicy.pageIndex(position: position, pageCount: canonicalPageCount)
    }

    private func verifyCurrentPage(expected: Int) async {
        try? await Task.sleep(for: .milliseconds(120))
        if let pdfiumNavigator {
            guard pdfiumNavigator.pageIndex == expected else {
                restoreWarning = .locationRestoreFailed
                return
            }
            pageIndex = expected
            return
        }
        guard let locator = navigator?.currentLocation,
              pageIndex(for: locator) == expected
        else {
            restoreWarning = .locationRestoreFailed
            return
        }
        pageIndex = expected
    }

    private func locationChanged(_ locator: Locator) {
        guard let index = pageIndex(for: locator) else {
            presentationError = .engineError
            return
        }
        pageIndex = index
        if suppressNextPersistence {
            suppressNextPersistence = false
            return
        }
        hasReadingActivity = true
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(Self.progressSaveDebounceMilliseconds))
            guard !Task.isCancelled else { return }
            await self?.flushProgress()
        }
    }

    private func persistCurrentPage() async throws {
        guard hasReadingActivity,
              phase == .reading || phase == .background || phase == .closing
        else { return }
        let index: Int
        if let pdfiumNavigator {
            index = pdfiumNavigator.pageIndex
        } else {
            guard let locator = navigator?.currentLocation,
                  let readiumIndex = pageIndex(for: locator) else { return }
            index = readiumIndex
        }
        guard let progress = makeProgress(index: index) else { return }
        let percent = progress.percent?.doubleValue ?? 0
        try await progressStore.save(progress: progress)
        await progressCoordination?.refreshAfterSave()
        remoteProgressSnapshot = progressCoordination?.remoteSnapshot
        publishProgressUpdate(ErmaoShared.PublicKt.createReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            bookId: bookID,
            resourceId: resourceID,
            percent: percent,
            progress: progress,
            chapterTitle: nil
        ))
    }

    private func makeProgress(index: Int) -> ErmaoShared.ReaderProgress? {
        let location = ErmaoShared.PdfReaderLocation(
            pageIndex: Int32(index),
            pageProgression: 0,
            engineLocator: nil
        )
        let timestamp = Int64(Date().timeIntervalSince1970 * 1_000)
        let percent = canonicalPageCount <= 1 ? 100 : Double(index) / Double(canonicalPageCount - 1) * 100
        return ErmaoShared.ReaderProgress(
            resourceId: resourceID,
            location: location,
            updatedAtEpochMillis: timestamp,
            deviceId: deviceIdentity.stableDeviceId(),
            percent: KotlinDouble(double: percent)
        )
    }

    private func releaseRuntime() async {
        defer { rangeCache?.clear() }
        tapNavigation?.close()
        tapNavigation = nil
        navigator?.delegate = nil
        navigator = nil
        pdfiumNavigator?.close()
        pdfiumNavigator = nil
        // Releasing the navigator removes its endpoint. Releasing this session-owned
        // GCD server then stops the loopback-only listener.
        await openedPublication?.close()
        openedPublication = nil
        managedPublication = nil
        positions = []
        tableOfContents = []
    }

    private func openRemote(_ source: ErmaoShared.RemoteByteRangeReaderSource) async throws {
        guard let rangeCache, let rangeServer else {
            throw IosReaderFailure(code: .engineError)
        }
        let document = try await IosPdfiumDocument.open(
            source: source,
            cache: rangeCache,
            server: rangeServer
        )
        guard document.pageCount > 0 else {
            document.close()
            throw IosReaderFailure(code: .pdfInvalid)
        }
        canonicalPageCount = document.pageCount
        tableOfContents = normalizedPageTitles(count: document.pageCount).enumerated().map { index, title in
            IosReaderTocEntry(
                id: "pdf:\(index)",
                title: title,
                href: "pdf-page:\(index)",
                depth: 0
            )
        }
        let local = try? await progressStore.load(sourceId: resourceID)
        let initialPage = try restorePage(local: local, remote: remoteSnapshot, source: source) ?? 0
        let navigator = IosPdfiumNavigatorViewController(
            document: document,
            initialPageIndex: initialPage
        )
        navigator.onPageChanged = { [weak self] index in self?.pdfiumLocationChanged(index) }
        navigator.onFailure = { [weak self] code in self?.presentationError = code }
        navigator.onCenterTap = { [weak self] in self?.controlsVisible.toggle() }
        pdfiumNavigator = navigator
        progressCoordination?.noticeHandler = { [weak self] snapshot in
            guard snapshot?.locator is ErmaoShared.PdfPublicationLocation else { return }
            self?.remoteProgressSnapshot = snapshot
        }
        expectedRestoredPage = initialPage
        pageIndex = initialPage
        phase = .reading
        pendingLaunchTargetPayload = nil
        await progressCoordination?.checkForRemoteProgress()
    }

    private func normalizedPageTitles(count: Int) -> [String] {
        (0 ..< count).map { index in
            guard pageTitleHints.indices.contains(index) else { return String(index + 1) }
            let title = pageTitleHints[index].trimmingCharacters(in: .whitespacesAndNewlines)
            return title.isEmpty ? String(index + 1) : title
        }
    }

    private func pdfiumLocationChanged(_ index: Int) {
        guard (0 ..< canonicalPageCount).contains(index) else {
            presentationError = .pdfPageLoadFailed
            return
        }
        pageIndex = index
        if suppressNextPersistence {
            suppressNextPersistence = false
            return
        }
        hasReadingActivity = true
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(Self.progressSaveDebounceMilliseconds))
            guard !Task.isCancelled else { return }
            await self?.flushProgress()
        }
    }
}

enum IosPdfPositionPolicy {
    static func pageIndex(position: Int, pageCount: Int) -> Int? {
        guard pageCount > 0, position > 0 else { return nil }
        let index = position - 1
        return index < pageCount ? index : nil
    }

    static func accepts(pageProgression: Double) -> Bool {
        pageProgression == 0
    }
}

// The pinned Readium delegate predates concurrency annotations; PDF view setup
// is invoked from its UIKit main-thread view lifecycle.
extension IosPdfReaderSession: @preconcurrency PDFNavigatorDelegate {
    func navigator(_ navigator: Navigator, locationDidChange locator: Locator) {
        locationChanged(locator)
        applySavedZoom()
    }
    func navigator(_ navigator: PDFNavigatorViewController, setupPDFView pdfView: PDFDocumentView) {
        applySavedZoom()
    }
    func navigator(_ navigator: Navigator, presentError error: NavigatorError) { presentationError = .engineError }
    func navigator(_ navigator: Navigator, presentExternalURL url: URL) {}
    func navigator(_ navigator: VisualNavigator, didTapAt point: CGPoint) {
        // The owned recognizer also receives taps over PDFKit's selectable text views.
        // Do not process the same touch a second time through Readium's recognizer.
        guard tapNavigation == nil else { return }
        handleTap(at: point)
    }
    private func handleTap(at point: CGPoint) {
        let width = max(1, self.navigator?.view.bounds.width ?? UIScreen.main.bounds.width)
        routeControlTap(fraction: point.x / width)
    }
    func navigator(_ navigator: VisualNavigator, didPressKey event: KeyEvent) {
        if event.key == .escape { activeControlPanel = nil; controlsVisible = true; return }
        guard activeControlPanel == nil, preferences.keyboardPageTurn else { return }
        switch event.key {
        case .arrowLeft, .pageUp: Task { await goPrevious() }
        case .arrowRight, .pageDown, .space: Task { await goNext() }
        default: break
        }
    }
    func navigator(_ navigator: VisualNavigator, didReleaseKey event: KeyEvent) {}
    func navigator(_ navigator: SelectableNavigator, shouldShowMenuForSelection selection: Selection) -> Bool { false }
    func navigator(_ navigator: SelectableNavigator, didSelect selection: Selection) {}
    func navigator(_ navigator: SelectableNavigator, didFailToCreateSelection error: Error) {}
}

/// PDFKit's text interaction can consume Readium's lower-priority single tap on iOS.
/// Own navigation at the native container while preserving selection, links and zoom.
@MainActor
private final class IosPdfTapNavigation: NSObject, UIGestureRecognizerDelegate {
    private weak var navigator: PDFNavigatorViewController?
    private var recognizer: UITapGestureRecognizer?
    private let onTap: (CGPoint) -> Void

    init(navigator: PDFNavigatorViewController, onTap: @escaping (CGPoint) -> Void) {
        self.navigator = navigator
        self.onTap = onTap
        super.init()
        let recognizer = UITapGestureRecognizer(target: self, action: #selector(didTap(_:)))
        recognizer.cancelsTouchesInView = false
        recognizer.delegate = self
        navigator.view.addGestureRecognizer(recognizer)
        self.recognizer = recognizer
    }

    func close() {
        if let recognizer { recognizer.view?.removeGestureRecognizer(recognizer) }
        recognizer = nil
        navigator = nil
    }

    @objc private func didTap(_ recognizer: UITapGestureRecognizer) {
        guard recognizer.state == .ended, let navigator, let pdfView = navigator.pdfView else { return }
        if pdfView.currentSelection != nil {
            pdfView.clearSelection()
            return
        }
        let point = recognizer.location(in: pdfView)
        if let page = pdfView.page(for: point, nearest: false),
           let annotation = page.annotation(at: pdfView.convert(point, to: page)),
           annotation.action != nil || annotation.url != nil {
            return
        }
        onTap(recognizer.location(in: navigator.view))
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool {
        true
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldRequireFailureOf otherGestureRecognizer: UIGestureRecognizer) -> Bool {
        guard let tap = otherGestureRecognizer as? UITapGestureRecognizer else { return false }
        return tap.numberOfTapsRequired > 1
    }
}
