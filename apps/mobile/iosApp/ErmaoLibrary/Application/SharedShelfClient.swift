import Foundation
@preconcurrency import ErmaoShared

actor SharedShelfClient: ShelfClient {
    private let repository: any ErmaoShared.ShelfRepository

    init(repository: any ErmaoShared.ShelfRepository) {
        self.repository = repository
    }

    func fetchShelves(context: ContentRequestContext, bookID: String) async throws -> [ShelfOption] {
        let result = try await repository.loadShelves(
            context: sharedContext(context),
            bookId: bookID
        )
        if let content = result as? ErmaoShared.ShelfResultContent<NSArray> {
            return (content.value ?? []).compactMap { value -> ShelfOption? in
                guard let shelf = value as? ErmaoShared.ShelfSummary else { return nil }
                return ShelfOption(
                    id: shelf.id,
                    name: shelf.name,
                    containsWork: shelf.containsBook,
                    isMembershipEditable: shelf.kind.name == "Static"
                )
            }
        }
        throw mapFailure(result)
    }

    func updateShelf(context: ContentRequestContext, bookID: String, shelf: ShelfOption, add: Bool) async throws {
        guard shelf.isMembershipEditable else { throw ContentClientError.invalidResponse }
        let result = try await repository.updateMembership(
            context: sharedContext(context),
            change: ErmaoShared.ShelfMembershipChange(
                bookId: bookID,
                shelfId: shelf.id,
                shelfKind: .static_,
                membership: add ? .add : .remove
            )
        )
        if result is ErmaoShared.ShelfResultContent<AnyObject> { return }
        throw mapFailure(result)
    }

    private func sharedContext(_ value: ContentRequestContext) -> ErmaoShared.ShelfRequestContext {
        ErmaoShared.PublicKt.createShelfRequestContext(
            profileId: value.profileID,
            displayName: value.profileDisplayName,
            baseUrl: value.baseURL,
            serverIdentity: value.serverIdentity,
            acceptsInsecureTls: value.acceptsInsecureTLS,
            userId: value.userID,
            authorizationVersion: value.authorizationVersion
        )
    }

    private func mapFailure(_ result: Any) -> ContentClientError {
        guard let failure = result as? ErmaoShared.ShelfResultFailure else { return .invalidResponse }
        switch failure.error.kind {
        case .unauthorized: return .unauthorized
        case .offline: return .offline
        case .inaccessible: return .inaccessible
        default: return .transport
        }
    }
}
