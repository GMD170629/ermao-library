import Foundation
import XCTest
@preconcurrency import class ErmaoShared.PublicKt
@preconcurrency import class ErmaoShared.ReaderProgress
@testable import ErmaoLibrary

@MainActor
final class ContentStoreTests: XCTestCase {
    func testResourceIndexUsesServerValueAndFallsBackToOneBasedPosition() {
        let base = BookResource(
            id: "resource-1",
            bookID: "book-1",
            sourceNodeID: "media-1",
            title: "Resource",
            format: "EPUB",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: false
        )

        XCTAssertEqual(base.displayIndex(position: 0), "01")
        XCTAssertEqual(
            BookResource(
                id: "resource-3",
                bookID: "book-1",
                sourceNodeID: "media-1",
                title: "Resource 3",
                format: "EPUB",
                resourceIndex: 3,
                sizeLabel: nil,
                progress: nil,
                isReadable: true,
                isSelected: false
            ).displayIndex(position: 0),
            "03"
        )
        XCTAssertEqual(
            BookResource(
                id: "resource-1-5",
                bookID: "book-1",
                sourceNodeID: "media-1",
                title: "Resource 1.5",
                format: "EPUB",
                resourceIndex: 1.5,
                sizeLabel: nil,
                progress: nil,
                isReadable: true,
                isSelected: false
            ).displayIndex(position: 0),
            "1.5"
        )
    }

    func testLibraryScopesKeepIndependentQueriesAndFilters() async {
        let client = ContentClientStub()
        let store = LibraryStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.setQuery("three body")
        store.applyFilters(LibraryFilters(readingStatus: .reading))
        store.selectScope(.series)
        store.setQuery("trilogy")
        store.selectScope(.books)

        XCTAssertEqual(store.current.query, "three body")
        XCTAssertEqual(store.current.filters.readingStatus, .reading)
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
        store.selectScope(.books)
        store.selectScope(.series)

        XCTAssertEqual(store.current.scrollAnchor, "group:middle")
    }

    func testReapplyingCurrentCollectionSortPreservesLoadedResultsAndScrollAnchor() async throws {
        let client = RacingContentClient()
        let store = LibraryStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            onUnauthorized: {}
        )

        store.reload()
        try await waitUntil {
            guard case .ready = store.current.results else { return false }
            return await client.booksRequestCount == 1
        }
        store.rememberAnchor("work:unfiltered")

        store.setSort(.recentAdded)
        try await Task.sleep(for: .milliseconds(350))

        let requestCount = await client.booksRequestCount
        XCTAssertEqual(requestCount, 1)
        XCTAssertEqual(store.current.scrollAnchor, "work:unfiltered")
        guard case .ready = store.current.results else {
            return XCTFail("Returning from detail must keep the visible collection")
        }
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
        try await waitUntil { await client.booksRequestCount == 1 }

        store.applyFilters(LibraryFilters(readingStatus: .reading))
        try await waitUntil { await client.booksRequestCount == 2 }
        try await waitUntil {
            guard case .ready(let items, _, _, _) = store.current.results else { return false }
            return items.compactMap(\.bookValue).map(\.id) == ["filtered"]
        }
        try await Task.sleep(for: .milliseconds(350))

        guard case .ready(let items, _, _, _) = store.current.results else {
            return XCTFail("Expected the filtered request to remain visible")
        }
        XCTAssertEqual(items.compactMap(\.bookValue).map(\.id), ["filtered"])
        let cancellationCount = await client.cancelledBooksRequestCount
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

    func testGroupingProtocolFailureDoesNotMasqueradeAsCachedContent() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        let store = LibraryStore(
            context: contentContext,
            client: FailingGroupingContentClient(error: .invalidResponse),
            cache: cache,
            onUnauthorized: {}
        )

        store.selectScope(.series)
        try await waitUntil {
            if case .failure = store.current.results { return true }
            return false
        }

