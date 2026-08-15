import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumAdapterGCDWebServer
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
    @Published private(set) var preferences: IosReaderPreferences

    let sourceID: String
    let displayTitle: String
    @Published private(set) var canonicalPageCount: Int
    private let pageTitleHints: [String]
    private let remoteSource: ErmaoShared.RemoteByteRangeReaderSource?
    private let rangeCache: IosPdfRangeCache?
    private let rangeServer: (any ErmaoShared.PdfRangeServerPort)?
    private let preferencesStore: IosReaderPreferencesStore

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderProgressSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private let namespaceKey: String
    private let workID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let deviceIdentity: IosReaderDeviceIdentity
    private var managedPublication: IosManagedPublication?
    private var openedPublication: IosOpenedReadiumPublication?
    private var positions: [Locator] = []
    private var httpServer: GCDHTTPServer?
    private var pendingSave: Task<Void, Never>?
    private var expectedRestoredPage: Int?
    private var hasReadingActivity = false
    private var suppressNextPersistence = false
    private var didOpen = false

    init(
        sourceID: String,
        displayTitle: String,
        pageCountHint: Int?,
        pageTitleHints: [String],
        preferences: IosReaderPreferences,
        preferencesStore: IosReaderPreferencesStore,
        remoteSource: ErmaoShared.RemoteByteRangeReaderSource? = nil,
        rangeCache: IosPdfRangeCache? = nil,
        rangeServer: (any ErmaoShared.PdfRangeServerPort)? = nil,
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderProgressSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?,
        namespaceKey: String,
        workID: String,
        publishProgressUpdate: @escaping @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void,
        deviceIdentity: IosReaderDeviceIdentity
    ) {
        self.sourceID = sourceID
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
        self.namespaceKey = namespaceKey
        self.workID = workID
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
            let managed = try await managedStore.resolve(sourceID: sourceID)
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
            let local = try? await progressStore.load(sourceId: sourceID)
            let openedSource = ErmaoShared.LocalReaderSource(
                sourceId: managed.sourceID,
                displayTitle: managed.displayTitle,
                format: managed.sourceFormat.readerFormat,
                workId: managed.workID,
                volumeId: managed.volumeID,
                sourceFormat: managed.sourceFormat
            )
            let initialPage = restorePage(local: local, remote: remoteSnapshot, source: openedSource)
            let server = GCDHTTPServer(
                assetRetriever: AssetRetriever(httpClient: DefaultHTTPClient(ephemeral: true))
            )
            let navigator = try PDFNavigatorViewController(
                publication: opened.publication,
                initialLocation: initialPage.map { parsedPositions[$0] },
                config: PDFNavigatorViewController.Configuration(
                    preferences: PDFPreferences(scroll: false, spread: .never)
                ),
                httpServer: server
            )
            navigator.delegate = self
            httpServer = server
            self.navigator = navigator
            progressCoordination?.noticeHandler = { [weak self] snapshot in
                guard snapshot?.locator is ErmaoShared.PdfPublicationLocation else { return }
                self?.remoteProgressSnapshot = snapshot
            }
            pageIndex = initialPage ?? 0
            phase = .reading
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
        if let pdfiumNavigator {
            if pageIndex == index { return true }
            guard pdfiumNavigator.goToPage(index) else { return false }
            await verifyCurrentPage(expected: index)
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
        let previous = preferences
        if updated.pdfFit != previous.pdfFit {
            zoomToFit()
        }
        guard preferencesStore.save(updated) else {
            if updated.pdfFit != previous.pdfFit { zoomToFit() }
            return false
        }
        preferences = updated
        return true
    }

    func verifyRestoredLocationAfterPresentation() async {
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
    ) -> Int? {
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
            workId: workID,
            volumeId: sourceID,
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
            sourceId: sourceID,
            location: location,
            updatedAtEpochMillis: timestamp,
            deviceId: deviceIdentity.stableDeviceId(),
            percent: KotlinDouble(double: percent)
        )
    }

    private func releaseRuntime() async {
        navigator?.delegate = nil
        navigator = nil
        pdfiumNavigator?.close()
        pdfiumNavigator = nil
        // Releasing the navigator removes its endpoint. Releasing this session-owned
        // GCD server then stops the loopback-only listener.
        httpServer = nil
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
        let local = try? await progressStore.load(sourceId: sourceID)
        let initialPage = restorePage(local: local, remote: remoteSnapshot, source: source) ?? 0
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

extension IosPdfReaderSession: PDFNavigatorDelegate {
    func navigator(_ navigator: Navigator, locationDidChange locator: Locator) { locationChanged(locator) }
    func navigator(_ navigator: Navigator, presentError error: NavigatorError) { presentationError = .engineError }
    func navigator(_ navigator: Navigator, presentExternalURL url: URL) {}
    func navigator(_ navigator: VisualNavigator, didTapAt point: CGPoint) {
        let width = max(1, self.navigator?.view.bounds.width ?? UIScreen.main.bounds.width)
        switch point.x / width {
        case ..<0.3: Task { await goPrevious() }
        case 0.7...: Task { await goNext() }
        default: controlsVisible.toggle()
        }
    }
    func navigator(_ navigator: VisualNavigator, didPressKey event: KeyEvent) {}
    func navigator(_ navigator: VisualNavigator, didReleaseKey event: KeyEvent) {}
    func navigator(_ navigator: SelectableNavigator, shouldShowMenuForSelection selection: Selection) -> Bool { false }
    func navigator(_ navigator: SelectableNavigator, didSelect selection: Selection) {}
    func navigator(_ navigator: SelectableNavigator, didFailToCreateSelection error: Error) {}
}
