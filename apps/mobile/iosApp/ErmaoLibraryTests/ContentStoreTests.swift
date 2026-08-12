import Foundation
import XCTest
@testable import ErmaoLibrary

@MainActor
final class ContentStoreTests: XCTestCase {
    func testLibraryScopesKeepIndependentQueriesAndFilters() async {
        let client = ContentClientStub()
        let store = LibraryStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.setQuery("three body")
        store.applyFilters(LibraryFilters(mediaKinds: [.ebook], readingStatuses: [.reading]))
        store.selectScope(.series)
        store.setQuery("trilogy")
        store.selectScope(.works)

        XCTAssertEqual(store.current.query, "three body")
        XCTAssertEqual(store.current.filters.mediaKinds, [.ebook])
        XCTAssertEqual(store.current.filters.readingStatuses, [.reading])
        store.selectScope(.series)
        XCTAssertEqual(store.current.query, "trilogy")
        XCTAssertTrue(store.current.filters.isEmpty)
    }

    func testSelectingAnUnloadedScopePublishesItsLoadingStateImmediately() {
        let store = LibraryStore(
            context: contentContext,
            client: ContentClientStub(),
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.selectScope(.series)

        XCTAssertEqual(store.selectedScope, .series)
        guard case .loading = store.current.results else {
            return XCTFail("Scope switching must not expose the target scope's idle intermediate state")
        }
    }

    func testScopeSelectionPreservesTheTargetScopesHistoricalScrollAnchor() {
        let store = LibraryStore(
            context: contentContext,
            client: ContentClientStub(),
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.selectScope(.series)
        store.rememberAnchor("group:middle")
        store.selectScope(.works)
        store.selectScope(.series)

        XCTAssertEqual(store.current.scrollAnchor, "group:middle")
    }

    func testApplyingFiltersDoesNotCancelInFlightContentRequestAndRejectsItsStaleResult() async throws {
        let client = RacingContentClient()
        let store = LibraryStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.reload()
        try await waitUntil { await client.worksRequestCount == 1 }

        store.applyFilters(LibraryFilters(mediaKinds: [.ebook]))
        try await waitUntil { await client.worksRequestCount == 2 }
        try await waitUntil {
            guard case .ready(let items, _, _, _) = store.current.results else { return false }
            return items.compactMap(\.workValue).map(\.id) == ["filtered"]
        }
        try await Task.sleep(for: .milliseconds(350))

        guard case .ready(let items, _, _, _) = store.current.results else {
            return XCTFail("Expected the filtered request to remain visible")
        }
        XCTAssertEqual(items.compactMap(\.workValue).map(\.id), ["filtered"])
        let cancellationCount = await client.cancelledWorksRequestCount
        XCTAssertEqual(cancellationCount, 0)
    }

    func testReturningToGroupingScopeRevalidatesServerContent() async throws {
        let client = MutableGroupingContentClient()
        let store = LibraryStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.selectScope(.series)
        try await waitUntil {
            store.current.groupingNames == ["Series 1"]
        }

        store.selectScope(.authors)
        try await waitUntil {
            store.current.groupingNames == ["Author 1"]
        }
        await client.setSeriesName("Series 2")
        store.selectScope(.series)
        try await waitUntil {
            store.current.groupingNames == ["Series 2"]
        }

        let seriesRequestCount = await client.seriesRequestCount
        XCTAssertEqual(seriesRequestCount, 2)
    }

    func testGroupingProtocolFailureDoesNotMasqueradeAsOfflineCachedContent() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        let store = LibraryStore(
            context: contentContext,
            client: FailingGroupingContentClient(
                error: .invalidResponse,
                restored: groupingPage(name: "Cached Series")
            ),
            cache: cache,
            onUnauthorized: {}
        )

        store.selectScope(.series)
        try await waitUntil {
            if case .failure = store.current.results { return true }
            return false
        }

        guard case .failure = store.current.results else {
            return XCTFail("A protocol failure must not be presented as offline cached content")
        }
    }

    func testGroupingOfflineFailureFallsBackToCachedContent() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        let store = LibraryStore(
            context: contentContext,
            client: FailingGroupingContentClient(
                error: .offline,
                restored: groupingPage(name: "Cached Series")
            ),
            cache: cache,
            onUnauthorized: {}
        )

        store.selectScope(.series)
        try await waitUntil {
            guard case .ready(let items, _, let isCached, _) = store.current.results else { return false }
            return isCached && items.compactMap(\.groupingValue).map(\.name) == ["Cached Series"]
        }
    }