        guard case .failure = store.current.results else {
            return XCTFail("A protocol failure must not be presented as cached content")
        }
    }

    func testGroupingNetworkFailureShowsFailureWithoutPersistentFallback() async throws {
        let cache = LibraryCacheStore(rootDirectory: temporaryDirectory())
        let store = LibraryStore(
            context: contentContext,
            client: FailingGroupingContentClient(error: .offline),
            cache: cache,
            onUnauthorized: {}
        )

        store.selectScope(.series)
        try await waitUntil {
            if case .failure = store.current.results { return true }
            return false
        }
    }

    func testTypedRoutesReuseExistingEntityInsteadOfStackingDuplicates() {
        var paths = RootTabPaths()
        paths.open(.work(bookID: "one"), in: .library)
        paths.open(.facet(kind: .author, facetID: "author"), in: .library)
        paths.open(.work(bookID: "one"), in: .library)

        XCTAssertEqual(paths.path(for: .library), [.work(bookID: "one")])
    }

    func testLibraryCacheIsNamespacedAndPersistsAtomically() async throws {
        let root = temporaryDirectory()
        let cache = LibraryCacheStore(rootDirectory: root)
        let page = BookPage(books: [work("one")], page: 1, pageSize: 24, total: 1, totalPages: 1)

        try await cache.save(page, namespace: "server|user|1", key: "works")

        let loaded = try await cache.load(BookPage.self, namespace: "server|user|1", key: "works")
        let differentNamespace = try await cache.load(BookPage.self, namespace: "server|user|2", key: "works")
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
        let cached = BookDetailContent(
            book: work("revoked"),
            description: "private",
            tags: [],
            seriesFacet: nil,
            authorFacets: [],
            resources: [],
            selectedResourceID: nil,
            readingStatus: .unread,
            chapters: []
        )
        try await cache.save(
            cached,
            namespace: contentContext.namespaceKey,
            key: "work|revoked|default|default"
        )
        let store = BookDetailStore(
            context: contentContext,
            client: ContentClientStub(),
            cache: cache,
            bookID: "revoked",
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
            BookDetailContent.self,
            namespace: contentContext.namespaceKey,
            key: "work|revoked|default|default"
        )
        XCTAssertNil(removed)
    }

    func testSingleReadableResourceLoadsChaptersInsteadOfBookContents() async throws {
        let client = DetailBrowserContentClient(resourceCount: 1)
        let store = BookDetailStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            bookID: "browser-work",
            onUnauthorized: {}
        )

        store.load()
        try await waitUntil { store.chapterPage?.chapters.map(\.title) == ["Opening", "Arrival"] }

        XCTAssertNil(store.contentsPage)
        let chapterRequestCount = await client.chapterRequestCount
        let contentsRequestCount = await client.contentsRequestCount
        XCTAssertEqual(chapterRequestCount, 1)
        XCTAssertEqual(contentsRequestCount, 0)
        guard case .ready(let content, _) = store.state else {
            return XCTFail("Expected the single-resource detail to remain ready")
        }
        XCTAssertEqual(content.chapters.map(\.state), [.read, .current])
    }

    func testMultipleReadableResourcesLoadsHierarchicalBookContents() async throws {
        let client = DetailBrowserContentClient(resourceCount: 2)
        let store = BookDetailStore(
            context: contentContext,
            client: client,
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            bookID: "browser-work",
            onUnauthorized: {}
        )

        store.load()
        try await waitUntil { store.contentsPage?.entries.map(\.title) == ["Volume One"] }

        XCTAssertNil(store.chapterPage)
        let contentsRequestCount = await client.contentsRequestCount
        let chapterRequestCount = await client.chapterRequestCount
        XCTAssertEqual(contentsRequestCount, 1)
        XCTAssertEqual(chapterRequestCount, 0)
    }

    func testReaderProgressImmediatelyUpdatesVisibleWorkDetailAndChapterStates() async throws {
        let initial = BookDetailContent(
            book: work("reader-work"),
            description: nil,
            tags: [],
            seriesFacet: nil,
            authorFacets: [],
            resources: [
                BookResource(
                    id: "resource-1",
                    bookID: "reader-work",
                    sourceNodeID: "media-1",
                    title: "Resource 1",
                    format: "EPUB",
                    sizeLabel: nil,
                    progress: nil,
                    isReadable: true,
                    isSelected: true
                ),
                BookResource(
                    id: "resource-2",
                    bookID: "reader-work",
                    sourceNodeID: "media-1",
                    title: "Resource 2",
                    format: "EPUB",
                    sizeLabel: nil,
                    progress: nil,
                    isReadable: true,
                    isSelected: false
                )
            ],
            selectedResourceID: "resource-1",
            readingStatus: .unread,
            chapters: [
                BookChapter(id: "chapter-1", title: "Chapter 1", progress: nil, isCurrent: false, href: "Text/all.xhtml#one", sortOrder: 1),
                BookChapter(id: "chapter-2", title: "Chapter 2", progress: nil, isCurrent: false, href: "Text/all.xhtml#two", sortOrder: 2),
            ]
        )
        let store = BookDetailStore(
            context: contentContext,
            client: ProgressContentClient(content: initial),
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            bookID: "reader-work",
            onUnauthorized: {}
        )
        store.load()
        try await waitUntil {
            if case .ready = store.state { return true }
            return false
        }

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            bookID: "reader-work",
            resourceID: "resource-1",
            percent: 42,
            progress: try exactReflowableProgress(
                href: "Text/all.xhtml",
                fragment: "two",
                updatedAtEpochMillis: 1_000
            ),
            chapterTitle: "Chapter 2"
        )

        guard case .ready(let content, _) = store.state else {
            return XCTFail("Expected work detail to remain ready")
        }
        XCTAssertEqual(content.book.progress, 42)
        XCTAssertEqual(content.resources.first?.progress, 42)
        XCTAssertEqual(content.chapters.map(\.state), [.read, .current])

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            bookID: "reader-work",
            resourceID: "resource-2",
            percent: 75,
            progress: try exactReflowableProgress(
                sourceID: "resource-2",
                href: "Text/all.xhtml",
                fragment: "one",
                updatedAtEpochMillis: 2_000
            ),
            chapterTitle: "Chapter 1"
        )

        guard case .ready(let unchanged, _) = store.state else {
            return XCTFail("Expected work detail to remain ready")
        }
        XCTAssertEqual(unchanged.book.progress, 42)
        XCTAssertNil(unchanged.resources.first(where: { $0.id == "resource-2" })?.progress)
        XCTAssertEqual(unchanged.chapters.map(\.state), [.read, .current])

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            bookID: "reader-work",
            resourceID: "resource-1",
            percent: 55,
            progress: try exactReflowableProgress(
                href: "Text/all.xhtml",
                fragment: "one",
                updatedAtEpochMillis: 1_500
            ),
            chapterTitle: "Chapter 1"
        )

        guard case .ready(let reordered, _) = store.state else {
            return XCTFail("Expected work detail to remain ready")
        }
        XCTAssertEqual(reordered.book.progress, 55)
        XCTAssertEqual(reordered.chapters.map(\.state), [.current, .unread])
    }

    func testReaderProgressUsesPublicationReadingOrderPositionWhenHrefIsSplit() async throws {
        let initial = BookDetailContent(
            book: work("position-work"),
            description: nil,
            tags: [],
            seriesFacet: nil,
            authorFacets: [],
            resources: [
                BookResource(
                    id: "resource-position",
                    bookID: "position-work",
                    sourceNodeID: "media-position",
                    title: "Resource",
                    format: "EPUB",
                    sizeLabel: nil,
                    progress: nil,
                    isReadable: true,
                    isSelected: true
                )
            ],
            selectedResourceID: "resource-position",
            readingStatus: .unread,
            chapters: [
                BookChapter(
                    id: "chapter-1",
                    title: "Chapter 1",
                    progress: nil,
                    isCurrent: false,
                    href: "Text/part0003.xhtml",
                    sortOrder: 1,
                    readingOrderPosition: 3
                ),
                BookChapter(
                    id: "chapter-2",
                    title: "Chapter 2",
                    progress: nil,
                    isCurrent: false,
                    href: "Text/part0008_split_000.xhtml",
                    sortOrder: 2,
                    readingOrderPosition: 10
                ),
                BookChapter(
                    id: "chapter-3",
                    title: "Chapter 3",
                    progress: nil,
                    isCurrent: false,
                    href: "Text/part0009.xhtml",
                    sortOrder: 3,
                    readingOrderPosition: 13
                ),
            ]
        )
        let store = BookDetailStore(
            context: contentContext,
            client: ProgressContentClient(content: initial),
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            bookID: "position-work",
            onUnauthorized: {}
        )
        store.load()
        try await waitUntil {
            if case .ready = store.state { return true }
            return false
        }

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            bookID: "position-work",
            resourceID: "resource-position",
            percent: 15.2,
            progress: try exactPositionProgress(
                sourceID: "resource-position",
                href: "Text/part0008_split_001.xhtml",
                position: 11,
                updatedAtEpochMillis: 3_000
            ),
            chapterTitle: "Chapter 2"
        )

        guard case .ready(let content, _) = store.state else {
            return XCTFail("Expected work detail to remain ready")
        }
        XCTAssertEqual(content.book.progress, 15.2)
        XCTAssertEqual(content.chapters.map(\.state), [.read, .current, .unread])
    }

    private func exactReflowableProgress(
        sourceID: String = "resource-1",
        href: String,
        fragment: String,
        updatedAtEpochMillis: Int64
    ) throws -> ReaderProgress {
        let payload = """
        {"schema":"ermao.reader-progress","version":6,"sourceId":"\(sourceID)","location":{"kind":"reflow","resourceKey":"\(href)#\(fragment)","engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"\(href)","type":"application/xhtml+xml","locations":{"fragments":["\(fragment)"]}}}},"updatedAtEpochMillis":\(updatedAtEpochMillis),"deviceId":"ios-test","percent":42.0}
        """
        return try PublicKt.createReaderProgressJson().decode(payload: payload)
    }

    private func exactPositionProgress(
        sourceID: String,
        href: String,
        position: Int,
        updatedAtEpochMillis: Int64
    ) throws -> ReaderProgress {
        let payload = """
        {"schema":"ermao.reader-progress","version":6,"sourceId":"\(sourceID)","location":{"kind":"reflow","resourceKey":"\(href)","engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"\(href)","type":"application/xhtml+xml","locations":{"cssSelector":"#visible","position":\(position)}}}},"updatedAtEpochMillis":\(updatedAtEpochMillis),"deviceId":"ios-test","percent":15.2}
        """
        return try PublicKt.createReaderProgressJson().decode(payload: payload)
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
                    bookCount: 1,
                    representativeBooks: []
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
    var bookValue: BookCard? {
        guard case .book(let book) = self else { return nil }
        return book
    }


    var groupingValue: LibraryGrouping? {
        guard case .grouping(let grouping) = self else { return nil }
        return grouping
    }
}

