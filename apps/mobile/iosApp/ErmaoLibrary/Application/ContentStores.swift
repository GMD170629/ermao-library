import Foundation
import Combine
@preconcurrency import ErmaoShared

enum ContentCacheIssue: String, Sendable {
    case readFailed
    case writeFailed
    case purgeFailed
}

enum HomeSectionState<Value: Sendable>: Sendable {
    case loading
    case content(Value, isCached: Bool)
    case empty
    case failure
}

@MainActor
final class HomeStore: ObservableObject {
    @Published private(set) var continueReading: HomeSectionState<ContinueReadingItem> = .loading
    @Published private(set) var recentReading: HomeSectionState<[WorkCard]> = .loading
    @Published private(set) var recentAdded: HomeSectionState<[WorkCard]> = .loading
    @Published private(set) var cacheIssue: ContentCacheIssue?

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let cache: LibraryCacheStore
    private let onUnauthorized: @MainActor () -> Void
    private var continueGeneration = UUID()
    private var recentReadingGeneration = UUID()
    private var recentAddedGeneration = UUID()

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: LibraryCacheStore,
        onUnauthorized: @escaping @MainActor () -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.onUnauthorized = onUnauthorized
    }

    func load() {
        let continueGeneration = UUID()
        let recentReadingGeneration = UUID()
        let recentAddedGeneration = UUID()
        self.continueGeneration = continueGeneration
        self.recentReadingGeneration = recentReadingGeneration
        self.recentAddedGeneration = recentAddedGeneration
        Task { [weak self] in
            guard let self else { return }
            async let continueTask: Void = loadContinueReading(generation: continueGeneration)
            async let recentTask: Void = loadRecentReading(generation: recentReadingGeneration)
            async let addedTask: Void = loadRecentAdded(generation: recentAddedGeneration)
            _ = await (continueTask, recentTask, addedTask)
        }
    }

    func retryContinueReading() {
        let generation = UUID()
        continueGeneration = generation
        Task { await loadContinueReading(generation: generation) }
    }
    func retryRecentReading() {
        let generation = UUID()
        recentReadingGeneration = generation
        Task { await loadRecentReading(generation: generation) }
    }
    func retryRecentAdded() {
        let generation = UUID()
        recentAddedGeneration = generation
        Task { await loadRecentAdded(generation: generation) }
    }

    private func loadContinueReading(generation: UUID) async {
        continueReading = .loading
        do {
            let value = try await client.fetchContinueReading(context: context)
            guard continueGeneration == generation else { return }
            if let value {
                continueReading = .content(value, isCached: false)
            } else {
                continueReading = .empty
            }
        } catch {
            guard continueGeneration == generation else { return }
            if handleUnauthorized(error) { return }
            if await handleInaccessible(error) { continueReading = .failure; return }
            continueReading = .failure
        }
    }

    private func loadRecentReading(generation: UUID) async {
        recentReading = .loading
        do {
            let values = try await client.fetchRecentReading(context: context, limit: 12)
            guard recentReadingGeneration == generation else { return }
            recentReading = values.isEmpty ? .empty : .content(values, isCached: false)
        } catch {
            guard recentReadingGeneration == generation else { return }
            if handleUnauthorized(error) { return }
            if await handleInaccessible(error) { recentReading = .failure; return }
            recentReading = .failure
        }
    }

    private func loadRecentAdded(generation: UUID) async {
        recentAdded = .loading
        do {
            let values = try await client.fetchRecentAdded(context: context, limit: 12)
            guard recentAddedGeneration == generation else { return }
            recentAdded = values.isEmpty ? .empty : .content(values, isCached: false)
        } catch {
            guard recentAddedGeneration == generation else { return }
            if handleUnauthorized(error) { return }
            if await handleInaccessible(error) { recentAdded = .failure; return }
            recentAdded = .failure
        }
    }

    private func handleUnauthorized(_ error: Error) -> Bool {
        guard case ContentClientError.unauthorized = error else { return false }
        onUnauthorized()
        return true
    }

    private func handleInaccessible(_ error: Error) async -> Bool {
        guard case ContentClientError.inaccessible = error else { return false }
        do { try await cache.removeNamespace(context.namespaceKey) }
        catch { cacheIssue = .purgeFailed }
        return true
    }

}

