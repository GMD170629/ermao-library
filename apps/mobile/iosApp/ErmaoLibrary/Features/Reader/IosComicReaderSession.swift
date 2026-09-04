import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import SwiftUI
import UIKit

@MainActor
final class IosComicReaderSession: NSObject, ObservableObject {
    private let navigationQueue = IosReaderNavigationQueue()
    static let progressSaveDebounceMilliseconds = 500

    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: IosComicNavigatorViewController?
    @Published private(set) var pageIndex = 0
    @Published private(set) var presentationError: IosReaderFailureCode?
    @Published private(set) var remoteProgressSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
    @Published private(set) var remoteProgressActionFailed = false
    @Published var controlsVisible = false
    @Published var activeControlPanel: IosReaderPanel?
    @Published private(set) var preferences: IosReaderPreferences

    let resourceID: String
    let displayTitle: String
    let pages: [IosCbzPage]

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderPositionSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let initialTarget: (any ErmaoShared.ReaderNavigationTarget)?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
    private let namespaceKey: String
    private let bookID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let deviceIdentity: IosReaderDeviceIdentity
    private let remoteSource: ErmaoShared.RemoteComicReaderSource?
    private let comicPageServer: (any ErmaoShared.ComicPageServerPort)?
    private let preferencesStore: IosReaderPreferencesStore
    private var openedPublication: IosOpenedReadiumPublication?
    private var pendingSave: Task<Void, Never>?
    private var latestLocationChange: Locator?
    private var didOpen = false

    init(
        resourceID: String,
        displayTitle: String,
        pages: [IosCbzPage],
        preferences: IosReaderPreferences,
        preferencesStore: IosReaderPreferencesStore,
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderPositionSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV5?,
        initialTarget: (any ErmaoShared.ReaderNavigationTarget)? = nil,
        namespaceKey: String,
        bookID: String,
        publishProgressUpdate: @escaping @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void,
        deviceIdentity: IosReaderDeviceIdentity,
        remoteSource: ErmaoShared.RemoteComicReaderSource? = nil,
        comicPageServer: (any ErmaoShared.ComicPageServerPort)? = nil
    ) {
        self.resourceID = resourceID
        self.displayTitle = displayTitle
        self.pages = pages
        self.preferences = preferences
        self.preferencesStore = preferencesStore
        self.managedStore = managedStore
        self.progressStore = progressStore
        self.progressCoordination = progressCoordination
        self.remoteSnapshot = remoteSnapshot
        self.initialTarget = initialTarget
        self.namespaceKey = namespaceKey
        self.bookID = bookID
        self.publishProgressUpdate = publishProgressUpdate
        self.deviceIdentity = deviceIdentity
        self.remoteSource = remoteSource
        self.comicPageServer = comicPageServer
    }

    deinit {
        pendingSave?.cancel()
    }

    var pageCount: Int { pages.count }
    var supportsComicQuality: Bool { remoteSource != nil }
    var progress: Double { navigator?.currentProgress ?? (pages.count <= 1 ? 1 : Double(pageIndex) / Double(pages.count - 1)) }
    var pageLabel: String {
        navigator?.visiblePageLabel ?? "\(pageIndex + 1) / \(max(1, pages.count))"
    }

