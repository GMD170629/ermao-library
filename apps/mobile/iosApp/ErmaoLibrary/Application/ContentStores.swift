import Foundation
import Combine
@preconcurrency import ErmaoShared

enum HomeSectionState<Value: Sendable>: Sendable {
    case loading
    case content(Value)
    case empty
    case failure
}

@MainActor
final class HomeStore: ObservableObject {
    @Published private(set) var continueReading: HomeSectionState<ContinueReadingItem> = .loading
    @Published private(set) var recentReading: HomeSectionState<[BookCard]> = .loading
    @Published private(set) var recentAdded: HomeSectionState<[BookCard]> = .loading

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let onUnauthorized: @MainActor () -> Void
    private var continueGeneration = UUID()
    private var recentReadingGeneration = UUID()
    private var recentAddedGeneration = UUID()

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        onUnauthorized: @escaping @MainActor () -> Void
    ) {
        self.context = context
        self.client = client
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
                continueReading = .content(value)
            } else {
                continueReading = .empty
            }
        } catch {
            guard continueGeneration == generation else { return }
            if handleUnauthorized(error) { return }
            if handleInaccessible(error) { continueReading = .failure; return }
            continueReading = .failure
        }
    }

    private func loadRecentReading(generation: UUID) async {
        recentReading = .loading
        do {
            let values = try await client.fetchRecentReading(context: context, limit: 12)
            guard recentReadingGeneration == generation else { return }
            recentReading = values.isEmpty ? .empty : .content(values)
        } catch {
            guard recentReadingGeneration == generation else { return }
            if handleUnauthorized(error) { return }
            if handleInaccessible(error) { recentReading = .failure; return }
            recentReading = .failure
        }
    }

    private func loadRecentAdded(generation: UUID) async {
        recentAdded = .loading
        do {
            let values = try await client.fetchRecentAdded(context: context, limit: 12)
            guard recentAddedGeneration == generation else { return }
            recentAdded = values.isEmpty ? .empty : .content(values)
        } catch {
            guard recentAddedGeneration == generation else { return }
            if handleUnauthorized(error) { return }
            if handleInaccessible(error) { recentAdded = .failure; return }
            recentAdded = .failure
        }
    }

    private func handleUnauthorized(_ error: Error) -> Bool {
        guard case ContentClientError.unauthorized = error else { return false }
        onUnauthorized()
        return true
    }

    private func handleInaccessible(_ error: Error) -> Bool {
        guard case ContentClientError.inaccessible = error else { return false }
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
    case ready(items: [LibraryResultItem], total: Int)
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
    @Published private(set) var scopeStates: [LibraryScope: LibraryScopeState] = [
        .books: LibraryScopeState(),
        .series: LibraryScopeState(),
        .authors: LibraryScopeState(),
    ]

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let onUnauthorized: @MainActor () -> Void
    private let discoveryRuntime = ErmaoShared.LibraryDiscoveryRuntime()
    private var searchTask: Task<Void, Never>?

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        onUnauthorized: @escaping @MainActor () -> Void
    ) {
        self.context = context
        self.client = client
        self.onUnauthorized = onUnauthorized
    }

    deinit {
        searchTask?.cancel()
    }

    var current: LibraryScopeState { scopeStates[selectedScope] ?? LibraryScopeState() }

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
        guard selectedScope == .books else { return }
        discoveryRuntime.applyFilters(filters: sharedFilters(filters))
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
        let token = discoveryRuntime.beginInitialRequest(scope: sharedScope(scope))
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
        update(scope) {
            $0.results = .loading
            $0.loadedPage = 0
            $0.totalPages = 1
            $0.isLoadingNextPage = false
            $0.hasPaginationError = false
            $0.paginationRequestKey = nil
        }
        let token = discoveryRuntime.beginInitialRequest(scope: sharedScope(scope))
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
            let response = try await fetch(scope: scope, state: state, page: page)
            guard discoveryRuntime.acceptPage(
                token: token,
                isEmpty: response.isEmpty
            ) else { return }
            apply(response, scope: scope, page: page)
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
                update(scope) {
                    $0.results = .inaccessible
                    $0.isLoadingNextPage = false
                    $0.paginationRequestKey = nil
                }
                return
            }
            if page > 1 {
                _ = discoveryRuntime.fail(token: token, errorCode: "CONTENT_LOAD_FAILED")
                update(scope) {
                    $0.isLoadingNextPage = false
                    $0.hasPaginationError = true
                    $0.paginationRequestKey = nil
                }
            } else {
                _ = discoveryRuntime.fail(token: token, errorCode: "CONTENT_LOAD_FAILED")
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

    private func fetch(scope: LibraryScope, state: LibraryScopeState, page: Int) async throws -> PageResponse {
        switch scope {
        case .books:
            let result = try await client.fetchBooks(
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
            return .books(result)
        case .series, .authors:
            let result = try await client.fetchGroupings(
                context: context,
                query: GroupingsQuery(
                    kind: scope == .series ? .series : .author,
                    query: state.query,
                    page: page,
                    pageSize: 30
                )
            )
            return .groupings(result)
        }
    }

    private func apply(_ response: PageResponse, scope: LibraryScope, page: Int) {
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
                : .ready(items: merged, total: total)
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

    private func queryRequestKey(scope: LibraryScope, state: LibraryScopeState, page: Int) -> String {
        let reading = state.filters.readingStatus?.rawValue ?? ""
        return "library|\(scope.rawValue)|\(selectedLibraryID ?? "all")|\(state.query)|\(state.sort.rawValue)|\(state.viewMode.rawValue)|\(reading)|\(page)"
    }

    private func paginationRequestKey(scope: LibraryScope, state: LibraryScopeState, page: Int) -> String {
        queryRequestKey(scope: scope, state: state, page: page)
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
        guard case .ready(let items, _) = results else { return nil }
        return items
    }
}

enum FacetLoadState: Sendable {
    case loading
    case ready(FacetPage)
    case empty(FacetIdentity)
    case inaccessible
    case failure
}

@MainActor
final class FacetStore: ObservableObject {
    @Published private(set) var state: FacetLoadState = .loading
    @Published private(set) var isLoadingNextPage = false
    @Published private(set) var hasPaginationError = false

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let kind: FacetKind
    private let facetID: String
    private let onUnauthorized: @MainActor () -> Void
    private var requestGeneration = UUID()

    init(context: ContentRequestContext, client: any ContentClient, kind: FacetKind, facetID: String, onUnauthorized: @escaping @MainActor () -> Void) {
        self.context = context
        self.client = client
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
        guard case .ready(let page) = state,
              page.page < page.totalPages,
              page.books.suffix(6).contains(where: { $0.id == bookID }),
              !isLoadingNextPage else { return }
        isLoadingNextPage = true
        hasPaginationError = false
        let generation = requestGeneration
        Task { [weak self] in await self?.loadPage(page.page + 1, generation: generation) }
    }

    func retry() {
        if case .ready(let page) = state, hasPaginationError {
            isLoadingNextPage = true
            let generation = requestGeneration
            Task { [weak self] in await self?.loadPage(page.page + 1, generation: generation) }
        } else {
            load()
        }
    }

    private func loadPage(_ page: Int, generation: UUID) async {
        do {
            let fetched = try await client.fetchFacet(
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
            apply(fetched, appending: page > 1)
        } catch {
            guard requestGeneration == generation else { return }
            if case ContentClientError.unauthorized = error { onUnauthorized(); return }
            if case ContentClientError.inaccessible = error {
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

    private func apply(_ result: FacetPage, appending: Bool) {
        var result = result
        if appending, case .ready(let previous) = state {
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
        state = result.books.isEmpty ? .empty(result.facet) : .ready(result)
        isLoadingNextPage = false
        hasPaginationError = false
    }
}

enum BookDetailLoadState: Sendable {
    case loading
    case ready(BookDetailContent)
    case inaccessible
    case failure
}

@MainActor
final class BookDetailStore: ObservableObject {
    let destination: BookContentDestination
    var isBookRoot: Bool { destination == .root }
    @Published private(set) var state: BookDetailLoadState = .loading
    @Published private(set) var contentsPage: BookContentsPage?
    @Published private(set) var chapterPage: BookChapterPage?
    @Published private(set) var resourceDetailPage: BookResourceDetailPage?
    @Published private(set) var viewState = BookContentViewState()
    var contentSort: BookContentSort { viewState.sort }
    var contentLayout: BookContentLayout { viewState.layout }
    @Published private(set) var isLoadingContentBrowser = false
    @Published private(set) var contentBrowserFailed = false
    @Published private(set) var isLoadingMoreResources = false
    @Published private(set) var hasResourcePaginationError = false
    @Published private(set) var hasMoreResources = true

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let bookID: String
    var bookIDValue: String { bookID }
    private let onUnauthorized: @MainActor () -> Void
    private var requestGeneration = UUID()
    private var activeResourceID: String?
    var selectedResourceID: String? { activeResourceID }
    private var latestProgressUpdatesByResourceID: [String: ErmaoShared.ReaderProgressPresentationUpdate] = [:]
    private var cancellables: Set<AnyCancellable> = []

    init(context: ContentRequestContext, client: any ContentClient, bookID: String, destination: BookContentDestination = .root, onUnauthorized: @escaping @MainActor () -> Void) {
        self.context = context
        self.client = client
        self.bookID = bookID
        self.destination = destination
        self.onUnauthorized = onUnauthorized
        ReaderProgressPresentationCenter.shared.updates
            .filter { $0.namespaceKey == context.namespaceKey && $0.bookId == bookID }
            .sink { [weak self] update in self?.apply(update) }
            .store(in: &cancellables)
    }

    func load(resourceID: String? = nil, showBlockingLoading: Bool = true) {
        activeResourceID = resourceID ?? destination.resourceID
        hasMoreResources = true
        if showBlockingLoading || currentContent == nil {
            state = .loading
            contentsPage = nil
            chapterPage = nil
            resourceDetailPage = nil
        }
        let generation = UUID()
        requestGeneration = generation
        Task { [weak self] in
            guard let self else { return }
            do {
                let value = try await client.fetchBookDetail(
                    context: context,
                    query: BookDetailQuery(bookID: bookID, resourceID: activeResourceID)
                )
                guard requestGeneration == generation else { return }
                let presented = applyingLatestProgress(to: value)
                state = .ready(presented)
                await loadContentBrowser(generation: generation)
            } catch {
                guard requestGeneration == generation else { return }
                if case ContentClientError.unauthorized = error { onUnauthorized(); return }
                if case ContentClientError.inaccessible = error {
                    state = .inaccessible
                    return
                }
                if currentContent == nil { state = .failure } else { contentBrowserFailed = true }
            }
        }
    }

    func refreshIfLoaded() {
        guard currentContent != nil, !isLoadingContentBrowser else { return }
        load(showBlockingLoading: false)
    }

    func refreshAfterReadingStatusChange(resourceID: String) {
        latestProgressUpdatesByResourceID.removeValue(forKey: resourceID)
        load(showBlockingLoading: false)
    }

    func refreshAfterBookReadingStatusChange() {
        latestProgressUpdatesByResourceID.removeAll()
        load(showBlockingLoading: false)
    }

    func loadIfNeeded() {
        guard currentContent == nil else { return }
        load()
    }

    func restoreViewState(_ value: BookContentViewState) {
        guard currentContent == nil, value.isValid else { return }
        viewState = value
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
                guard case .ready(let current) = state else {
                    isLoadingMoreResources = false
                    return
                }
                state = .ready(current.appending(page))
                hasMoreResources = page.page < page.totalPages && !page.resources.isEmpty
                isLoadingMoreResources = false
            } catch {
                isLoadingMoreResources = false
                hasResourcePaginationError = true
            }
        }
    }

    func selectContentSort(_ sort: BookContentSort) {
        guard contentSort != sort else { return }
        viewState.sort = sort
        viewState.page = 1
        loadContents(sourceNodeID: contentsPage?.currentSourceNodeID ?? destination.sourceNodeID, page: viewState.page)
    }

    func selectContentLayout(_ layout: BookContentLayout) {
        viewState.layout = layout
    }

    func selectContentPage(_ page: Int) {
        guard page > 0 else { return }
        viewState.page = page
        loadContents(sourceNodeID: contentsPage?.currentSourceNodeID, page: page)
    }

    func selectResourceDetailPage(_ page: Int) {
        guard page > 0 else { return }
        viewState.readingUnitsPage = page
        guard let resourceID = activeResourceID else { return }
        loadResourceDetail(resourceID: resourceID, page: page)
    }

    func retryContentBrowser() {
        guard currentContent != nil else { return }
        if destination == .root && contentsPage == nil {
            load(showBlockingLoading: false)
            return
        }
        if let resourceID = activeResourceID {
            if currentContent?.resources.contains(where: { $0.id == resourceID }) != true {
                load(showBlockingLoading: false)
                return
            }
            loadResourceDetail(resourceID: resourceID, page: resourceDetailPage?.page ?? 1)
        } else {
            loadContents(sourceNodeID: contentsPage?.currentSourceNodeID ?? destination.sourceNodeID, page: viewState.page)
        }
    }

    private func loadContentBrowser(
        generation: UUID
    ) async {
        isLoadingContentBrowser = true
        contentBrowserFailed = false
        do {
            if activeResourceID == nil {
                let page = try await client.fetchBookContents(
                    context: context, bookID: bookID,
                    sourceNodeID: destination.sourceNodeID,
                    sort: contentSort, page: viewState.page, pageSize: 200
                )
                guard requestGeneration == generation else { return }
                contentsPage = page
                if destination == .root {
                    guard let rootTarget = page.currentNode.destination else { throw ContentClientError.inaccessible }
                    activeResourceID = rootTarget.resourceID
                }
                try await ensureResources(
                    Set(page.entries.compactMap(\.resourceID) + page.entries.compactMap(\.representativeResourceID) +
                        (isBookRoot ? [currentContent?.continueResourceID].compactMap { $0 } : [])),
                    generation: generation
                )
                guard requestGeneration == generation else { return }
            }
            if let resourceID = activeResourceID {
                try await ensureResources([resourceID], generation: generation)
                guard requestGeneration == generation else { return }
                guard let resource = currentContent?.resources.first(where: { $0.id == resourceID }) else {
                    throw ContentClientError.inaccessible
                }
                let page = try await client.fetchResourceDetail(
                    context: context, bookID: bookID, resourceID: resourceID,
                    page: viewState.readingUnitsPage, pageSize: resourceDetailPageSize(resource)
                )
                guard requestGeneration == generation else { return }
                resourceDetailPage = page
                if let current = currentContent {
                    state = .ready(applyingLatestProgress(to: current))
                }
            } else {
                resourceDetailPage = nil
                chapterPage = nil
                if let current = currentContent { state = .ready(applyingLatestProgress(to: current)) }
            }
            isLoadingContentBrowser = false
        } catch {
            guard requestGeneration == generation else { return }
            isLoadingContentBrowser = false
            if case ContentClientError.unauthorized = error { onUnauthorized(); return }
            if case ContentClientError.inaccessible = error { state = .inaccessible; return }
            contentBrowserFailed = true
        }
    }

    private func ensureResources(_ ids: Set<String>, generation: UUID) async throws {
        var pageNumber = 1
        while !ids.isSubset(of: Set(currentContent?.resources.map(\.id) ?? [])) {
            let page = try await client.fetchBookResources(
                context: context, bookID: bookID, page: pageNumber, pageSize: 24
            )
            guard requestGeneration == generation else { return }
            if let current = currentContent { state = .ready(current.appending(page)) }
            if pageNumber >= page.totalPages || page.resources.isEmpty { break }
            pageNumber += 1
        }
    }

    private func loadContents(sourceNodeID: String?, page: Int) {
        let generation = UUID()
        requestGeneration = generation
        isLoadingContentBrowser = true
        contentBrowserFailed = false
        Task { [weak self] in
            guard let self else { return }
            do {
                let value = try await client.fetchBookContents(
                    context: context,
                    bookID: bookID,
                    sourceNodeID: sourceNodeID,
                    sort: contentSort,
                    page: page,
                    pageSize: 200
                )
                guard requestGeneration == generation else { return }
                try await ensureResources(Set(value.entries.compactMap(\.resourceID) + value.entries.compactMap(\.representativeResourceID)), generation: generation)
                guard requestGeneration == generation else { return }
                contentsPage = value
                isLoadingContentBrowser = false
            } catch {
                guard requestGeneration == generation else { return }
                isLoadingContentBrowser = false
                contentBrowserFailed = true
            }
        }
    }

    private func loadResourceDetail(resourceID: String, page: Int) {
        let generation = UUID()
        requestGeneration = generation
        isLoadingContentBrowser = true
        contentBrowserFailed = false
        Task { [weak self] in
            guard let self else { return }
            do {
                let resource = currentContent?.resources.first(where: { $0.id == resourceID })
                let value = try await client.fetchResourceDetail(
                    context: context,
                    bookID: bookID,
                    resourceID: resourceID,
                    page: page,
                    pageSize: resourceDetailPageSize(resource)
                )
                guard requestGeneration == generation, activeResourceID == resourceID else { return }
                resourceDetailPage = value
                isLoadingContentBrowser = false
            } catch {
                guard requestGeneration == generation, activeResourceID == resourceID else { return }
                isLoadingContentBrowser = false
                contentBrowserFailed = true
            }
        }
    }

    private func resourceDetailPageSize(_ resource: BookResource?) -> Int {
        switch resource?.readerType.lowercased() {
        case "comic", "pdf": 24
        case "audio": 100
        default: 50
        }
    }

    private var currentContent: BookDetailContent? {
        guard case .ready(let content) = state else { return nil }
        return content
    }

    private func applyingLatestProgress(to content: BookDetailContent) -> BookDetailContent {
        latestProgressUpdatesByResourceID.values
            .sorted { $0.capturedAtEpochMillis < $1.capturedAtEpochMillis }
            .reduce(content) { $0.applying($1, activeResourceID: activeResourceID) }
    }

    private func apply(_ update: ErmaoShared.ReaderProgressPresentationUpdate) {
        let previous = latestProgressUpdatesByResourceID[update.resourceId]
        guard update.capturedAtEpochMillis >= (previous?.capturedAtEpochMillis ?? -1) else { return }
        latestProgressUpdatesByResourceID[update.resourceId] = update
        guard case .ready(let content) = state else { return }
        let presented = applyingLatestProgress(to: content)
        state = .ready(presented)
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
            chapters: chapters,
            rootSourceNodeID: rootSourceNodeID,
            continueResourceID: continueResourceID
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
            chapters: chapters,
            rootSourceNodeID: rootSourceNodeID,
            continueResourceID: continueResourceID
        )
    }

    func applying(_ update: ErmaoShared.ReaderProgressPresentationUpdate, activeResourceID: String?) -> BookDetailContent {
        guard book.id == update.bookId else { return self }
        let updatesSelected = activeResourceID == update.resourceId
        let updatedBook = BookCard(
            id: book.id,
            title: book.title,
            author: book.author,
            cover: book.cover,
            progress: updatesSelected ? update.percent : book.progress
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
                assets: resource.assets,
                importStatus: resource.importStatus
            )
        }
        let states = ErmaoShared.PublicKt.resolveReaderChapterStatesFromLocation(
            units: chapters.map { ErmaoShared.ReaderChapterUnit(
                href: $0.href, sortOrder: Int32($0.sortOrder),
                readingOrderPosition: $0.readingOrderPosition.map { KotlinInt(int: Int32($0)) }
            ) },
            location: update.location, progressPercent: update.percent
        )
        let updatedChapters = chapters.enumerated().map { index, chapter in
            let state: ChapterReadingState = states[index] == .current ? .current : (states[index] == .read ? .read : .unread)
            return BookChapter(
                id: chapter.id, title: chapter.title,
                progress: state == .current ? update.percent : nil,
                isCurrent: state == .current, href: chapter.href, sortOrder: chapter.sortOrder,
                readingOrderPosition: chapter.readingOrderPosition, state: state
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
            readingStatus: updatesSelected ? (update.percent >= 100 ? .finished : .reading) : readingStatus,
            chapters: updatesSelected ? updatedChapters : chapters,
            rootSourceNodeID: rootSourceNodeID,
            continueResourceID: update.resourceId
        )
    }
}