enum LibraryResultItem: Identifiable, Sendable {
    case work(WorkCard)
    case grouping(LibraryGrouping)

    var id: String {
        switch self {
        case .work(let value): "work:\(value.id)"
        case .grouping(let value): "group:\(value.id)"
        }
    }
}

enum LibraryResultState: Sendable {
    case idle
    case loading
    case ready(items: [LibraryResultItem], total: Int, isCached: Bool, isRefreshing: Bool)
    case empty
    case failure
    case permissionRevalidating
    case inaccessible
}

struct LibraryScopeState: Sendable {
    var query = ""
    var sort: LibrarySort = .recentAdded
    var viewMode: LibraryViewMode = .grid
    var filters = LibraryFilters()
    var results: LibraryResultState = .idle
    var loadedPage = 0
    var totalPages = 1
    var scrollAnchor: String?
    var isLoadingNextPage = false
    var hasPaginationError = false
    var paginationRequestKey: String?
}

@MainActor
final class LibraryStore: ObservableObject {
    @Published private(set) var selectedScope: LibraryScope = .works
    @Published private(set) var cacheIssue: ContentCacheIssue?
    @Published private(set) var scopeStates: [LibraryScope: LibraryScopeState] = [
        .works: LibraryScopeState(),
        .series: LibraryScopeState(),
        .authors: LibraryScopeState(),
    ]

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let cache: LibraryCacheStore
    private let onUnauthorized: @MainActor () -> Void
    private let discoveryRuntime = ErmaoShared.LibraryDiscoveryRuntime(
        offlineFilterAvailability: ErmaoShared.OfflineFilterAvailabilityUnavailable(
            reasonCode: "MANAGED_DOWNLOADS_UNAVAILABLE"
        )
    )
    private var searchTask: Task<Void, Never>?

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: LibraryCacheStore,
        onUnauthorized: @escaping @MainActor () -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.onUnauthorized = onUnauthorized
    }

    deinit {
        searchTask?.cancel()
    }

    var current: LibraryScopeState { scopeStates[selectedScope] ?? LibraryScopeState() }

    let offlineFilterAvailability: OfflineFilterAvailability = .unavailable(
        reasonCode: "MANAGED_DOWNLOADS_UNAVAILABLE"
    )

    func selectScope(_ scope: LibraryScope) {
        guard selectedScope != scope else { return }
        discoveryRuntime.selectScope(scope: sharedScope(scope))
        revalidate(scope)
        selectedScope = scope
    }

    func setQuery(_ query: String) {
        discoveryRuntime.updateQuery(scope: sharedScope(selectedScope), query: query)
        updateCurrent { $0.query = query }
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            self?.reload()
        }
    }

    func setSort(_ sort: LibrarySort) {
        guard selectedScope == .works else { return }
        guard current.sort != sort else { return }
        discoveryRuntime.updateSort(scope: .works, sort: sharedSort(sort))
        updateCurrent { $0.sort = sort }
        reload()
    }

    func reloadIfNeeded() {
        guard case .idle = current.results else { return }
        reload()
    }

    func setViewMode(_ viewMode: LibraryViewMode) {
        discoveryRuntime.updateViewMode(
            scope: sharedScope(selectedScope),
            viewMode: viewMode == .grid ? .grid : .list
        )
        updateCurrent {
            $0.viewMode = viewMode
            $0.isLoadingNextPage = false
            $0.paginationRequestKey = nil
        }
    }

    func applyFilters(_ filters: LibraryFilters) {
        guard selectedScope == .works, !filters.downloadedOnly else { return }
        guard discoveryRuntime.applyFilters(filters: sharedFilters(filters)) is ErmaoShared.FilterCommitResultApplied
        else { return }
        updateCurrent { $0.filters = filters }
        reload()
    }

    func removeMediaFilter(_ mediaKind: LibraryMediaKind) {
        var filters = current.filters
        filters.mediaKinds.remove(mediaKind)
        applyFilters(filters)
    }

    func removeReadingFilter(_ readingStatus: LibraryReadingStatus) {
        var filters = current.filters
        filters.readingStatuses.remove(readingStatus)
        applyFilters(filters)
    }

    func clearSearch() {
        discoveryRuntime.updateQuery(scope: sharedScope(selectedScope), query: "")
        updateCurrent { $0.query = "" }
        reload()
    }

    func rememberAnchor(_ identifier: String) {
        discoveryRuntime.rememberScrollAnchor(
            scope: sharedScope(selectedScope),
            anchor: ErmaoShared.LibraryScrollAnchor(itemId: identifier, offset: 0)
        )
        updateCurrent { $0.scrollAnchor = identifier }
    }

    func reload() {
        let scope = selectedScope
        let token = discoveryRuntime.beginInitialRequest(
            scope: sharedScope(scope),
            retainsVisibleContent: current.readyItems?.isEmpty == false
        )
        update(scope) {
            $0.results = .loading
            $0.loadedPage = 0
            $0.totalPages = 1
            $0.isLoadingNextPage = false
            $0.hasPaginationError = false
            $0.paginationRequestKey = nil
            $0.scrollAnchor = nil
        }
        Task { [weak self] in
            await self?.load(scope: scope, page: 1, token: token)
        }
    }

    func refresh() {
        revalidate(selectedScope)
    }

    private func revalidate(_ scope: LibraryScope) {
        if case .ready(let items, let total, let cached, _) = scopeStates[scope]?.results {
            update(scope) {
                $0.results = .ready(
                    items: items,
                    total: total,
                    isCached: cached,
                    isRefreshing: true
                )
            }
        } else {
            update(scope) {
                $0.results = .loading
                $0.loadedPage = 0
                $0.totalPages = 1
                $0.isLoadingNextPage = false
                $0.hasPaginationError = false
                $0.paginationRequestKey = nil
            }
        }
        let token = discoveryRuntime.beginInitialRequest(
            scope: sharedScope(scope),
            retainsVisibleContent: scopeStates[scope]?.readyItems?.isEmpty == false
        )
        Task { [weak self] in
            await self?.load(scope: scope, page: 1, token: token)
        }
    }

    func loadNextPageIfNeeded(visibleItemID: String) {
        let state = current
        let nextPage = state.loadedPage + 1
        let requestKey = paginationRequestKey(scope: selectedScope, state: state, page: nextPage)
        guard
            state.loadedPage < state.totalPages,
            !state.isLoadingNextPage,
            state.paginationRequestKey != requestKey,
            let items = state.readyItems,
            items.suffix(6).contains(where: { $0.id == visibleItemID })
        else { return }
        updateCurrent {
            $0.isLoadingNextPage = true
            $0.hasPaginationError = false
            $0.paginationRequestKey = requestKey
        }
        let scope = selectedScope
        guard let token = discoveryRuntime.beginNextPage(
            scope: sharedScope(scope),
            page: Int32(nextPage)
        ) else { return }
        Task { [weak self] in
            await self?.load(scope: scope, page: nextPage, token: token)
        }
    }

    func retryNextPage() {
        updateCurrent { $0.hasPaginationError = false }
        let state = current
        guard state.loadedPage < state.totalPages else { return }
        let nextPage = state.loadedPage + 1
        let requestKey = paginationRequestKey(scope: selectedScope, state: state, page: nextPage)
        updateCurrent {
            $0.isLoadingNextPage = true
            $0.paginationRequestKey = requestKey
        }
        let scope = selectedScope
        guard let token = discoveryRuntime.beginNextPage(
            scope: sharedScope(scope),
            page: Int32(nextPage)
        ) else { return }
        Task { [weak self] in
            await self?.load(scope: scope, page: nextPage, token: token)
        }
    }

    private func load(
        scope: LibraryScope,
        page: Int,
        token: ErmaoShared.LibraryRequestToken
    ) async {
        guard let state = scopeStates[scope] else { return }
        do {
            let fetched = try await fetch(scope: scope, state: state, page: page)
            guard discoveryRuntime.acceptPage(
                token: token,
                isEmpty: fetched.response.isEmpty,
                source: .network,
                isStale: false
            ) else { return }
            apply(
                fetched.response,
                scope: scope,
                page: page,
                isCached: false
            )
        } catch {
            if case ContentClientError.unauthorized = error {
                discoveryRuntime.beginPermissionRevalidation()
                scopeStates = scopeStates.mapValues { state in
                    var next = state
                    next.results = .permissionRevalidating
                    next.loadedPage = 0
                    next.scrollAnchor = nil
                    return next
                }
                onUnauthorized()
                return
            }
            if case ContentClientError.inaccessible = error {
                discoveryRuntime.markInaccessible(scope: sharedScope(scope))
                do { try await cache.removeNamespace(context.namespaceKey) }
                catch { cacheIssue = .purgeFailed }
                update(scope) {
                    $0.results = .inaccessible
                    $0.isLoadingNextPage = false
                    $0.paginationRequestKey = nil
                }
                return
            }
            if page > 1 {
                _ = discoveryRuntime.fail(token: token, errorCode: "CONTENT_LOAD_FAILED", hasVisibleContent: true)
                update(scope) {
                    $0.isLoadingNextPage = false
                    $0.hasPaginationError = true
                    $0.paginationRequestKey = nil
                }
            } else {
                _ = discoveryRuntime.fail(token: token, errorCode: "CONTENT_LOAD_FAILED", hasVisibleContent: false)
                update(scope) { $0.results = .failure }
            }
        }
    }

    private enum PageResponse: Sendable {
        case works(WorkPage)
        case groupings(GroupingPage)

        var isEmpty: Bool {
            switch self {
            case .works(let page): page.works.isEmpty
            case .groupings(let page): page.groups.isEmpty
            }
        }
    }

    private struct PageFetch: Sendable {
        let response: PageResponse
        let provenance: ContentProvenance
        let isStale: Bool
    }

    private func fetch(scope: LibraryScope, state: LibraryScopeState, page: Int) async throws -> PageFetch {
        switch scope {
        case .works:
            let result = try await client.fetchWorksResult(
                    context: context,
                    query: WorksQuery(
                        query: state.query,
                        sort: state.sort,
                        filters: state.filters,
                        page: page,
                        pageSize: 24
                    )
                )
            return PageFetch(
                response: .works(result.value),
                provenance: result.provenance,
                isStale: result.isStale
            )
        case .series, .authors:
            let result = try await client.fetchGroupingsResult(
                    context: context,
                    query: GroupingsQuery(
                        kind: scope == .series ? .series : .author,
                        query: state.query,
                        page: page,
                        pageSize: 30
                    )
                )
            return PageFetch(
                response: .groupings(result.value),
                provenance: result.provenance,
                isStale: result.isStale
            )
        }
    }

    private func apply(_ response: PageResponse, scope: LibraryScope, page: Int, isCached: Bool) {
        let nextItems: [LibraryResultItem]
        let total: Int
        let totalPages: Int
        switch response {
        case .works(let value):
            nextItems = value.works.map(LibraryResultItem.work)
            total = value.total
            totalPages = value.totalPages
        case .groupings(let value):
            nextItems = value.groups.map(LibraryResultItem.grouping)
            total = value.total
            totalPages = value.totalPages
        }
        let previous = page > 1 ? scopeStates[scope]?.readyItems ?? [] : []
        let merged = deduplicated(previous + nextItems)
        update(scope) {
            $0.results = merged.isEmpty
                ? .empty
                : .ready(items: merged, total: total, isCached: isCached, isRefreshing: false)
            $0.loadedPage = page
            $0.totalPages = totalPages
            $0.isLoadingNextPage = false
            $0.hasPaginationError = false
            $0.paginationRequestKey = nil
        }
    }

    private func deduplicated(_ items: [LibraryResultItem]) -> [LibraryResultItem] {
        var identifiers = Set<String>()
        return items.filter { identifiers.insert($0.id).inserted }
    }

    private func cacheKey(scope: LibraryScope, state: LibraryScopeState, page: Int) -> String {
        let media = state.filters.mediaKinds.map(\.rawValue).sorted().joined(separator: ",")
        let reading = state.filters.readingStatuses.map(\.rawValue).sorted().joined(separator: ",")
        return "library|\(scope.rawValue)|\(state.query)|\(state.sort.rawValue)|\(state.viewMode.rawValue)|\(media)|\(reading)|\(state.filters.downloadedOnly)|\(page)"
    }

    private func paginationRequestKey(scope: LibraryScope, state: LibraryScopeState, page: Int) -> String {
        cacheKey(scope: scope, state: state, page: page)
    }

    private func updateCurrent(_ update: (inout LibraryScopeState) -> Void) {
        self.update(selectedScope, update)
    }

    private func update(_ scope: LibraryScope, _ update: (inout LibraryScopeState) -> Void) {
        var state = scopeStates[scope] ?? LibraryScopeState()
        update(&state)
        scopeStates[scope] = state
    }

    private func sharedScope(_ scope: LibraryScope) -> ErmaoShared.LibraryScope {
        switch scope {
        case .works: .works
        case .series: .series
        case .authors: .authors
        }
    }

    private func sharedSort(_ sort: LibrarySort) -> ErmaoShared.LibrarySort {
        switch sort {
        case .recentAdded: .recentlyadded
        case .recentRead: .recentlyread
        case .title: .title
        case .author: .author
        }
    }

    private func sharedFilters(_ filters: LibraryFilters) -> ErmaoShared.LibraryFilters {
        ErmaoShared.PublicKt.createLibraryFilters(
            mediaKindWireValues: filters.mediaKinds.map(\.rawValue),
            readingStatuses: Set(filters.readingStatuses.map { status in
                switch status {
                case .unread: ErmaoShared.ReadingStatus.unread
                case .reading: ErmaoShared.ReadingStatus.reading
                case .finished: ErmaoShared.ReadingStatus.finished
                }
            })
        )
    }
}