    func open() async {
        guard !didOpen else { return }
        didOpen = true
        do {
            let opened: IosOpenedReadiumPublication
            if let remoteSource {
                guard let comicPageServer else { throw IosReaderFailure(code: .networkUnavailable) }
                opened = try openRemotePublication(source: remoteSource, server: comicPageServer, preferences: preferences)
            } else {
                let managed = try await managedStore.resolve(
                    resourceID: resourceID,
                    namespace: namespaceKey
                )
                guard [.cbz, .zip, .cbr, .rar, .imagedir].contains(managed.sourceFormat) else {
                    throw IosReaderFailure(code: .comicArchiveFormatUnsupported)
                }
                if managed.sourceFormat == .imagedir {
                    opened = try IosImageDirectoryPublicationFactory().open(managed, pageTitleHints: pages)
                } else {
                    opened = try await IosCbzPublicationFactory().open(managed, pageTitleHints: pages)
                }
            }
            let local = try? await progressStore.load(resourceId: resourceID)
            let initialPage = try await restorePage(
                local: local,
                remote: remoteSnapshot
            )
            let initial = initialPage.map(locator(for:))
            let navigator = try IosComicNavigatorViewController(
                publication: opened.publication,
                pages: pages,
                initialLocation: initial,
                preferences: preferences
            )
            navigator.delegate = self
            openedPublication = opened
            self.navigator = navigator
            progressCoordination?.noticeHandler = { [weak self] snapshot in
                self?.setRemoteProgress(snapshot)
            }
            pageIndex = initialPage?.pageIndex ?? 0
            phase = .reading
            if remoteSource == nil {
                progressCoordination?.beginDeferredSynchronization()
            } else {
                await progressCoordination?.checkForRemoteProgress()
            }
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

    func goPrevious() async { _ = await navigator?.goBackward(animated: preferences.comicPageTurnAnimation == "slide") }
    func goNext() async { _ = await navigator?.goForward(animated: preferences.comicPageTurnAnimation == "slide") }

    func applyPreferences(_ updated: IosReaderPreferences) async -> Bool {
        guard canApplyControlPreferences(updated) else { return false }
        if updated.comicImageVariant != preferences.comicImageVariant {
            return await replaceRemotePublication(for: updated)
        }
        if let navigator {
            guard await navigator.applyPreferences(updated) else { return false }
        }
        guard preferencesStore.save(updated) else { return false }
        preferences = updated
        return true
    }

    /// A remote image variant changes the bytes returned by every Readium
    /// Resource. Reopen the publication as one transaction so no old request
    /// can populate the new renderer's cache or remain in flight.
    private func replaceRemotePublication(for updated: IosReaderPreferences) async -> Bool {
        guard let remoteSource,
              let comicPageServer,
              let oldNavigator = navigator,
              let oldPublication = openedPublication,
              let currentLocation = oldNavigator.currentLocation
        else { return false }

        var replacementPublication: IosOpenedReadiumPublication?
        let replacementNavigator: IosComicNavigatorViewController
        do {
            let opened = try openRemotePublication(
                source: remoteSource,
                server: comicPageServer,
                preferences: updated
            )
            replacementPublication = opened
            replacementNavigator = try IosComicNavigatorViewController(
                publication: opened.publication,
                pages: pages,
                initialLocation: currentLocation,
                preferences: updated
            )
            guard await replacementNavigator.prepareCurrentPresentation() else {
                throw IosReaderFailure(code: .comicArchiveOpenFailed)
            }
        } catch {
            await replacementPublication?.close()
            presentationError = presentationError ?? .comicArchiveOpenFailed
            return false
        }

        guard preferencesStore.save(updated) else {
            replacementNavigator.close()
            await replacementPublication?.close()
            return false
        }

        replacementNavigator.delegate = self
        openedPublication = replacementPublication
        navigator = replacementNavigator
        preferences = updated
        pageIndex = replacementNavigator.currentPageIndex
        oldNavigator.delegate = nil
        oldNavigator.close()
        await oldPublication.close()
        return true
    }

    func goToPage(_ index: Int) async -> Bool {
        await navigationQueue.enqueue { [weak self] in
            guard let self else { return false }
            return await self.executePageNavigation(index)
        }
    }

    private func executePageNavigation(_ index: Int) async -> Bool {
        guard pages.indices.contains(index), let navigator else { return false }
        let expected = pages[index]
        if pageIndex == expected.pageIndex { return true }
        guard await navigator.go(to: locator(for: expected), animated: preferences.comicPageTurnAnimation == "slide") else { return false }
        return true
    }

    func showControls() { controlsVisible = true }
    func dismissPresentationError() { presentationError = nil }
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
        try? await persistCurrentPage(waitForSynchronization: false)
        try? await progressStore.retryPendingUpload()
        try? await progressStore.awaitPendingUpload()
        progressCoordination?.close()
        navigator?.delegate = nil
        navigator?.close()
        navigator = nil
        await openedPublication?.close()
        openedPublication = nil
        phase = .closed
    }

    func flushProgress() async {
        pendingSave?.cancel()
        try? await persistCurrentPage()
    }

    private func restorePage(
        local: ErmaoShared.ReaderPositionLocalState?,
        remote: ErmaoShared.ReaderProgressSnapshotV5?
    ) async throws -> IosCbzPage? {
        if let initialTarget {
            guard let target = initialTarget as? ErmaoShared.ReaderNavigationTargetComic,
                  let page = pages.first(where: { $0.pageIndex == Int(target.pageIndex) && $0.resourceHref == target.resourceHref })
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
            return page
        }
        let pending = (try? await progressStore.syncState())?.pending
        let opaque: ErmaoShared.ReaderOpaqueLocator?
        if let pending, pending.resourceId == resourceID {
            opaque = local?.position.locator
        } else if let remote {
            opaque = remote.position.locator
        } else if progressCoordination == nil {
            opaque = local?.position.locator
        } else {
            opaque = nil
        }
        guard let opaque,
              let locator = try? ReadiumSwiftLocatorMapper().locator(from: opaque),
              let page = page(for: locator)
        else { return nil }
        guard pages.indices.contains(page.pageIndex),
              pages[page.pageIndex].resourceHref == page.resourceHref else {
            return nil
        }
        return page
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

    private func locationChanged(_ locator: Locator) {
        guard let page = page(for: locator) else {
            presentationError = .engineError
            return
        }
        latestLocationChange = locator
        pageIndex = page.pageIndex
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(Self.progressSaveDebounceMilliseconds))
            guard !Task.isCancelled else { return }
            await self?.flushProgress()
        }
    }

