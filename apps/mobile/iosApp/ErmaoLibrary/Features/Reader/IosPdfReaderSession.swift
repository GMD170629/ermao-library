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
    @Published private(set) var remoteProgressSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
    @Published private(set) var remoteProgressActionFailed = false
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
    private let remoteDescriptor: ErmaoShared.DownloadDescriptor?
    private let pdfiumMaterializer: IosPdfiumDownloadMaterializer?
    private let preferencesStore: IosReaderPreferencesStore

    private let managedStore: IosManagedPublicationStore
    private let progressStore: any ErmaoShared.ReaderPositionSyncingStore
    private let progressCoordination: IosReaderProgressSessionCoordination?
    private let initialTarget: (any ErmaoShared.ReaderNavigationTarget)?
    private(set) var pendingLaunchTargetPayload: String?
    private let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
    private let namespaceKey: String
    private let bookID: String
    private let publishProgressUpdate: @MainActor (ErmaoShared.ReaderProgressPresentationUpdate) -> Void
    private let deviceIdentity: IosReaderDeviceIdentity
    private var pendingSave: Task<Void, Never>?
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
        remoteDescriptor: ErmaoShared.DownloadDescriptor? = nil,
        pdfiumMaterializer: IosPdfiumDownloadMaterializer? = nil,
        managedStore: IosManagedPublicationStore,
        progressStore: any ErmaoShared.ReaderPositionSyncingStore,
        progressCoordination: IosReaderProgressSessionCoordination? = nil,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV5?,
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
        self.remoteDescriptor = remoteDescriptor
        self.pdfiumMaterializer = pdfiumMaterializer
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
            if let remoteSource {
                guard let rangeCache, let rangeServer else {
                    throw IosReaderFailure(code: .engineError)
                }
                document = try await IosPdfiumDocument.open(
                    source: remoteSource,
                    cache: rangeCache,
                    server: rangeServer,
                    descriptor: remoteDescriptor,
                    materializer: pdfiumMaterializer
                )
            } else {
                let managed = try await managedStore.resolve(
                    resourceID: resourceID,
                    namespace: namespaceKey
                )
                guard managed.sourceFormat == .pdf else {
                    throw IosReaderFailure(code: .corruptFile)
                }
                document = try await IosPdfiumDocument.open(publication: managed)
            }
            try await finishOpening(document: document)
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
        pendingLaunchTargetPayload = nil
        return true
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

    func applySavedZoomAfterPresentation() {
        applySavedZoom()
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
        await releaseRuntime()
        phase = .closed
    }

    func flushProgress() async {
        pendingSave?.cancel()
        try? await persistCurrentPage()
    }

    private func restorePage(
        local: ErmaoShared.ReaderPositionLocalState?,
        remote: ErmaoShared.ReaderProgressSnapshotV5?
    ) async throws -> Int? {
        if let initialTarget {
            guard let target = initialTarget as? ErmaoShared.ReaderNavigationTargetPdf,
                  (0 ..< canonicalPageCount).contains(Int(target.pageIndex))
            else { throw IosReaderFailure(code: .locationRestoreFailed) }
            return Int(target.pageIndex)
        }
        let pending = (try? await progressStore.syncState())?.pending
        let locator: ErmaoShared.ReaderOpaqueLocator?
        if let pending, pending.resourceId == resourceID {
            locator = local?.position.locator
        } else if let remote {
            locator = remote.position.locator
        } else if progressCoordination == nil {
            locator = local?.position.locator
        } else {
            locator = nil
        }
        guard let locator else { return nil }
        guard let index = pageIndex(from: locator),
              (0 ..< canonicalPageCount).contains(index)
        else { return nil }
        return index
    }

    private func persistCurrentPage(waitForSynchronization: Bool = true) async throws {
        guard phase == .reading || phase == .background || phase == .closing
        else { return }
        guard let index = navigator?.pageIndex else { return }
        guard let position = makePosition(index: index) else { return }
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

    private func makePosition(index: Int) -> ErmaoShared.ReaderPositionLocalState? {
        guard (0 ..< canonicalPageCount).contains(index) else { return nil }
        let timestamp = Int64(Date().timeIntervalSince1970 * 1_000)
        let totalProgression = canonicalPageCount <= 1
            ? 1
            : Double(index) / Double(canonicalPageCount - 1)
        let locatorObject: [String: Any] = [
            "href": "document.pdf",
            "type": "application/pdf",
            "locations": [
                "position": index + 1,
                "progression": totalProgression,
                "totalProgression": totalProgression,
            ],
        ]
        guard JSONSerialization.isValidJSONObject(locatorObject),
              let data = try? JSONSerialization.data(withJSONObject: locatorObject, options: [.sortedKeys]),
              let locatorJSON = String(data: data, encoding: .utf8),
              let locator = try? ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: locatorJSON)
        else { return nil }
        let presentation = ErmaoShared.ReaderPositionPresentation(
            displayPercent: totalProgression * 100,
            totalProgression: totalProgression,
            currentHref: "document.pdf",
            chapter: nil,
            page: ErmaoShared.ReaderPagePresentation(
                number: Int32(index + 1),
                total: KotlinInt(int: Int32(canonicalPageCount))
            ),
            playback: nil
        )
        return ErmaoShared.ReaderPositionLocalState(
            resourceId: resourceID,
            clientId: deviceIdentity.stableDeviceId(),
            capturedAtEpochMillis: timestamp,
            position: ErmaoShared.ReaderPositionReport(locator: locator, presentation: presentation)
        )
    }

    private func pageIndex(from locator: ErmaoShared.ReaderOpaqueLocator) -> Int? {
        guard let data = locator.canonicalJson.data(using: .utf8),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let locations = root["locations"] as? [String: Any],
              let position = locations["position"] as? NSNumber
        else { return nil }
        let oneBased = position.intValue
        guard oneBased >= 1 else { return nil }
        return oneBased - 1
    }

    private func releaseRuntime() async {
        defer { rangeCache?.clear() }
        navigator?.close()
        navigator = nil
        tableOfContents = []
    }

    private func finishOpening(
        document: IosPdfiumDocument
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
        let local = try? await progressStore.load(resourceId: resourceID)
        let initialPage = try await restorePage(local: local, remote: remoteSnapshot) ?? 0
        let navigator = IosPdfiumNavigatorViewController(
            document: document,
            initialPageIndex: initialPage
        )
        navigator.onPageChanged = { [weak self] index in self?.pdfiumLocationChanged(index) }
        navigator.onFailure = { [weak self, weak navigator] failure in
            guard let self, let navigator, self.navigator === navigator,
                  phase == .reading || phase == .background else {
                return
            }
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
            self?.setRemoteProgress(snapshot)
        }
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
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(Self.progressSaveDebounceMilliseconds))
            guard !Task.isCancelled else { return }
            await self?.flushProgress()
        }
    }

    func dismissRemoteProgressNotice() {
        progressCoordination?.dismissRemoteNotice()
        setRemoteProgress(nil)
    }

    func goToRemoteProgress() async {
        guard let snapshot = remoteProgressSnapshot,
              let target = pageIndex(from: snapshot.position.locator),
              (0 ..< canonicalPageCount).contains(target),
              let navigator
        else {
            remoteProgressActionFailed = true
            return
        }
        remoteProgressActionFailed = false
        guard await navigator.goToPage(target) else {
            remoteProgressActionFailed = true
            return
        }
        pageIndex = target
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
