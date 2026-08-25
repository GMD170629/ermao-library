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
    @Published private(set) var recentReading: HomeSectionState<[BookCard]> = .loading
    @Published private(set) var recentAdded: HomeSectionState<[BookCard]> = .loading
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
    case book(BookCard)
    case grouping(LibraryGrouping)

    var id: String {
        switch self {
        case .book(let value): "book:\(value.id)"
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
    @Published private(set) var selectedScope: LibraryScope = .books
    @Published private(set) var libraryOptions: [LibrarySourceOption] = []
    @Published private(set) var selectedLibraryID: String?
    @Published private(set) var cacheIssue: ContentCacheIssue?
    @Published private(set) var scopeStates: [LibraryScope: LibraryScopeState] = [
        .books: LibraryScopeState(),
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

    func selectLibrary(_ libraryID: String?) {
        guard selectedLibraryID != libraryID else { return }
        selectedLibraryID = libraryID
        reload()
    }

    func loadLibraryOptionsIfNeeded() {
        guard libraryOptions.isEmpty else { return }
        Task { [weak self] in
            guard let self else { return }
            do {
                let options = try await client.fetchLibraryOptions(context: context)
                libraryOptions = options
                if let selectedLibraryID, !options.contains(where: { $0.id == selectedLibraryID }) {
                    self.selectedLibraryID = nil
                    reload()
                }
            } catch ContentClientError.unauthorized {
                onUnauthorized()
            } catch {
                // The unfiltered library remains usable if source labels cannot be loaded.
            }
        }
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
        guard selectedScope == .books else { return }
        guard current.sort != sort else { return }
        discoveryRuntime.updateSort(scope: .books, sort: sharedSort(sort))
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
        guard selectedScope == .books, !filters.downloadedOnly else { return }
        guard discoveryRuntime.applyFilters(filters: sharedFilters(filters)) is ErmaoShared.FilterCommitResultApplied
        else { return }
        updateCurrent { $0.filters = filters }
        reload()
    }

    func removeReadingFilter(_ readingStatus: LibraryReadingStatus) {
        var filters = current.filters
        if filters.readingStatus == readingStatus { filters.readingStatus = nil }
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
        case books(BookPage)
        case groupings(GroupingPage)

        var isEmpty: Bool {
            switch self {
            case .books(let page): page.books.isEmpty
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
        case .books:
            let result = try await client.fetchBooksResult(
                    context: context,
                    query: BooksQuery(
                        query: state.query,
                        libraryID: selectedLibraryID,
                        sort: state.sort,
                        filters: state.filters,
                        page: page,
                        pageSize: 24
                    )
                )
            return PageFetch(
                response: .books(result.value),
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
        case .books(let value):
            nextItems = value.books.map(LibraryResultItem.book)
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
        let reading = state.filters.readingStatus?.rawValue ?? ""
        return "library|\(scope.rawValue)|\(selectedLibraryID ?? "all")|\(state.query)|\(state.sort.rawValue)|\(state.viewMode.rawValue)|\(reading)|\(state.filters.downloadedOnly)|\(page)"
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
        case .books: .books
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
            readingStatus: filters.readingStatus.map { status in
                switch status {
                case .unread: ErmaoShared.ReadingStatus.unread
                case .reading: ErmaoShared.ReadingStatus.reading
                case .finished: ErmaoShared.ReadingStatus.finished
                }
            }
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

    func loadNextPageIfNeeded(bookID: String) {
        guard case .ready(let page, _) = state,
              page.page < page.totalPages,
              page.books.suffix(6).contains(where: { $0.id == bookID }),
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
            var ids = Set(previous.books.map(\.id))
            result = FacetPage(
                facet: result.facet,
                books: previous.books + result.books.filter { ids.insert($0.id).inserted },
                page: result.page,
                pageSize: result.pageSize,
                total: result.total,
                totalPages: result.totalPages
            )
        }
        state = result.books.isEmpty ? .empty(result.facet) : .ready(result, isCached: isCached)
        isLoadingNextPage = false
        hasPaginationError = false
    }
}

enum BookDetailLoadState: Sendable {
    case loading
    case ready(BookDetailContent, isCached: Bool)
    case inaccessible
    case failure
}

@MainActor
final class BookDetailStore: ObservableObject {
    @Published private(set) var state: BookDetailLoadState = .loading
    @Published private(set) var cacheIssue: ContentCacheIssue?
    @Published private(set) var contentsPage: BookContentsPage?
    @Published private(set) var chapterPage: BookChapterPage?
    @Published private(set) var isLoadingContentBrowser = false
    @Published private(set) var contentBrowserFailed = false
    @Published private(set) var isLoadingMoreResources = false
    @Published private(set) var hasResourcePaginationError = false
    @Published private(set) var hasMoreResources = true

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let cache: LibraryCacheStore
    private let bookID: String
    var bookIDValue: String { bookID }
    private let onUnauthorized: @MainActor () -> Void
    private var requestGeneration = UUID()
    private var activeResourceID: String?
    private var latestProgressUpdatesByResourceID: [String: ErmaoShared.ReaderProgressPresentationUpdate] = [:]
    private var cancellables: Set<AnyCancellable> = []

    init(context: ContentRequestContext, client: any ContentClient, cache: LibraryCacheStore, bookID: String, onUnauthorized: @escaping @MainActor () -> Void) {
        self.context = context
        self.client = client
        self.cache = cache
        self.bookID = bookID
        self.onUnauthorized = onUnauthorized
        ReaderProgressPresentationCenter.shared.updates
            .filter { $0.namespaceKey == context.namespaceKey && $0.bookId == bookID }
            .sink { [weak self] update in self?.apply(update) }
            .store(in: &cancellables)
    }

    func load(resourceID: String? = nil, showBlockingLoading: Bool = true) {
        activeResourceID = resourceID
        hasMoreResources = true
        if showBlockingLoading || currentContent == nil {
            state = .loading
            contentsPage = nil
            chapterPage = nil
        }
        let generation = UUID()
        requestGeneration = generation
        Task { [weak self] in
            guard let self else { return }
            do {
                let value = try await client.fetchBookDetail(
                    context: context,
                    query: BookDetailQuery(bookID: bookID, resourceID: resourceID)
                )
                guard requestGeneration == generation else { return }
                let latestProgressUpdate = value.selectedResourceID
                    .flatMap { latestProgressUpdatesByResourceID[$0] }
                let presented = latestProgressUpdate.map { value.applying($0) } ?? value
                state = .ready(presented, isCached: false)
                await loadContentBrowser(for: presented, generation: generation)
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
        load(resourceID: activeResourceID, showBlockingLoading: false)
    }

    func loadMoreResources() {
        guard !isLoadingMoreResources,
              hasMoreResources,
              let content = currentContent,
              !content.resources.isEmpty
        else { return }
        let pageSize = 24
        let nextPage = content.resources.count / pageSize + 1
        isLoadingMoreResources = true
        hasResourcePaginationError = false
        Task { [weak self] in
            guard let self else { return }
            do {
                let page = try await client.fetchBookResources(
                    context: context,
                    bookID: bookID,
                    page: nextPage,
                    pageSize: pageSize
                )
                guard case .ready(let current, let isCached) = state else {
                    isLoadingMoreResources = false
                    return
                }
                state = .ready(current.appending(page), isCached: isCached)
                hasMoreResources = page.page < page.totalPages && !page.resources.isEmpty
                isLoadingMoreResources = false
            } catch {
                isLoadingMoreResources = false
                hasResourcePaginationError = true
            }
        }
    }

    func openContents(_ sourceNodeID: String?) {
        guard currentContent != nil else { return }
        let generation = requestGeneration
        isLoadingContentBrowser = true
        contentBrowserFailed = false
        Task { [weak self] in
            guard let self else { return }
            do {
                let page = try await client.fetchBookContents(
                    context: context,
                    bookID: bookID,
                    sourceNodeID: sourceNodeID,
                    page: 1,
                    pageSize: 200
                )
                guard requestGeneration == generation else { return }
                contentsPage = page
                isLoadingContentBrowser = false
            } catch {
                guard requestGeneration == generation else { return }
                isLoadingContentBrowser = false
                contentBrowserFailed = true
            }
        }
    }

    func retryContentBrowser() {
        guard let content = currentContent else { return }
        if content.resources.filter({ $0.isReadable != false }).count == 1 {
            let generation = requestGeneration
            Task { [weak self] in
                guard let self else { return }
                await loadContentBrowser(for: content, generation: generation, force: true)
            }
        } else {
            openContents(contentsPage?.currentSourceNodeID)
        }
    }

    private func loadContentBrowser(
        for content: BookDetailContent,
        generation: UUID,
        force: Bool = false
    ) async {
        let readableResources = content.resources.filter { $0.isReadable != false }
        isLoadingContentBrowser = true
        contentBrowserFailed = false
        do {
            if readableResources.count == 1, let resource = readableResources.first {
                if !force, chapterPage?.resourceID == resource.id {
                    isLoadingContentBrowser = false
                    return
                }
                let page = try await client.fetchBookChapters(
                    context: context,
                    bookID: bookID,
                    resourceID: resource.id,
                    page: 1,
                    pageSize: 500
                )
                guard requestGeneration == generation else { return }
                chapterPage = page
                contentsPage = nil
                if case .ready(let current, let isCached) = state {
                    state = .ready(current.replacingChapters(page.chapters), isCached: isCached)
                }
            } else {
                if !force, contentsPage != nil {
                    isLoadingContentBrowser = false
                    return
                }
                let page = try await client.fetchBookContents(
                    context: context,
                    bookID: bookID,
                    sourceNodeID: nil,
                    page: 1,
                    pageSize: 200
                )
                guard requestGeneration == generation else { return }
                contentsPage = page
                chapterPage = nil
            }
            isLoadingContentBrowser = false
        } catch {
            guard requestGeneration == generation else { return }
            isLoadingContentBrowser = false
            contentBrowserFailed = true
        }
    }

    private var currentContent: BookDetailContent? {
        guard case .ready(let content, _) = state else { return nil }
        return content
    }

    private func apply(_ update: ErmaoShared.ReaderProgressPresentationUpdate) {
        let previous = latestProgressUpdatesByResourceID[update.resourceId]
        guard update.capturedAtEpochMillis >= (previous?.capturedAtEpochMillis ?? -1) else { return }
        latestProgressUpdatesByResourceID[update.resourceId] = update
        guard case .ready(let content, let isCached) = state else { return }
        guard content.selectedResourceID == update.resourceId else { return }
        let presented = content.applying(update)
        state = .ready(presented, isCached: isCached)
    }
}

private extension BookDetailContent {
    func replacingChapters(_ chapters: [BookChapter]) -> BookDetailContent {
        BookDetailContent(
            book: book,
            description: description,
            tags: tags,
            seriesFacet: seriesFacet,
            seriesIndex: seriesIndex,
            authorFacets: authorFacets,
            resources: resources,
            selectedResourceID: selectedResourceID,
            readingStatus: readingStatus,
            chapters: chapters
        )
    }

    func appending(_ page: BookResourcePage) -> BookDetailContent {
        var seen = Set(resources.map(\.id))
        let merged = (resources + page.resources.filter { seen.insert($0.id).inserted })
            .sorted { lhs, rhs in
                lhs.sortOrder == rhs.sortOrder ? lhs.id < rhs.id : lhs.sortOrder < rhs.sortOrder
            }
        return BookDetailContent(
            book: book,
            description: description,
            tags: tags,
            seriesFacet: seriesFacet,
            seriesIndex: seriesIndex,
            authorFacets: authorFacets,
            resources: merged,
            selectedResourceID: selectedResourceID,
            readingStatus: readingStatus,
            chapters: chapters
        )
    }

    func applying(_ update: ErmaoShared.ReaderProgressPresentationUpdate) -> BookDetailContent {
        guard book.id == update.bookId,
              selectedResourceID == update.resourceId,
              resources.contains(where: { $0.id == update.resourceId })
        else { return self }
        let updatedBook = BookCard(
            id: book.id,
            title: book.title,
            author: book.author,
            cover: book.cover,
            progress: update.percent
        )
        let updatedResources = resources.map { resource in
            guard resource.id == update.resourceId else { return resource }
            return BookResource(
                id: resource.id,
                bookID: resource.bookID,
                sourceNodeID: resource.sourceNodeID,
                title: resource.title,
                description: resource.description,
                format: resource.format,
                readerType: resource.readerType,
                resourceIndex: resource.resourceIndex,
                cover: resource.cover,
                sizeLabel: resource.sizeLabel,
                progress: update.percent,
                isReadable: resource.isReadable,
                isSelected: resource.isSelected,
                sortOrder: resource.sortOrder,
                publisher: resource.publisher,
                publishedAt: resource.publishedAt,
                language: resource.language,
                isbn: resource.isbn,
                identifier: resource.identifier,
                narrator: resource.narrator,
                pageCount: resource.pageCount,
                metadataSource: resource.metadataSource,
                kindleSendAvailable: resource.kindleSendAvailable,
                assets: resource.assets
            )
        }
        let currentChapterIndex = update.chapterTitle.flatMap { chapterTitle in
            chapters.firstIndex { chapter in
                chapter.title.compare(
                    chapterTitle,
                    options: [.caseInsensitive, .diacriticInsensitive]
                ) == .orderedSame
            }
        }
        let updatedChapters = chapters.enumerated().map { index, chapter in
            guard let currentChapterIndex else { return chapter }
            let state: ChapterReadingState = if index < currentChapterIndex {
                .read
            } else if index == currentChapterIndex {
                .current
            } else {
                .unread
            }
            return BookChapter(
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
        return BookDetailContent(
            book: updatedBook,
            description: description,
            tags: tags,
            seriesFacet: seriesFacet,
            seriesIndex: seriesIndex,
            authorFacets: authorFacets,
            resources: updatedResources,
            selectedResourceID: selectedResourceID,
            readingStatus: update.percent >= 100 ? .finished : .reading,
            chapters: updatedChapters
        )
    }
}
