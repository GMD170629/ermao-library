import Foundation
import Combine

enum ShelfCatalogLoadState: Equatable {
    case loading
    case ready(catalog: [ShelfCatalogItem], detail: ShelfCatalogDetail?)
    case failed(ContentClientError)
}

enum ShelfCreationState: Equatable { case idle, saving, failed }

@MainActor
final class ShelfCatalogStore: ObservableObject {
    @Published private(set) var state: ShelfCatalogLoadState = .loading
    @Published var scope: ShelfCatalogScope = .all
    @Published private var queries: [ShelfCatalogScope: String] = [:]
    @Published private(set) var loadingMore = false
    @Published private(set) var paginationFailed = false
    @Published private(set) var creation: ShelfCreationState = .idle
    private let context: ContentRequestContext
    private let client: any ShelfCatalogClient
    private let shelfID: String?
    private let onUnauthorized: @MainActor () -> Void
    private var generation = UUID()

    init(context: ContentRequestContext, client: any ShelfCatalogClient, shelfID: String?, onUnauthorized: @escaping @MainActor () -> Void) {
        self.context = context; self.client = client; self.shelfID = shelfID; self.onUnauthorized = onUnauthorized
    }

    var query: String {
        get { queries[scope] ?? "" }
        set { queries[scope] = newValue }
    }
    var catalog: [ShelfCatalogItem] {
        if case .ready(let catalog, _) = state { return catalog }
        return []
    }
    var detail: ShelfCatalogDetail? {
        if case .ready(_, let detail) = state { return detail }
        return nil
    }
    var visibleShelves: [ShelfCatalogItem] { filteredShelves(catalog, scope: scope, query: query, collectionID: shelfID) }

    func loadIfNeeded() async {
        if case .loading = state { await refresh() }
    }

    func refresh() async {
        let requestID = UUID()
        generation = requestID
        let previousPage = detail?.page ?? 1
        loadingMore = true; paginationFailed = false
        do {
            let catalog = try await client.catalog(context: context)
            var detail: ShelfCatalogDetail?
            if let shelfID { detail = try await client.detail(context: context, shelfID: shelfID, page: 1) }
            else { detail = nil }
            if previousPage > 1, let shelfID {
                for page in 2...previousPage {
                    guard let current = detail, page <= current.totalPages else { break }
                    var next = try await client.detail(context: context, shelfID: shelfID, page: page)
                    var seen = Set<String>()
                    next.shelf.books = (current.shelf.books + next.shelf.books).filter { seen.insert($0.id).inserted }
                    detail = next
                }
            }
            guard generation == requestID, !Task.isCancelled else { return }
            state = .ready(catalog: catalog, detail: detail)
            loadingMore = false
        } catch {
            guard generation == requestID, !Task.isCancelled else { return }
            fail(error)
        }
    }

    func loadMore() async {
        guard let current = detail, current.shelf.kind != .collection, current.page < current.totalPages, !loadingMore else { return }
        let requestID = generation
        loadingMore = true; paginationFailed = false
        defer { if generation == requestID { loadingMore = false } }
        do {
            var next = try await client.detail(context: context, shelfID: current.shelf.id, page: current.page + 1)
            guard generation == requestID, !Task.isCancelled else { return }
            var seen = Set<String>()
            next.shelf.books = (current.shelf.books + next.shelf.books).filter { seen.insert($0.id).inserted }
            state = .ready(catalog: catalog, detail: next)
            loadingMore = false
        } catch {
            guard generation == requestID, !Task.isCancelled else { return }
            loadingMore = false
            if let issue = error as? ContentClientError, issue == .unauthorized || issue == .inaccessible { fail(issue) }
            else { paginationFailed = true }
        }
    }

    func create(_ draft: ShelfCreateDraft) async -> String? {
        guard creation != .saving, draft.isValid else { return nil }
        creation = .saving
        do {
            let id = try await client.create(context: context, draft: draft)
            guard !Task.isCancelled else { creation = .idle; return nil }
            await refresh()
            creation = .idle
            return id
        } catch {
            guard !Task.isCancelled else { creation = .idle; return nil }
            creation = .failed
            if error as? ContentClientError == .unauthorized { onUnauthorized() }
            return nil
        }
    }

    func clearCreationError() { if creation != .saving { creation = .idle } }

    private func fail(_ error: Error) {
        let issue = error as? ContentClientError ?? .transport
        state = .failed(issue)
        if issue == .unauthorized { onUnauthorized() }
    }
}
