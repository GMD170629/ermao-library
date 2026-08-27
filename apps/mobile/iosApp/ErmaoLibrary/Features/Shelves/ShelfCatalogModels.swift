import Foundation

enum ShelfCatalogKind: String, Sendable { case standard, smart, collection }
enum ShelfCatalogScope: String, CaseIterable, Sendable { case all, shelves, collections }

struct ShelfPreview: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let author: String?
    let cover: CoverReference?
    let progress: Double
}

struct ShelfCatalogItem: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let description: String?
    let kind: ShelfCatalogKind
    let count: Int
    var books: [ShelfPreview]
    let collectionIDs: [String]
    let rulesSupported: Bool
}

struct ShelfCatalogDetail: Equatable, Sendable {
    var shelf: ShelfCatalogItem
    let page: Int
    let totalPages: Int
}

struct ShelfCreateDraft: Sendable {
    var name = ""
    var description = ""
    var isCollection = false
    var memberIDs: Set<String> = []
    var isValid: Bool { !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
}

protocol ShelfCatalogClient: Sendable {
    func catalog(context: ContentRequestContext) async throws -> [ShelfCatalogItem]
    func detail(context: ContentRequestContext, shelfID: String, page: Int) async throws -> ShelfCatalogDetail
    func create(context: ContentRequestContext, draft: ShelfCreateDraft) async throws -> String
}

func filteredShelves(_ catalog: [ShelfCatalogItem], scope: ShelfCatalogScope, query: String, collectionID: String?) -> [ShelfCatalogItem] {
    let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
    return catalog.filter { shelf in
        let matchesScope = scope == .all || (scope == .collections ? shelf.kind == .collection : shelf.kind != .collection)
        return matchesScope && (collectionID == nil || shelf.collectionIDs.contains(collectionID ?? "")) &&
            (query.isEmpty || shelf.name.localizedCaseInsensitiveContains(query) ||
                (shelf.description?.localizedCaseInsensitiveContains(query) ?? false))
    }
}

func shelfPreview(_ shelf: ShelfCatalogItem, catalog: [ShelfCatalogItem]) -> [ShelfPreview] {
    let candidates = shelf.kind == .collection
        ? catalog.filter { $0.collectionIDs.contains(shelf.id) }.flatMap(\.books) : shelf.books
    var seen = Set<String>()
    return Array(candidates.filter { seen.insert($0.id).inserted }.prefix(3))
}
