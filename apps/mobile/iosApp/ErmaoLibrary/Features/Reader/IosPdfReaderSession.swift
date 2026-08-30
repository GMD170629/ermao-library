import Foundation
@preconcurrency import ErmaoShared

@MainActor
final class IosPdfReaderSession: NSObject, ObservableObject {
    private let navigationQueue = IosReaderNavigationQueue()
    static let progressSaveDebounceMilliseconds = 500

    @Published private(set) var phase: IosReaderSessionPhase = .opening
    @Published private(set) var navigator: IosPdfiumNavigatorViewController?
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
            let document: IosPdfiumDocument
            let source: ErmaoShared.ReaderSource
            if let remoteSource {
                guard let rangeCache, let rangeServer else {
                    throw IosReaderFailure(code: .engineError)
                }
                document = try await IosPdfiumDocument.open(
                    source: remoteSource,
                    cache: rangeCache,
                    server: rangeServer
                )
                source = remoteSource
            } else {
                let managed = try await managedStore.resolve(
                    resourceID: resourceID,
                    namespace: namespaceKey
                )
                guard managed.sourceFormat == .pdf else {
                    throw IosReaderFailure(code: .corruptFile)
                }
                document = try await IosPdfiumDocument.open(publication: managed)
                source = ErmaoShared.LocalReaderSource(
                    resourceId: managed.resourceID,
                    displayTitle: managed.displayTitle,
                    format: managed.sourceFormat.readerFormat,
                    bookId: managed.bookID,
                    assetId: managed.assetID,
                    sourceFormat: managed.sourceFormat
                )
            }
            try await finishOpening(document: document, source: source)
        } catch let failure as IosReaderFailure {
            await releaseRuntime()
            phase = .failed(failure.code)
        } catch {
            await releaseRuntime()
            phase = .failed(.engineError)
        }
    }

    func goPrevious() async {
        _ = await goToPage(pageIndex - 1)
    }
    func goNext() async {
        _ = await goToPage(pageIndex + 1)
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
        if pageIndex == index {
            guard let navigator, await navigator.ensureCurrentPageRendered() else { return false }
            pendingLaunchTargetPayload = nil
            return true
        }
        guard let navigator else { return false }
        guard await navigator.goToPage(index) else { return false }
        await verifyCurrentPage(expected: index)
        if pageIndex == index { pendingLaunchTargetPayload = nil }
        return pageIndex == index
    }

    func goToTOCEntry(_ entry: IosReaderTocEntry) async -> Bool {
        if entry.id.hasPrefix("pdf:"),
           let index = Int(entry.id.dropFirst("pdf:".count)) {
            return await goToPage(index)
        }
        return false
    }

    func zoomIn() {
        navigator?.zoomIn()
    }

    func zoomOut() {
        navigator?.zoomOut()
    }

    func zoomToFit() {
        navigator?.zoomToFit()
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
        navigator?.setZoom(preferences.pdfZoom)
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
        suppressNextPersistence = pageIndex != expected
        let didNavigate = await goToPage(expected)
        suppressNextPersistence = false
        guard didNavigate, pageIndex == expected else { return }
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
        try? await persistCurrentPage(waitForSynchronization: false)
        progressCoordination?.close()
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

    private func verifyCurrentPage(expected: Int) async {
        try? await Task.sleep(for: .milliseconds(120))
        guard let navigator, navigator.pageIndex == expected else {
            restoreWarning = .locationRestoreFailed
            return
        }
        guard await navigator.ensureCurrentPageRendered() else {
            restoreWarning = .locationRestoreFailed
            return
        }
        pageIndex = expected
    }

    private func persistCurrentPage(waitForSynchronization: Bool = true) async throws {
        guard hasReadingActivity,
              phase == .reading || phase == .background || phase == .closing
        else { return }
        guard let index = navigator?.pageIndex else { return }
        guard let progress = makeProgress(index: index) else { return }
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
        navigator?.close()
        navigator = nil
        tableOfContents = []
    }

    private func finishOpening(
        document: IosPdfiumDocument,
        source: ErmaoShared.ReaderSource
    ) async throws {
        guard document.pageCount > 0 else {
            document.close()
            throw IosReaderFailure(code: .pdfInvalid)
        }
        var navigatorOwnsDocument = false
        defer {
            if !navigatorOwnsDocument { document.close() }
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
        navigator.onFailure = { [weak self] failure in
            guard let self else { return }
            if failure.safeContext["ruleId"] == ErmaoShared.PublicKt.readerSafetyPdfRenderBudgetFailure().ruleId {
                presentationError = failure.code
                return
            }
            if !failure.safeContext.isEmpty {
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    await releaseRuntime()
                    phase = .failed(failure.code)
                }
                return
            }
            presentationError = failure.code
        }
        navigator.onTapFraction = { [weak self] fraction in self?.routeControlTap(fraction: fraction) }
        navigator.onSwipe = { [weak self] command in self?.handleSwipe(command) }
        navigator.onKeyCommand = { [weak self] command in self?.handleKeyCommand(command) }
        self.navigator = navigator
        navigatorOwnsDocument = true
        progressCoordination?.noticeHandler = { [weak self] snapshot in
            guard snapshot?.locator is ErmaoShared.PdfPublicationLocation else { return }
            self?.remoteProgressSnapshot = snapshot
        }
        expectedRestoredPage = initialPage
        pageIndex = initialPage
        phase = .reading
        pendingLaunchTargetPayload = nil
        await beginProgressSynchronization()
    }

    private func beginProgressSynchronization() async {
        if remoteSource == nil {
            progressCoordination?.beginDeferredSynchronization()
        } else {
            await progressCoordination?.checkForRemoteProgress()
        }
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

    private func handleKeyCommand(_ command: IosPdfiumKeyCommand) {
        if command == .escape {
            activeControlPanel = nil
            controlsVisible = true
            return
        }
        guard activeControlPanel == nil, preferences.keyboardPageTurn else { return }
        switch command {
        case .previous:
            Task { await goPrevious() }
        case .next:
            Task { await goNext() }
        case .escape:
            break
        }
    }

    private func handleSwipe(_ command: IosPdfiumKeyCommand) {
        guard activeControlPanel == nil, preferences.swipePageTurn else { return }
        switch command {
        case .previous:
            Task { await goPrevious() }
        case .next:
            Task { await goNext() }
        case .escape:
            break
        }
    }
}

enum IosPdfPositionPolicy {
    static func accepts(pageProgression: Double) -> Bool {
        pageProgression == 0
    }
}