    func testTypedRoutesReuseExistingEntityInsteadOfStackingDuplicates() {
        var paths = RootTabPaths()
        paths.open(.work(workID: "one"), in: .library)
        paths.open(.facet(kind: .author, facetID: "author"), in: .library)
        paths.open(.work(workID: "one"), in: .library)

        XCTAssertEqual(paths.path(for: .library), [.work(workID: "one")])
    }

    func testLibraryCacheIsNamespacedAndPersistsAtomically() async throws {
        let root = temporaryDirectory()
        let cache = LibraryCacheStore(rootDirectory: root)
        let page = WorkPage(works: [work("one")], page: 1, pageSize: 24, total: 1, totalPages: 1)

        try await cache.save(page, namespace: "server|user|1", key: "works")

        let loaded = try await cache.load(WorkPage.self, namespace: "server|user|1", key: "works")
        let differentNamespace = try await cache.load(WorkPage.self, namespace: "server|user|2", key: "works")
        XCTAssertEqual(loaded, page)
        XCTAssertNil(differentNamespace)
        let isFresh = try await cache.isFresh(namespace: "server|user|1", key: "works")
        XCTAssertTrue(isFresh)
    }

    func testRemovingCurrentNamespaceDoesNotRemoveAnotherUsersCache() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        try await cache.save("current", namespace: "server|current-user|1", key: "home")
        try await cache.save("other", namespace: "server|other-user|1", key: "home")

        try await cache.removeNamespace("server|current-user|1")

