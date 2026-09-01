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
    @Published private(set) var restoreWarning: IosReaderFailureCode?
    @Published private(set) var remoteProgressSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    @Published var controlsVisible = false
    @Published var activeControlPanel: IosReaderPanel?
    @Published private(set) var preferences: IosReaderPreferences

    let resourceID: String
    let displayTitle: String
    let pages: [IosCbzPage]

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderProgressSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let initialTarget: (any ErmaoShared.ReaderNavigationTarget)?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
    private let namespaceKey: String
    private let bookID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let deviceIdentity: IosReaderDeviceIdentity
    private let remoteSource: ErmaoShared.RemoteComicReaderSource?
    private let comicPageServer: (any ErmaoShared.ComicPageServerPort)?
    private let preferencesStore: IosReaderPreferencesStore
    private var openedPublication: IosOpenedReadiumPublication?
    private var pendingSave: Task<Void, Never>?
    private var expectedRestoredPage: IosCbzPage?
    private var hasReadingActivity = false
    private var suppressNextPersistence = false
    private var didOpen = false

    init(
        resourceID: String,
        displayTitle: String,
        pages: [IosCbzPage],
        preferences: IosReaderPreferences,
        preferencesStore: IosReaderPreferencesStore,
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderProgressSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?,
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
            let openedSource: ErmaoShared.ReaderSource
            if let remoteSource {
                guard let comicPageServer else { throw IosReaderFailure(code: .networkUnavailable) }
                opened = try openRemotePublication(source: remoteSource, server: comicPageServer, preferences: preferences)
                openedSource = remoteSource
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
                openedSource = ErmaoShared.LocalReaderSource(
                    resourceId: managed.resourceID,
                    displayTitle: managed.displayTitle,
                    format: managed.sourceFormat.readerFormat,
                    bookId: managed.bookID,
                    assetId: managed.assetID,
                    sourceFormat: managed.sourceFormat
                )
            }
            let local = try? await progressStore.load(sourceId: resourceID)
            let initialPage = try restorePage(
                local: local,
                remote: remoteSnapshot,
                openedSource: openedSource
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
                guard snapshot?.locator is ErmaoShared.ComicPublicationLocation else { return }
                self?.remoteProgressSnapshot = snapshot
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
        await verifyCurrentPage(expected: pages[index])
        return pageIndex == expected.pageIndex && pages[pageIndex].resourceHref == expected.resourceHref
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
    func dismissRemoteProgressNotice() {
        progressCoordination?.dismissRemoteNotice()
        remoteProgressSnapshot = nil
    }

    func goToRemoteProgress() async {
        guard let snapshot = remoteProgressSnapshot,
              let remote = snapshot.locator as? ErmaoShared.ComicPublicationLocation,
              pages.indices.contains(Int(remote.pageIndex))
        else { return }
        let expected = pages[Int(remote.pageIndex)]
        suppressNextPersistence = true
        _ = await goToPage(expected.pageIndex)
        guard pageIndex == expected.pageIndex else { suppressNextPersistence = false; return }
        guard let progress = makeProgress(page: expected) else { return }
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
        try? await persistCurrentPage(waitForSynchronization: false)
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
        local: ErmaoShared.ReaderProgress?,
        remote: ErmaoShared.ReaderProgressSnapshotV4?,
        openedSource: ErmaoShared.ReaderSource
    ) throws -> IosCbzPage? {
        if let initialTarget {
            guard let target = initialTarget as? ErmaoShared.ReaderNavigationTargetComic,
                  let page = pages.first(where: { $0.pageIndex == Int(target.pageIndex) && $0.resourceHref == target.resourceHref })
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
            expectedRestoredPage = page
            return page
        }
        let decision = ErmaoShared.PublicKt.decideReaderResume(
            localProgress: local,
            remoteSnapshot: remote,
            openedSource: openedSource
        )
        guard let selected = decision.selected else {
            if local != nil || remote != nil { restoreWarning = .locationRestoreFailed }
            return nil
        }
        let href: String
        let index: Int
        if let value = selected.localProgress?.location as? ErmaoShared.ComicReaderLocation {
            href = value.resourceHref
            index = Int(value.pageIndex)
        } else if let value = selected.remoteSnapshot?.locator as? ErmaoShared.ComicPublicationLocation {
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

    private func persistCurrentPage(waitForSynchronization: Bool = true) async throws {
        guard hasReadingActivity,
              phase == .reading || phase == .background || phase == .closing,
              let locator = navigator?.currentLocation,
              let page = page(for: locator)
        else { return }
        guard let progress = makeProgress(page: page) else { return }
        let percent = progress.percent?.doubleValue ?? 0
        try await progressStore.save(progress: progress)
        if waitForSynchronization {
            await progressCoordination?.refreshAfterSave()
        }
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

    private func makeProgress(page: IosCbzPage) -> ErmaoShared.ReaderProgress? {
        let location = ErmaoShared.ComicReaderLocation(
            resourceHref: page.resourceHref,
            pageIndex: Int32(page.pageIndex),
            engineLocator: nil
        )
        let timestamp = Int64(Date().timeIntervalSince1970 * 1_000)
        let percent = (navigator?.currentProgress ?? (pages.count <= 1 ? 1 : Double(page.pageIndex) / Double(pages.count - 1))) * 100
        return ErmaoShared.ReaderProgress(
            resourceId: resourceID,
            location: location,
            updatedAtEpochMillis: timestamp,
            deviceId: deviceIdentity.stableDeviceId(),
            percent: KotlinDouble(double: percent)
        )
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