private extension LibraryScopeState {
    var readyItems: [LibraryResultItem]? {
        guard case .ready(let items, _, _, _) = results else { return nil }
        return items
    }
}

enum FacetLoadState: Sendable {
    case loading
    case ready(FacetPage, isCached: Bool)
    case empty(FacetIdentity)
    case inaccessible
    case failure
}

@MainActor
final class FacetStore: ObservableObject {
    @Published private(set) var state: FacetLoadState = .loading
    @Published private(set) var isLoadingNextPage = false
    @Published private(set) var hasPaginationError = false
    @Published private(set) var cacheIssue: ContentCacheIssue?

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let cache: LibraryCacheStore
    private let kind: FacetKind
    private let facetID: String
    private let onUnauthorized: @MainActor () -> Void
    private var requestGeneration = UUID()

    init(context: ContentRequestContext, client: any ContentClient, cache: LibraryCacheStore, kind: FacetKind, facetID: String, onUnauthorized: @escaping @MainActor () -> Void) {
        self.context = context
        self.client = client
        self.cache = cache
        self.kind = kind
        self.facetID = facetID
        self.onUnauthorized = onUnauthorized
    }

    func load() {
        state = .loading
        let generation = UUID()
        requestGeneration = generation
        Task { [weak self] in await self?.loadPage(1, generation: generation) }
    }