    private func persistCurrentPage(waitForSynchronization: Bool = true) async throws {
        guard phase == .reading || phase == .background || phase == .closing,
              let locator = latestLocationChange,
              let page = page(for: locator)
        else { return }
        guard let position = makePosition(page: page, locator: locator) else { return }
        try await progressStore.save(position: position)
        if waitForSynchronization {
            await progressCoordination?.refreshAfterSave()
        }
        publishProgressUpdate(ErmaoShared.PublicKt.createReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            bookId: bookID,
            resourceId: resourceID,
            position: position.position,
            capturedAtEpochMillis: position.capturedAtEpochMillis
        ))
    }

    private func makePosition(
        page: IosCbzPage,
        locator: Locator
    ) -> ErmaoShared.ReaderPositionLocalState? {
        let timestamp = Int64(Date().timeIntervalSince1970 * 1_000)
        let totalProgression = min(1, max(0, locator.locations.totalProgression
            ?? (pages.count <= 1 ? 1 : Double(page.pageIndex) / Double(pages.count - 1))))
        guard let opaque = try? ReadiumSwiftLocatorMapper().opaqueLocator(from: locator) else { return nil }
        let presentation = ErmaoShared.ReaderPositionPresentation(
            displayPercent: totalProgression * 100,
            totalProgression: totalProgression,
            currentHref: locator.href.normalized.string,
            chapter: nil,
            page: ErmaoShared.ReaderPagePresentation(
                number: Int32(page.pageIndex + 1),
                total: KotlinInt(int: Int32(pages.count))
            ),
            playback: nil
        )
        return ErmaoShared.ReaderPositionLocalState(
            resourceId: resourceID,
            clientId: deviceIdentity.stableDeviceId(),
            capturedAtEpochMillis: timestamp,
            position: ErmaoShared.ReaderPositionReport(locator: opaque, presentation: presentation)
        )
    }

    func dismissRemoteProgressNotice() {
        progressCoordination?.dismissRemoteNotice()
        setRemoteProgress(nil)
    }

    func goToRemoteProgress() async {
        guard let snapshot = remoteProgressSnapshot,
              let exact = try? ReadiumSwiftLocatorMapper().locator(from: snapshot.position.locator),
              let target = page(for: exact),
              let navigator
        else {
            remoteProgressActionFailed = true
            return
        }
        remoteProgressActionFailed = false
        guard await navigator.go(
            to: locator(for: target),
            animated: preferences.comicPageTurnAnimation == "slide"
        ) else {
            remoteProgressActionFailed = true
            return
        }
        pageIndex = target.pageIndex
        let local = ErmaoShared.ReaderPositionLocalState(
            resourceId: resourceID,
            clientId: deviceIdentity.stableDeviceId(),
            capturedAtEpochMillis: snapshot.capturedAtEpochMillis,
            position: snapshot.position
        )
        try? await progressCoordination?.acceptRemote(position: local, snapshot: snapshot)
        setRemoteProgress(nil)
    }

    private func setRemoteProgress(_ snapshot: ErmaoShared.ReaderProgressSnapshotV5?) {
        remoteProgressSnapshot = snapshot
        remoteProgressActionFailed = false
    }

    private func openRemotePublication(
        source: ErmaoShared.RemoteComicReaderSource,
        server: any ErmaoShared.ComicPageServerPort,
        preferences: IosReaderPreferences
    ) throws -> IosOpenedReadiumPublication {
        let variant = ErmaoShared.ReaderComicImageVariant.entries.first {
            $0.wireValue == preferences.comicImageVariant
        } ?? .original
        return try IosRemoteComicPublicationFactory().open(
            source: source,
            pages: pages,
            server: server,
            imageVariant: variant,
            onFailure: { [weak self] failure in self?.presentationError = failure.code }
        )
    }
}

extension IosComicReaderSession: IosComicNavigatorDelegate {
    func comicNavigator(_ navigator: IosComicNavigatorViewController, locationDidChange locator: Locator) {
        locationChanged(locator)
    }

    func comicNavigator(_ navigator: IosComicNavigatorViewController, didFail error: Error) {
        presentationError = presentationError ?? .comicArchiveOpenFailed
    }

    func comicNavigator(_ navigator: IosComicNavigatorViewController, didTapAt point: CGPoint) {
        let width = max(1, self.navigator?.view.bounds.width ?? UIScreen.main.bounds.width)
        routeControlTap(fraction: point.x / width)
    }

    func comicNavigator(_ navigator: IosComicNavigatorViewController, didRequest navigation: IosComicNavigationRequest) {
        switch navigation {
        case .escape:
            activeControlPanel = nil
            controlsVisible = true
        case .previous:
            guard activeControlPanel == nil, preferences.keyboardPageTurn else { return }
            Task { await goPrevious() }
        case .next:
            guard activeControlPanel == nil, preferences.keyboardPageTurn else { return }
            Task { await goNext() }
        }
    }
}
