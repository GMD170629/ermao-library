import Foundation
@preconcurrency import ErmaoShared

actor SharedShelfCatalogClient: ShelfCatalogClient {
    private let repository: any ErmaoShared.ShelfCatalogRepository

    init(repository: any ErmaoShared.ShelfCatalogRepository) { self.repository = repository }

    func catalog(context: ContentRequestContext) async throws -> [ShelfCatalogItem] {
        let result = try await repository.loadCatalog(context: sharedContext(context))
        guard let response = result as? ErmaoShared.ShelfResultContent<NSArray>, let values = response.value else {
            throw failure(result)
        }
        return try values.map { value in
            guard let entry = value as? ErmaoShared.ShelfCatalogEntry else { throw ContentClientError.invalidResponse }
            return try item(entry)
        }
    }

    func detail(context: ContentRequestContext, shelfID: String, page: Int) async throws -> ShelfCatalogDetail {
        guard let pageNumber = Int32(exactly: page), pageNumber > 0 else { throw ContentClientError.invalidResponse }
        let result = try await repository.loadPage(context: sharedContext(context), shelfId: shelfID, page: pageNumber)
        guard let response = result as? ErmaoShared.ShelfResultContent<ErmaoShared.ShelfCatalogPage>, let value = response.value else {
            throw failure(result)
        }
        return ShelfCatalogDetail(shelf: try item(value.shelf), page: Int(value.page), totalPages: Int(value.totalPages))
    }

    func create(context: ContentRequestContext, draft: ShelfCreateDraft) async throws -> String {
        guard draft.isValid else { throw ContentClientError.invalidResponse }
        let result = try await repository.createShelf(context: sharedContext(context), input: ErmaoShared.CreateShelfInput(
            name: draft.name.trimmingCharacters(in: .whitespacesAndNewlines),
            description: draft.description.trimmingCharacters(in: .whitespacesAndNewlines),
            kind: draft.isCollection ? .collection : .static_,
            memberShelfIds: draft.isCollection ? draft.memberIDs.sorted() : []
        ))
        guard let response = result as? ErmaoShared.ShelfResultContent<NSString>, let id = response.value else { throw failure(result) }
        return id as String
    }

    private func item(_ value: ErmaoShared.ShelfCatalogEntry) throws -> ShelfCatalogItem {
        let kind: ShelfCatalogKind
        switch value.kind {
        case .static_: kind = .standard
        case .smart: kind = .smart
        case .collection: kind = .collection
        default: throw ContentClientError.invalidResponse
        }
        return ShelfCatalogItem(
            id: value.id, name: value.name, description: value.description_, kind: kind,
            count: Int(value.count), books: value.books.map {
                ShelfPreview(id: $0.id, title: $0.title, author: $0.author,
                             cover: $0.coverUrl.isEmpty ? nil : CoverReference(path: $0.coverUrl), progress: $0.progress)
            }, collectionIDs: value.collectionIds, rulesSupported: value.rulesSupported
        )
    }

    private func sharedContext(_ value: ContentRequestContext) -> ErmaoShared.ShelfRequestContext {
        ErmaoShared.PublicKt.createShelfRequestContext(
            profileId: value.profileID, displayName: value.profileDisplayName, baseUrl: value.baseURL,
            serverIdentity: value.serverIdentity, acceptsInsecureTls: value.acceptsInsecureTLS,
            userId: value.userID, authorizationVersion: value.authorizationVersion
        )
    }

    private func failure(_ result: any ErmaoShared.ShelfResult) -> ContentClientError {
        guard let failure = result as? ErmaoShared.ShelfResultFailure else { return .invalidResponse }
        switch failure.error.kind {
        case .unauthorized: return .unauthorized
        case .inaccessible: return .inaccessible
        case .offline: return .offline
        default: return .transport
        }
    }
}

enum ShelfCatalogComposition {
    static func makeClient() -> any ShelfCatalogClient {
        #if DEBUG
        if ProcessInfo.processInfo.environment[ContentUITestFixture.launchEnvironmentKey] == "1" {
            return FixtureShelfCatalogClient()
        }
        #endif
        return SharedShelfCatalogClient(repository: IosCompositionKt.createIosShelfCatalogRepository(cookieStore: KeychainCookiePayloadStore()))
    }
}

#if DEBUG
/// Isolated UI-test catalog. It never reads or writes the user's server.
private actor FixtureShelfCatalogClient: ShelfCatalogClient {
    private var entries: [ShelfCatalogItem] = [
        ShelfCatalogItem(id: "plan", name: "Reading Plan", description: nil, kind: .collection, count: 2,
                         books: [], collectionIDs: [], rulesSupported: true),
        ShelfCatalogItem(id: "to-read", name: "To Read", description: nil, kind: .standard, count: 3,
                         books: FixtureShelfCatalogClient.fixtureBooks, collectionIDs: ["plan"], rulesSupported: true),
        ShelfCatalogItem(id: "reading", name: "Currently Reading", description: nil, kind: .smart, count: 3,
                         books: FixtureShelfCatalogClient.fixtureBooks, collectionIDs: ["plan"], rulesSupported: true),
        ShelfCatalogItem(id: "favorites", name: "Favorites", description: nil, kind: .standard, count: 3,
                         books: FixtureShelfCatalogClient.fixtureBooks, collectionIDs: [], rulesSupported: true)
    ]
    private static let fixtureBooks = [
        ShelfPreview(id: "pride-and-prejudice", title: "Pride and Prejudice", author: "Jane Austen", cover: nil, progress: 32),
        ShelfPreview(id: "the-left-hand-of-darkness", title: "The Left Hand of Darkness", author: "Ursula K. Le Guin", cover: nil, progress: 0),
        ShelfPreview(id: "earthsea", title: "Earthsea", author: "Ursula K. Le Guin", cover: nil, progress: 0)
    ]
    func catalog(context: ContentRequestContext) -> [ShelfCatalogItem] { entries }
    func detail(context: ContentRequestContext, shelfID: String, page: Int) throws -> ShelfCatalogDetail {
        guard let shelf = entries.first(where: { $0.id == shelfID }) else { throw ContentClientError.inaccessible }
        return ShelfCatalogDetail(shelf: shelf, page: 1, totalPages: 1)
    }
    func create(context: ContentRequestContext, draft: ShelfCreateDraft) -> String {
        let id = UUID().uuidString
        let members = entries.filter { draft.memberIDs.contains($0.id) }
        entries.append(ShelfCatalogItem(id: id, name: draft.name, description: draft.description,
            kind: draft.isCollection ? .collection : .standard, count: draft.isCollection ? members.count : 0,
            books: [], collectionIDs: [], rulesSupported: true))
        if draft.isCollection {
            entries = entries.map { shelf in
                guard draft.memberIDs.contains(shelf.id) else { return shelf }
                return ShelfCatalogItem(id: shelf.id, name: shelf.name, description: shelf.description, kind: shelf.kind,
                    count: shelf.count, books: shelf.books, collectionIDs: shelf.collectionIDs + [id], rulesSupported: shelf.rulesSupported)
            }
        }
        return id
    }
}
#endif