    func loadNextPageIfNeeded(workID: String) {
        guard case .ready(let page, _) = state,
              page.page < page.totalPages,
              page.works.suffix(6).contains(where: { $0.id == workID }),
              !isLoadingNextPage else { return }
        isLoadingNextPage = true
        hasPaginationError = false
        let generation = requestGeneration
        Task { [weak self] in await self?.loadPage(page.page + 1, generation: generation) }
    }

    func retry() {
        if case .ready(let page, _) = state, hasPaginationError {
            isLoadingNextPage = true
            let generation = requestGeneration
            Task { [weak self] in await self?.loadPage(page.page + 1, generation: generation) }
        } else {
            load()
        }
    }

    private func loadPage(_ page: Int, generation: UUID) async {
        do {
            let fetched = try await client.fetchFacetResult(
                context: context,
                query: FacetQuery(
                    kind: kind,
                    facetID: facetID,
                    sort: kind == .series ? .seriesIndex : .recentRead,
                    page: page,
                    pageSize: 24
                )
            )
            guard requestGeneration == generation else { return }
            apply(fetched.value, appending: page > 1, isCached: false)
        } catch {
            guard requestGeneration == generation else { return }
            if case ContentClientError.unauthorized = error { onUnauthorized(); return }
            if case ContentClientError.inaccessible = error {
                do { try await cache.removeNamespace(context.namespaceKey) }
                catch { cacheIssue = .purgeFailed }
                state = .inaccessible
                return
            }
            if page > 1 {
                isLoadingNextPage = false
                hasPaginationError = true
            } else {
                state = .failure
            }
        }
    }

