import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import SwiftUI
import UIKit

@MainActor
final class IosComicReaderSession: NSObject, ObservableObject {
    static let progressSaveDebounceMilliseconds = 500

    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: EPUBNavigatorViewController?
    @Published private(set) var pageIndex = 0
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var restoreWarning: IosReaderFailureCode?
    @Published var controlsVisible = false

    let sourceID: String
    let displayTitle: String
    let pages: [IosCbzPage]

    private let managedStore: IosManagedPublicationStore
    private let progressStore: IosReaderProgressStore
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private let namespaceKey: String
    private let workID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let deviceIdentity: IosReaderDeviceIdentity
    private var managedPublication: IosManagedPublication?
    private var openedPublication: IosOpenedReadiumPublication?
    private var pendingSave: Task<Void, Never>?
    private var expectedRestoredPage: IosCbzPage?
    private var hasReadingActivity = false
    private var didOpen = false

    init(
        sourceID: String,
        displayTitle: String,
        pages: [IosCbzPage],
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
        self.pages = pages
        self.managedStore = managedStore
        self.progressStore = progressStore
        self.remoteSnapshot = remoteSnapshot
        self.namespaceKey = namespaceKey
        self.workID = workID
        self.publishProgressUpdate = publishProgressUpdate
        self.deviceIdentity = deviceIdentity
    }

    deinit { pendingSave?.cancel() }

    var pageCount: Int { pages.count }
    var progress: Double { pages.count <= 1 ? 1 : Double(pageIndex) / Double(pages.count - 1) }
    var pageLabel: String { "\(pageIndex + 1) / \(max(1, pages.count))" }

    func open() async {
        guard !didOpen else { return }
        didOpen = true
        do {
            let managed = try await managedStore.resolve(sourceID: sourceID)
            guard managed.sourceFormat == .cbz else { throw IosReaderFailure(code: .corruptFile) }
            let opened = try await IosCbzPublicationFactory().open(managed, canonicalPages: pages)
            let local = try await progressStore.load(sourceId: sourceID)
            let initialPage = restorePage(local: local, remote: remoteSnapshot, managed: managed)
            let initial = initialPage.map(locator(for:))
            var config = EPUBNavigatorViewController.Configuration()
            config.disablePageTurnsWhileScrolling = false
            let navigator = try EPUBNavigatorViewController(
                publication: opened.publication,
                initialLocation: initial,
                config: config
            )
            navigator.delegate = self
            managedPublication = managed
            openedPublication = opened
            self.navigator = navigator
            pageIndex = initialPage?.pageIndex ?? 0
            phase = .reading
        } catch let failure as IosReaderFailure {
            await openedPublication?.close()
            openedPublication = nil
            phase = .failed(failure.code)
        } catch {
            await openedPublication?.close()
            openedPublication = nil
            phase = .failed(.engineError)
        }
    }

    func goPrevious() async { _ = await navigator?.goBackward(options: .animated) }
    func goNext() async { _ = await navigator?.goForward(options: .animated) }

    func goToPage(_ index: Int) async {
        guard pages.indices.contains(index), let navigator else { return }
        _ = await navigator.go(to: locator(for: pages[index]), options: .animated)
        await verifyCurrentPage(expected: pages[index])
    }

    func verifyRestoredLocationAfterPresentation() async {
        guard let expected = expectedRestoredPage else { return }
        expectedRestoredPage = nil
        try? await Task.sleep(for: .milliseconds(160))
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
        navigator?.delegate = nil
        navigator = nil
        await openedPublication?.close()
        openedPublication = nil
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
    ) -> IosCbzPage? {
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
        let href: String
        let index: Int
        if let value = selected.localProgress?.location as? ErmaoShared.ComicReaderLocation {
            guard IosContentFingerprint(shared: value.contentFingerprint) == managed.fingerprint else {
                restoreWarning = .locationRestoreFailed
                return nil
            }
            href = value.resourceHref
            index = Int(value.pageIndex)
        } else if let value = selected.remoteSnapshot?.locator as? ErmaoShared.ComicPublicationLocation {
            guard let fingerprint = try? IosContentFingerprint(
                originalFileHash: value.publication.originalFileHash,
                parserVersion: value.publication.parser,
                normalizationVersion: value.publication.normalization
            ), fingerprint == managed.fingerprint else {
                restoreWarning = .locationRestoreFailed
                return nil
            }
            href = value.resourceHref
            index = Int(value.pageIndex)
        } else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        guard pages.indices.contains(index), pages[index].resourceHref == href else {
            restoreWarning = .locationRestoreFailed
            return nil
        }
        expectedRestoredPage = pages[index]
        return pages[index]
    }

    private func locator(for page: IosCbzPage) -> Locator {
        Locator(
            href: AnyURL(string: page.resourceHref)!,
            mediaType: MediaType(page.mediaType)!,
            title: String(page.pageIndex + 1),
            locations: Locator.Locations(
                progression: 0,
                totalProgression: pages.count <= 1 ? 1 : Double(page.pageIndex) / Double(pages.count - 1),
                position: page.pageIndex + 1
            )
        )
    }

    private func page(for locator: Locator) -> IosCbzPage? {
        let href = locator.href.removingQuery().removingFragment().string
        guard let index = pages.firstIndex(where: { $0.resourceHref == href }),
              pages[index].pageIndex == index
        else { return nil }
        return pages[index]
    }

    private func verifyCurrentPage(expected: IosCbzPage) async {
        try? await Task.sleep(for: .milliseconds(100))
        guard let locator = navigator?.currentLocation,
              let actual = page(for: locator),
              actual.pageIndex == expected.pageIndex,
              actual.resourceHref == expected.resourceHref
        else {
            restoreWarning = .locationRestoreFailed
            return
        }
        pageIndex = actual.pageIndex
    }

    private func locationChanged(_ locator: Locator) {
        guard let page = page(for: locator) else {
            presentationError = .engineError
            return
        }
        pageIndex = page.pageIndex
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
              let page = page(for: locator)
        else { return }
        let location = ErmaoShared.ComicReaderLocation(
            resourceHref: page.resourceHref,
            pageIndex: Int32(page.pageIndex),
            contentFingerprint: managedPublication.fingerprint.shared,
            engineLocator: nil
        )
        let timestamp = Int64(Date().timeIntervalSince1970 * 1_000)
        let percent = pages.count <= 1 ? 100 : Double(page.pageIndex) / Double(pages.count - 1) * 100
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
            currentHref: page.resourceHref,
            chapterTitle: nil,
            capturedAtEpochMillis: timestamp
        ))
    }
}

extension IosComicReaderSession: EPUBNavigatorDelegate {
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