        let removed = try await cache.load(String.self, namespace: "server|current-user|1", key: "home")
        let retained = try await cache.load(String.self, namespace: "server|other-user|1", key: "home")
        XCTAssertNil(removed)
        XCTAssertEqual(retained, "other")
    }

    func testLibraryCacheRetainsAtMostThreePagesPerQueryIdentity() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        for page in 1...4 {
            try await cache.save(page, namespace: "server|user|1", key: "library|works|query|title|||\(page)")
        }

        let evicted = try await cache.load(Int.self, namespace: "server|user|1", key: "library|works|query|title|||1")
        let retained = try await cache.load(Int.self, namespace: "server|user|1", key: "library|works|query|title|||4")
        XCTAssertNil(evicted)
        XCTAssertEqual(retained, 4)
    }

    func testInaccessibleWorkPurgesCachedPrivateContentInsteadOfDisplayingIt() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        let cached = WorkDetailContent(
            work: work("revoked"),
            description: "private",
            tags: [],
            seriesFacet: nil,
            authorFacets: [],
            availableMediaKinds: [.ebook],
            selectedMediaKind: .ebook,
            selectedVolumeID: nil,
            readingStatus: .unread,
            volumes: [],
            chapters: []
        )
        try await cache.save(
            cached,
            namespace: contentContext.namespaceKey,
            key: "work|revoked|default|default"
        )
        let store = WorkDetailStore(
            context: contentContext,
            client: ContentClientStub(),
            cache: cache,
            workID: "revoked",
            onUnauthorized: {}
        )

        store.load()
        for _ in 0..<20 {
            if case .inaccessible = store.state { break }
            try await Task.sleep(for: .milliseconds(25))
        }

        guard case .inaccessible = store.state else {
            return XCTFail("Expected inaccessible state")
        }
        let removed = try await cache.load(
            WorkDetailContent.self,
            namespace: contentContext.namespaceKey,
            key: "work|revoked|default|default"
        )
        XCTAssertNil(removed)
    }

    private var contentContext: ContentRequestContext {
        ContentRequestContext(
            profileID: "profile",
            profileDisplayName: "Library",
            serverIdentity: "server",
            userID: "user",
            authorizationVersion: 1,
            baseURL: "https://books.example.com",
            acceptsInsecureTLS: false
        )
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("ermao-content-tests-\(UUID().uuidString)", isDirectory: true)
    }

    private func groupingPage(name: String) -> GroupingPage {
        GroupingPage(
            groups: [
                LibraryGrouping(
                    id: "series",
                    kind: .series,
                    name: name,
                    workCount: 1,
                    representativeWorks: []
                )
            ],
            page: 1,
            pageSize: 30,
            total: 1,
            totalPages: 1
        )
    }

    private func waitUntil(
        attempts: Int = 100,
        condition: @escaping @MainActor () async -> Bool
    ) async throws {
        for _ in 0..<attempts {
            if await condition() { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Timed out waiting for asynchronous content state")
    }
}

private extension LibraryScopeState {
    var groupingNames: [String] {
        guard case .ready(let items, _, _, _) = results else { return [] }
        return items.compactMap {
            guard case .grouping(let grouping) = $0 else { return nil }
            return grouping.name
        }
    }
}

private extension LibraryResultItem {
    var workValue: WorkCard? {
        guard case .work(let work) = self else { return nil }
        return work
    }


    var groupingValue: LibraryGrouping? {
        guard case .grouping(let grouping) = self else { return nil }
        return grouping
    }
}

private actor FailingGroupingContentClient: ContentClient {
    private let error: ContentClientError
    private let restored: GroupingPage?

    init(error: ContentClientError, restored: GroupingPage? = nil) {
        self.error = error
        self.restored = restored
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage { throw error }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage { throw error }
    func restoreGroupingsResult(
        context: ContentRequestContext,
        query: GroupingsQuery
    ) async throws -> ContentFetch<GroupingPage>? {
        restored.map { ContentFetch(value: $0, provenance: .cache, isStale: true) }
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage { throw error }
    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent { throw error }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { throw error }
}

private actor RacingContentClient: ContentClient {
    private(set) var worksRequestCount = 0
    private(set) var cancelledWorksRequestCount = 0

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }

    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        worksRequestCount += 1
        do {
            try await Task.sleep(for: query.filters.isEmpty ? .milliseconds(300) : .milliseconds(20))
        } catch {
            cancelledWorksRequestCount += 1
            throw error
        }
        let id = query.filters.isEmpty ? "unfiltered" : "filtered"
        return WorkPage(works: [work(id)], page: 1, pageSize: query.pageSize, total: 1, totalPages: 1)
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"), works: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent { throw ContentClientError.inaccessible }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private actor MutableGroupingContentClient: ContentClient {
    private var seriesName = "Series 1"
    private(set) var seriesRequestCount = 0

    func setSeriesName(_ name: String) { seriesName = name }
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        WorkPage(works: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        let name: String
        switch query.kind {
        case .series:
            seriesRequestCount += 1
            name = seriesName
        case .author:
            name = "Author 1"
        }
        let group = LibraryGrouping(
            id: query.kind == .series ? "series" : "author",
            kind: query.kind,
            name: name,
            workCount: 1,
            representativeWorks: []
        )
        return GroupingPage(groups: [group], page: 1, pageSize: query.pageSize, total: 1, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"), works: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent { throw ContentClientError.inaccessible }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private actor ContentClientStub: ContentClient {
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        WorkPage(works: [work("work-\(query.page)")], page: query.page, pageSize: query.pageSize, total: 1, totalPages: 1)
    }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: query.page, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(
            facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"),
            works: [],
            page: query.page,
            pageSize: query.pageSize,
            total: 0,
            totalPages: 1
        )
    }
    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent {
        throw ContentClientError.inaccessible
    }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private func work(_ id: String) -> WorkCard {
    WorkCard(
        id: id,
        title: "Title \(id)",
        author: "Author",
        cover: nil,
        progress: nil,
        availableMediaKinds: [.ebook]
    )
}