    private func apply(_ result: FacetPage, appending: Bool, isCached: Bool) {
        var result = result
        if appending, case .ready(let previous, _) = state {
            var ids = Set(previous.works.map(\.id))
            result = FacetPage(
                facet: result.facet,
                works: previous.works + result.works.filter { ids.insert($0.id).inserted },
                page: result.page,
                pageSize: result.pageSize,
                total: result.total,
                totalPages: result.totalPages
            )
        }
        state = result.works.isEmpty ? .empty(result.facet) : .ready(result, isCached: isCached)
        isLoadingNextPage = false
        hasPaginationError = false
    }
}

enum WorkDetailLoadState: Sendable {
    case loading
    case ready(WorkDetailContent, isCached: Bool)
    case inaccessible
    case failure
}

@MainActor
final class WorkDetailStore: ObservableObject {
    @Published private(set) var state: WorkDetailLoadState = .loading
    @Published private(set) var cacheIssue: ContentCacheIssue?
    @Published private(set) var isLoadingMoreVolumes = false
    @Published private(set) var hasVolumePaginationError = false

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let cache: LibraryCacheStore
    private let workID: String
    var workIDValue: String { workID }
    private let onUnauthorized: @MainActor () -> Void
    private var requestGeneration = UUID()
    private var activeVersionId: String?
    private var activeVolumeID: String?
    private var latestProgressUpdatesByVolumeID: [String: ErmaoShared.ReaderProgressPresentationUpdate] = [:]
    private var cancellables: Set<AnyCancellable> = []

