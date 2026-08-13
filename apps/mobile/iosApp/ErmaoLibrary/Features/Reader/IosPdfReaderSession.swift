import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumAdapterGCDWebServer
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import UIKit

@MainActor
final class IosPdfReaderSession: NSObject, ObservableObject {
    static let progressSaveDebounceMilliseconds = 500

    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: PDFNavigatorViewController?
    @Published private(set) var pageIndex = 0
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var restoreWarning: IosReaderFailureCode?
    @Published private(set) var tableOfContents: [IosReaderTocEntry] = []
    @Published var controlsVisible = false

    let sourceID: String
    let displayTitle: String
    let canonicalPageCount: Int

    private let managedStore: IosManagedPublicationStore
    private let progressStore: IosReaderProgressStore
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
    private var didOpen = false

    init(
        sourceID: String,
        displayTitle: String,
        canonicalPageCount: Int,
        managedStore: IosManagedPublicationStore,
        progressStore: IosReaderProgressStore,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?,
        namespaceKey: String,
        workID: String,
        publishProgressUpdate: @escaping @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void,
        deviceIdentity: IosReaderDeviceIdentity
    ) {
        self.sourceID = sourceID
        self.displayTitle = displayTitle
        self.canonicalPageCount = canonicalPageCount
        self.managedStore = managedStore
        self.progressStore = progressStore
        self.remoteSnapshot = remoteSnapshot
        self.namespaceKey = namespaceKey
        self.workID = workID
        self.publishProgressUpdate = publishProgressUpdate
        self.deviceIdentity = deviceIdentity
    }

    deinit { pendingSave?.cancel() }

    var pageLabel: String { "\(pageIndex + 1) / \(canonicalPageCount)" }
    var progress: Double {
        canonicalPageCount <= 1 ? 1 : Double(pageIndex) / Double(canonicalPageCount - 1)
    }

    func open() async {
        guard !didOpen else { return }
        didOpen = true
        do {
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
            guard parsedPositions.count == canonicalPageCount else {
                throw IosReaderFailure(code: .corruptFile)
            }
            positions = parsedPositions
            tableOfContents = await loadTableOfContents(opened.publication)
            let local = try await progressStore.load(sourceId: sourceID)
            let initialPage = restorePage(local: local, remote: remoteSnapshot, managed: managed)
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
            pageIndex = initialPage ?? 0
            phase = .reading
        } catch let failure as IosReaderFailure {
            await releaseRuntime()
            phase = .failed(failure.code)
        } catch {
            await releaseRuntime()
            phase = .failed(.engineError)
        }
    }

    func goPrevious() async { _ = await navigator?.goBackward(options: .animated) }
    func goNext() async { _ = await navigator?.goForward(options: .animated) }

    func goToPage(_ index: Int) async {
        guard positions.indices.contains(index), let navigator else { return }
        _ = await navigator.go(to: positions[index], options: .animated)
        await verifyCurrentPage(expected: index)
    }

    func goToTOCEntry(_ entry: IosReaderTocEntry) async {
        guard let publication = openedPublication?.publication,
              let href = RelativeURL(string: entry.href),
              let link = publication.linkWithHREF(href),
              let navigator
        else { return }
        _ = await navigator.go(to: link, options: .animated)
    }

    func zoomIn() {
        guard let view = navigator?.pdfView else { return }
        view.scaleFactor = min(view.maxScaleFactor, view.scaleFactor * 1.25)
    }

    func zoomOut() {
        guard let view = navigator?.pdfView else { return }
        view.scaleFactor = max(view.minScaleFactor, view.scaleFactor / 1.25)
    }

