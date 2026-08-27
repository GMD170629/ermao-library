import XCTest
@testable import ErmaoLibrary

@MainActor
final class ShelfCatalogTests: XCTestCase {
    func testSearchAndScopePreserveMemberVisibility() {
        let catalog = [shelf("c", .collection), shelf("s", .standard, collections: ["c"]), shelf("smart", .smart)]
        XCTAssertEqual(filteredShelves(catalog, scope: .all, query: "", collectionID: nil).count, 3)
        XCTAssertEqual(filteredShelves(catalog, scope: .shelves, query: "", collectionID: nil).count, 2)
        XCTAssertEqual(filteredShelves(catalog, scope: .all, query: " S ", collectionID: "c").map(\.id), ["s"])
    }

    func testCollectionPreviewDeduplicatesAndDoesNotIncludeOtherShelves() {
        let collection = shelf("c", .collection)
        let catalog = [collection, shelf("s", .standard, collections: ["c"], books: [book("a"), book("b")]),
                       shelf("t", .smart, collections: ["c"], books: [book("a"), book("c")]),
                       shelf("other", .standard, books: [book("private")])]
        XCTAssertEqual(shelfPreview(collection, catalog: catalog).map(\.id), ["a", "b", "c"])
    }

    func testRefreshFailureClearsOldContentAndKeepsScopeQuery() async {
        let client = FakeShelfCatalogClient()
        let store = makeStore(client)
        await store.refresh()
        store.query = "s"
        store.scope = .collections
        store.query = "c"
        store.scope = .all
        XCTAssertEqual(store.query, "s")
        await client.setFailure(.offline)
        await store.refresh()
        XCTAssertEqual(store.state, .failed(.offline))
        XCTAssertTrue(store.catalog.isEmpty)
        XCTAssertEqual(store.query, "s")
    }

    func testPaginationFailurePreservesOnlyCurrentLoadedPage() async {
        let client = FakeShelfCatalogClient()
        let store = makeStore(client, id: "s")
        await store.refresh()
        await client.setFailure(.offline)
        await store.loadMore()
        XCTAssertEqual(store.detail?.page, 1)
        XCTAssertTrue(store.paginationFailed)
        await client.setFailure(nil)
        await store.loadMore()
        XCTAssertEqual(store.detail?.page, 2)
        XCTAssertEqual(store.detail?.shelf.books.count, 1)
    }

    func testUnauthorizedClearsContentAndReauthenticates() async {
        let client = FakeShelfCatalogClient()
        var count = 0
        let store = ShelfCatalogStore(context: context, client: client, shelfID: nil) { count += 1 }
        await client.setFailure(.unauthorized)
        await store.refresh()
        XCTAssertEqual(count, 1)
        XCTAssertTrue(store.catalog.isEmpty)
    }

    func testCreateDoesNotReportSuccessOnFailure() async {
        let client = FakeShelfCatalogClient()
        let store = makeStore(client)
        await client.setFailure(.transport)
        let id = await store.create(ShelfCreateDraft(name: "New"))
        XCTAssertNil(id)
        XCTAssertEqual(store.creation, .failed)
    }

    private func makeStore(_ client: FakeShelfCatalogClient, id: String? = nil) -> ShelfCatalogStore {
        ShelfCatalogStore(context: context, client: client, shelfID: id, onUnauthorized: {})
    }
    private var context: ContentRequestContext {
        ContentRequestContext(profileID: "p", profileDisplayName: "Books", serverIdentity: "server", userID: "user",
                              authorizationVersion: 1, baseURL: "https://example.test", acceptsInsecureTLS: false)
    }
    private func shelf(_ id: String, _ kind: ShelfCatalogKind, collections: [String] = [], books: [ShelfPreview] = []) -> ShelfCatalogItem {
        ShelfCatalogItem(id: id, name: id, description: nil, kind: kind, count: books.count, books: books, collectionIDs: collections, rulesSupported: true)
    }
    private func book(_ id: String) -> ShelfPreview { ShelfPreview(id: id, title: id, author: nil, cover: nil, progress: 0) }
}

private actor FakeShelfCatalogClient: ShelfCatalogClient {
    private var failure: ContentClientError?
    func setFailure(_ value: ContentClientError?) { failure = value }
    func catalog(context: ContentRequestContext) throws -> [ShelfCatalogItem] {
        if let failure { throw failure }
        return [ShelfCatalogItem(id: "s", name: "s", description: nil, kind: .standard, count: 2,
            books: [ShelfPreview(id: "b", title: "Book", author: nil, cover: nil, progress: 0)], collectionIDs: [], rulesSupported: true)]
    }
    func detail(context: ContentRequestContext, shelfID: String, page: Int) throws -> ShelfCatalogDetail {
        ShelfCatalogDetail(shelf: try catalog(context: context)[0], page: page, totalPages: 2)
    }
    func create(context: ContentRequestContext, draft: ShelfCreateDraft) throws -> String {
        if let failure { throw failure }
        return "created"
    }
}