    init(context: ContentRequestContext, client: any ContentClient, cache: LibraryCacheStore, workID: String, onUnauthorized: @escaping @MainActor () -> Void) {
        self.context = context
        self.client = client
        self.cache = cache
        self.workID = workID
        self.onUnauthorized = onUnauthorized
        ReaderProgressPresentationCenter.shared.updates
            .filter { $0.namespaceKey == context.namespaceKey && $0.workId == workID }
            .sink { [weak self] update in self?.apply(update) }
            .store(in: &cancellables)
    }

    func load(
        versionId: String? = nil,
        volumeID: String? = nil,
        showBlockingLoading: Bool = true
    ) {
        activeVersionId = versionId
        activeVolumeID = volumeID
        if showBlockingLoading || currentContent == nil { state = .loading }
        let generation = UUID()
        requestGeneration = generation
        Task { [weak self] in
            guard let self else { return }
            do {
                let value = try await client.fetchWorkDetail(
                    context: context,
                    query: WorkDetailQuery(workID: workID, versionId: versionId, volumeID: volumeID)
                )
                guard requestGeneration == generation else { return }
                let latestProgressUpdate = value.selectedVolumeID
                    .flatMap { latestProgressUpdatesByVolumeID[$0] }
                let presented = latestProgressUpdate.map { value.applying($0) } ?? value
                state = .ready(presented, isCached: false)
            } catch {
                guard requestGeneration == generation else { return }
                if case ContentClientError.unauthorized = error { onUnauthorized(); return }
                if case ContentClientError.inaccessible = error {
                    do { try await cache.removeNamespace(context.namespaceKey) }
                    catch { cacheIssue = .purgeFailed }
                    state = .inaccessible
                    return
                }
                state = .failure
            }
        }
    }