private actor FailingGroupingContentClient: ContentClient {
    private let error: ContentClientError

    init(error: ContentClientError) {
        self.error = error
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage { throw error }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage { throw error }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage { throw error }
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent { throw error }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { throw error }
}

private actor RacingContentClient: ContentClient {
    private(set) var booksRequestCount = 0
    private(set) var cancelledBooksRequestCount = 0

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }

    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        booksRequestCount += 1
        do {
            try await Task.sleep(for: query.filters.isEmpty ? .milliseconds(300) : .milliseconds(20))
        } catch {
            cancelledBooksRequestCount += 1
            throw error
        }
        let id = query.filters.isEmpty ? "unfiltered" : "filtered"
        return BookPage(books: [work(id)], page: 1, pageSize: query.pageSize, total: 1, totalPages: 1)
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"), books: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent { throw ContentClientError.inaccessible }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private actor MutableGroupingContentClient: ContentClient {
    private var seriesName = "Series 1"
    private(set) var seriesRequestCount = 0

    func setSeriesName(_ name: String) { seriesName = name }
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        BookPage(books: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
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
            bookCount: 1,
            representativeBooks: []
        )
        return GroupingPage(groups: [group], page: 1, pageSize: query.pageSize, total: 1, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"), books: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent { throw ContentClientError.inaccessible }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private actor ContentClientStub: ContentClient {
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        BookPage(books: [work("book-\(query.page)")], page: query.page, pageSize: query.pageSize, total: 1, totalPages: 1)
    }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: query.page, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(
            facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"),
            books: [],
            page: query.page,
            pageSize: query.pageSize,
            total: 0,
            totalPages: 1
        )
    }
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent {
        throw ContentClientError.inaccessible
    }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private actor ProgressContentClient: ContentClient {
    let content: BookDetailContent

    init(content: BookDetailContent) {
        self.content = content
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        BookPage(books: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"), books: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent { content }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }
}

private actor DetailBrowserContentClient: ContentClient {
    let resourceCount: Int
    private(set) var contentsRequestCount = 0
    private(set) var chapterRequestCount = 0

    init(resourceCount: Int) {
        self.resourceCount = resourceCount
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] { [] }
    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        BookPage(books: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(
            facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"),
            books: [],
            page: 1,
            pageSize: query.pageSize,
            total: 0,
            totalPages: 1
        )
    }
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent {
        let resources = (1...resourceCount).map { index in
            BookResource(
                id: "resource-\(index)",
                bookID: query.bookID,
                sourceNodeID: "node-\(index)",
                title: "Volume \(index)",
                format: "EPUB",
                sizeLabel: nil,
                progress: index == 1 ? 40 : nil,
                isReadable: true,
                isSelected: index == 1
            )
        }
        return BookDetailContent(
            book: work(query.bookID),
            description: "Description",
            tags: ["Science Fiction"],
            seriesFacet: FacetIdentity(id: "series-1", kind: .series, name: "Hainish Cycle"),
            authorFacets: [FacetIdentity(id: "author-1", kind: .author, name: "Ursula K. Le Guin")],
            resources: resources,
            selectedResourceID: resources.first?.id,
            readingStatus: .reading,
            chapters: []
        )
    }
    func fetchBookContents(
        context: ContentRequestContext,
        bookID: String,
        sourceNodeID: String?,
        page: Int,
        pageSize: Int
    ) async throws -> BookContentsPage {
        contentsRequestCount += 1
        let root = contentEntry(id: "root", title: "Browser Work", kind: "FOLDER", hasChildren: true)
        let volume = contentEntry(
            id: "node-1",
            title: "Volume One",
            kind: "FILE",
            hasChildren: false,
            resourceID: "resource-1"
        )
        return BookContentsPage(
            bookID: bookID,
            currentSourceNodeID: nil,
            currentResourceID: nil,
            currentNode: root,
            currentResourceIDs: [],
            parentSourceNodeID: nil,
            breadcrumbs: [],
            entries: [volume],
            page: page,
            pageSize: pageSize,
            total: 1,
            totalPages: 1
        )
    }
    func fetchBookChapters(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookChapterPage {
        chapterRequestCount += 1
        return BookChapterPage(
            resourceID: resourceID,
            chapters: [
                BookChapter(id: "chapter-1", title: "Opening", progress: nil, isCurrent: false, sortOrder: 1, state: .read),
                BookChapter(id: "chapter-2", title: "Arrival", progress: 40, isCurrent: true, sortOrder: 2, state: .current),
            ],
            page: page,
            pageSize: pageSize,
            total: 2,
            totalPages: 1
        )
    }
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data { Data() }

    private func contentEntry(
        id: String,
        title: String,
        kind: String,
        hasChildren: Bool,
        resourceID: String? = nil
    ) -> BookContentEntry {
        BookContentEntry(
            sourceNodeID: id,
            parentSourceNodeID: nil,
            name: title,
            title: title,
            description: nil,
            kind: kind,
            physicalKind: kind == "FOLDER" ? "DIRECTORY" : "FILE",
            sizeBytes: nil,
            hasChildren: hasChildren,
            resourceID: resourceID,
            representativeResourceID: resourceID,
            cover: nil
        )
    }
}

private func work(_ id: String) -> BookCard {
    BookCard(
        id: id,
        title: "Title \(id)",
        author: "Author",
        cover: nil,
        progress: nil
    )
}
