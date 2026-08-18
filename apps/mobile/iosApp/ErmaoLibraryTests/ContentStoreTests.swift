import Foundation
import XCTest
@preconcurrency import class ErmaoShared.PublicKt
@preconcurrency import class ErmaoShared.ReaderProgress
@testable import ErmaoLibrary

@MainActor
final class ContentStoreTests: XCTestCase {
    func testVolumeIndexUsesServerValueAndFallsBackToOneBasedPosition() {
        let base = WorkVolume(
            id: "volume-1",
            versionID: "media-1",
            title: "Volume",
            formatLabel: "EPUB",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: false
        )

        XCTAssertEqual(base.displayIndex(position: 0), "01")
        XCTAssertEqual(
            WorkVolume(
                id: "volume-3",
                versionID: "media-1",
                title: "Volume 3",
                formatLabel: "EPUB",
                volumeIndex: 3,
                sizeLabel: nil,
                progress: nil,
                isReadable: true,
                isSelected: false
            ).displayIndex(position: 0),
            "03"
        )
        XCTAssertEqual(
            WorkVolume(
                id: "volume-1-5",
                versionID: "media-1",
                title: "Volume 1.5",
                formatLabel: "EPUB",
                volumeIndex: 1.5,
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
            return await client.worksRequestCount == 1
        }
        store.rememberAnchor("work:unfiltered")

        store.setSort(.recentAdded)
        try await Task.sleep(for: .milliseconds(350))

        let requestCount = await client.worksRequestCount
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
            versions: [],
            selectedVersionId: "version-1",
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

    func testReaderProgressImmediatelyUpdatesVisibleWorkDetailAndChapterStates() async throws {
        let initial = WorkDetailContent(
            work: work("reader-work"),
            description: nil,
            tags: [],
            seriesFacet: nil,
            authorFacets: [],
            versions: [],
            selectedVersionId: "version-1",
            selectedVolumeID: "volume-1",
            readingStatus: .unread,
            volumes: [
                WorkVolume(
                    id: "volume-1",
                    versionID: "media-1",
                    title: "Volume 1",
                    formatLabel: "EPUB",
                    sizeLabel: nil,
                    progress: nil,
                    isReadable: true,
                    isSelected: true
                ),
                WorkVolume(
                    id: "volume-2",
                    versionID: "media-1",
                    title: "Volume 2",
                    formatLabel: "EPUB",
                    sizeLabel: nil,
                    progress: nil,
                    isReadable: true,
                    isSelected: false
                )
            ],
            chapters: [
                WorkChapter(id: "chapter-1", title: "Chapter 1", progress: nil, isCurrent: false, href: "Text/all.xhtml#one", sortOrder: 1),
                WorkChapter(id: "chapter-2", title: "Chapter 2", progress: nil, isCurrent: false, href: "Text/all.xhtml#two", sortOrder: 2),
            ]
        )
        let store = WorkDetailStore(
            context: contentContext,
            client: ProgressContentClient(content: initial),
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            workID: "reader-work",
            onUnauthorized: {}
        )
        store.load()
        try await waitUntil {
            if case .ready = store.state { return true }
            return false
        }

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            workID: "reader-work",
            volumeID: "volume-1",
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
        XCTAssertEqual(content.work.progress, 42)
        XCTAssertEqual(content.volumes.first?.progress, 42)
        XCTAssertEqual(content.chapters.map(\.state), [.read, .current])

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            workID: "reader-work",
            volumeID: "volume-2",
            percent: 75,
            progress: try exactReflowableProgress(
                sourceID: "volume-2",
                href: "Text/all.xhtml",
                fragment: "one",
                updatedAtEpochMillis: 2_000
            ),
            chapterTitle: "Chapter 1"
        )

        guard case .ready(let unchanged, _) = store.state else {
            return XCTFail("Expected work detail to remain ready")
        }
        XCTAssertEqual(unchanged.work.progress, 42)
        XCTAssertNil(unchanged.volumes.first(where: { $0.id == "volume-2" })?.progress)
        XCTAssertEqual(unchanged.chapters.map(\.state), [.read, .current])

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            workID: "reader-work",
            volumeID: "volume-1",
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
        XCTAssertEqual(reordered.work.progress, 55)
        XCTAssertEqual(reordered.chapters.map(\.state), [.current, .unread])
    }

    func testReaderProgressUsesPublicationReadingOrderPositionWhenHrefIsSplit() async throws {
        let initial = WorkDetailContent(
            work: work("position-work"),
            description: nil,
            tags: [],
            seriesFacet: nil,
            authorFacets: [],
            versions: [],
            selectedVersionId: "version-1",
            selectedVolumeID: "volume-position",
            readingStatus: .unread,
            volumes: [
                WorkVolume(
                    id: "volume-position",
                    versionID: "media-position",
                    title: "Volume",
                    formatLabel: "EPUB",
                    sizeLabel: nil,
                    progress: nil,
                    isReadable: true,
                    isSelected: true
                )
            ],
            chapters: [
                WorkChapter(
                    id: "chapter-1",
                    title: "Chapter 1",
                    progress: nil,
                    isCurrent: false,
                    href: "Text/part0003.xhtml",
                    sortOrder: 1,
                    readingOrderPosition: 3
                ),
                WorkChapter(
                    id: "chapter-2",
                    title: "Chapter 2",
                    progress: nil,
                    isCurrent: false,
                    href: "Text/part0008_split_000.xhtml",
                    sortOrder: 2,
                    readingOrderPosition: 10
                ),
                WorkChapter(
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
        let store = WorkDetailStore(
            context: contentContext,
            client: ProgressContentClient(content: initial),
            cache: LibraryCacheStore(rootDirectory: temporaryDirectory()),
            workID: "position-work",
            onUnauthorized: {}
        )
        store.load()
        try await waitUntil {
            if case .ready = store.state { return true }
            return false
        }

        ReaderProgressPresentationCenter.shared.publish(
            namespaceKey: contentContext.namespaceKey,
            workID: "position-work",
            volumeID: "volume-position",
            percent: 15.2,
            progress: try exactPositionProgress(
                sourceID: "volume-position",
                href: "Text/part0008_split_001.xhtml",
                position: 11,
                updatedAtEpochMillis: 3_000
            ),
            chapterTitle: "Chapter 2"
        )

        guard case .ready(let content, _) = store.state else {
            return XCTFail("Expected work detail to remain ready")
        }
        XCTAssertEqual(content.work.progress, 15.2)
        XCTAssertEqual(content.chapters.map(\.state), [.read, .current, .unread])
    }

    private func exactReflowableProgress(
        sourceID: String = "volume-1",
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

    init(error: ContentClientError) {
        self.error = error
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage { throw error }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage { throw error }
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

private actor ProgressContentClient: ContentClient {
    let content: WorkDetailContent

    init(content: WorkDetailContent) {
        self.content = content
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? { nil }
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] { [] }
    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        WorkPage(works: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        GroupingPage(groups: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(facet: FacetIdentity(id: query.facetID, kind: query.kind, name: "Facet"), works: [], page: 1, pageSize: query.pageSize, total: 0, totalPages: 1)
    }
    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent { content }
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