    func refreshIfLoaded() {
        guard currentContent != nil else { return }
        load(versionId: activeVersionId, volumeID: activeVolumeID, showBlockingLoading: false)
    }

    func loadMoreVolumes() {
        guard !isLoadingMoreVolumes,
              let content = currentContent,
              content.volumes.count < content.volumeCount,
              let versionId = content.selectedVersionId ?? content.volumes.first?.versionID
        else { return }
        let pageSize = 24
        let nextPage = content.volumes.count / pageSize + 1
        let requestedVersionId = versionId
        isLoadingMoreVolumes = true
        hasVolumePaginationError = false
        Task { [weak self] in
            guard let self else { return }
            do {
                let page = try await client.fetchWorkVolumes(
                    context: context,
                    workID: workID,
                    versionId: versionId,
                    page: nextPage,
                    pageSize: pageSize
                )
                guard case .ready(let current, let isCached) = state else {
                    isLoadingMoreVolumes = false
                    return
                }
                guard current.selectedVersionId == requestedVersionId,
                      current.volumes.first?.versionID == versionId else {
                    isLoadingMoreVolumes = false
                    return
                }
                state = .ready(current.appending(page), isCached: isCached)
                isLoadingMoreVolumes = false
            } catch {
                isLoadingMoreVolumes = false
                if currentContent?.selectedVersionId == requestedVersionId,
                   currentContent?.volumes.first?.versionID == versionId {
                    hasVolumePaginationError = true
                }
            }
        }
    }

    private var currentContent: WorkDetailContent? {
        guard case .ready(let content, _) = state else { return nil }
        return content
    }

    private func apply(_ update: ErmaoShared.ReaderProgressPresentationUpdate) {
        let previous = latestProgressUpdatesByVolumeID[update.volumeId]
        guard update.capturedAtEpochMillis >= (previous?.capturedAtEpochMillis ?? -1) else { return }
        latestProgressUpdatesByVolumeID[update.volumeId] = update
        guard case .ready(let content, let isCached) = state else { return }
        guard content.selectedVolumeID == update.volumeId else { return }
        let presented = content.applying(update)
        state = .ready(presented, isCached: isCached)
    }
}