    func zoomToFit() {
        guard let navigator else { return }
        navigator.submitPreferences(PDFPreferences(scroll: false, spread: .never))
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

    func enterBackground() async {
        phase = .background
        await flushProgress()
        try? await progressStore.awaitPendingUpload()
    }

    func becomeActive() {
        if phase == .background { phase = .reading }
        Task { try? await progressStore.retryPendingUpload() }
    }

    func close() async throws {
        guard phase != .closed else { return }
        phase = .closing
        pendingSave?.cancel()
        do {
            try await persistCurrentPage()
            try? await progressStore.awaitPendingUpload()
        } catch {
            phase = .reading
            throw error
        }
        await releaseRuntime()
        phase = .closed
    }

    func flushProgress() async {
        pendingSave?.cancel()
        do { try await persistCurrentPage() } catch { presentationError = .persistenceFailed }
    }

    private func restorePage(
        local: ErmaoShared.ReaderProgress?,
        remote: ErmaoShared.ReaderProgressSnapshotV4?,
        managed: IosManagedPublication
    ) -> Int? {
        let source = ErmaoShared.LocalReaderSource(
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
            openedSource: source
        )
        guard let selected = decision.selected else {
            if local != nil || remote != nil { restoreWarning = .locationRestoreFailed }
            return nil
        }
        let index: Int
        if let value = selected.localProgress?.location as? ErmaoShared.PdfReaderLocation {
            guard IosContentFingerprint(shared: value.contentFingerprint) == managed.fingerprint,
                  IosPdfPositionPolicy.accepts(pageProgression: value.pageProgression)
            else {
                restoreWarning = .locationRestoreFailed
                return nil
            }
            index = Int(value.pageIndex)
        } else if let value = selected.remoteSnapshot?.locator as? ErmaoShared.PdfPublicationLocation {
            guard let fingerprint = try? IosContentFingerprint(
                originalFileHash: value.publication.originalFileHash,
                parserVersion: value.publication.parser,
                normalizationVersion: value.publication.normalization
            ), fingerprint == managed.fingerprint,
               IosPdfPositionPolicy.accepts(pageProgression: value.pageProgression) else {
                restoreWarning = .locationRestoreFailed
                return nil
            }
            index = Int(value.pageIndex)
        } else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        guard positions.indices.contains(index) else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        expectedRestoredPage = index
        return index
    }

    private func pageIndex(for locator: Locator) -> Int? {
        guard let position = locator.locations.position else { return nil }
        return IosPdfPositionPolicy.pageIndex(position: position, pageCount: positions.count)
    }

    private func loadTableOfContents(_ publication: Publication) async -> [IosReaderTocEntry] {
        guard case let .success(links) = await publication.tableOfContents() else { return [] }
        var sequence = 0
        func flatten(_ links: [Link], depth: Int) -> [IosReaderTocEntry] {
            links.flatMap { link in
                sequence += 1
                let title = link.title?.trimmingCharacters(in: .whitespacesAndNewlines)
                let current = IosReaderTocEntry(
                    id: "\(sequence):\(link.href)",
                    title: title.flatMap { $0.isEmpty ? nil : $0 }
                        ?? String(localized: "reader.toc.untitled"),
                    href: link.href.string,
                    depth: depth
                )
                return [current] + flatten(link.children, depth: depth + 1)
            }
        }
        return flatten(links, depth: 0)
    }

    private func verifyCurrentPage(expected: Int) async {
        try? await Task.sleep(for: .milliseconds(120))
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
              phase == .reading || phase == .background || phase == .closing,
              let managedPublication, let locator = navigator?.currentLocation,
              let index = pageIndex(for: locator)
        else { return }
        let location = ErmaoShared.PdfReaderLocation(
            pageIndex: Int32(index),
            pageProgression: 0,
            contentFingerprint: managedPublication.fingerprint.shared,
            engineLocator: nil
        )
        let timestamp = Int64(Date().timeIntervalSince1970 * 1_000)
        let percent = canonicalPageCount <= 1 ? 100 : Double(index) / Double(canonicalPageCount - 1) * 100
        let progress = ErmaoShared.ReaderProgress(
            sourceId: sourceID,
            location: location,
            updatedAtEpochMillis: timestamp,
            deviceId: deviceIdentity.stableDeviceId(),
            percent: KotlinDouble(double: percent)
        )
        try await progressStore.save(progress: progress)
        publishProgressUpdate(ErmaoShared.ReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            workId: workID,
            volumeId: sourceID,
            percent: percent,
            currentHref: "pdf:page:\(index)",
            chapterTitle: nil,
            capturedAtEpochMillis: timestamp
        ))
    }

    private func releaseRuntime() async {
        navigator?.delegate = nil
        navigator = nil
        // Releasing the navigator removes its endpoint. Releasing this session-owned
        // GCD server then stops the loopback-only listener.
        httpServer = nil
        await openedPublication?.close()
        openedPublication = nil
        managedPublication = nil
        positions = []
        tableOfContents = []
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