private extension WorkDetailContent {
    func appending(_ page: WorkVolumePage) -> WorkDetailContent {
        var seen = Set(volumes.map(\.id))
        let merged = (volumes + page.volumes.filter { seen.insert($0.id).inserted })
            .sorted { lhs, rhs in
                lhs.sortOrder == rhs.sortOrder ? lhs.id < rhs.id : lhs.sortOrder < rhs.sortOrder
            }
        return WorkDetailContent(
            work: work,
            description: description,
            tags: tags,
            seriesFacet: seriesFacet,
            seriesIndex: seriesIndex,
            authorFacets: authorFacets,
            versions: versions.map { version in
                guard version.id == selectedVersionId else { return version }
                return WorkVersionContent(
                    id: version.id,
                    sourceKey: version.sourceKey,
                    sourceName: version.sourceName,
                    volumes: merged,
                    volumeCount: page.total
                )
            },
            selectedVersionId: selectedVersionId,
            selectedVolumeID: selectedVolumeID,
            readingStatus: readingStatus,
            volumes: merged,
            volumeCount: page.total,
            chapters: chapters
        )
    }

    func applying(_ update: ErmaoShared.ReaderProgressPresentationUpdate) -> WorkDetailContent {
        guard work.id == update.workId,
              selectedVolumeID == update.volumeId,
              volumes.contains(where: { $0.id == update.volumeId })
        else { return self }
        let updatedWork = WorkCard(
            id: work.id,
            title: work.title,
            author: work.author,
            cover: work.cover,
            progress: update.percent,
            availableMediaKinds: work.availableMediaKinds
        )
        let updatedVolumes = volumes.map { volume in
            guard volume.id == update.volumeId else { return volume }
            return WorkVolume(
                id: volume.id,
                versionID: volume.versionID,
                title: volume.title,
                formatLabel: volume.formatLabel,
                readerType: volume.readerType,
                suggestedMediaKind: volume.suggestedMediaKind,
                volumeIndex: volume.volumeIndex,
                cover: volume.cover,
                sizeLabel: volume.sizeLabel,
                progress: update.percent,
                isReadable: volume.isReadable,
                isSelected: volume.isSelected,
                sortOrder: volume.sortOrder,
                publisher: volume.publisher,
                publishedAt: volume.publishedAt,
                language: volume.language,
                isbn: volume.isbn,
                identifier: volume.identifier,
                narrator: volume.narrator,
                pageCount: volume.pageCount,
                metadataSource: volume.metadataSource,
                kindleSendAvailable: volume.kindleSendAvailable,
                files: volume.files
            )
        }
        let readerChapterUnits: [ErmaoShared.ReaderChapterUnit] = chapters.map {
            ErmaoShared.ReaderChapterUnit(
                href: $0.href,
                sortOrder: Int32($0.sortOrder),
                readingOrderPosition: $0.readingOrderPosition.map {
                    KotlinInt(int: Int32($0))
                }
            )
        }
        let states = ErmaoShared.PublicKt.resolveReaderChapterStatesFromLocation(
            units: readerChapterUnits,
            location: update.location,
            progressPercent: update.percent
        )
        let updatedChapters = chapters.enumerated().map { index, chapter in
            let state: WorkChapterReadingState = switch states[index] {
            case .current: .current
            case .read: .read
            default: .unread
            }
            return WorkChapter(
                id: chapter.id,
                title: chapter.title,
                progress: state == .current ? update.percent : nil,
                isCurrent: state == .current,
                href: chapter.href,
                sortOrder: chapter.sortOrder,
                readingOrderPosition: chapter.readingOrderPosition,
                state: state
            )
        }
        return WorkDetailContent(
            work: updatedWork,
            description: description,
            tags: tags,
            seriesFacet: seriesFacet,
            seriesIndex: seriesIndex,
            authorFacets: authorFacets,
            versions: versions.map { version in
                WorkVersionContent(
                    id: version.id,
                    sourceKey: version.sourceKey,
                    sourceName: version.sourceName,
                    volumes: version.id == selectedVersionId ? updatedVolumes : version.volumes,
                    volumeCount: version.volumeCount
                )
            },
            selectedVersionId: selectedVersionId,
            selectedVolumeID: selectedVolumeID,
            readingStatus: update.percent >= 100 ? .finished : .reading,
            volumes: updatedVolumes,
            volumeCount: volumeCount,
            chapters: updatedChapters
        )
    }
}
