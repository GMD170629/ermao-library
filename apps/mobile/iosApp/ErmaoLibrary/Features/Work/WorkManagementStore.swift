import Foundation
import Combine
@preconcurrency import ErmaoShared

@MainActor
final class WorkManagementStore: ObservableObject {
    enum Action: Equatable {
        case workUpdated, coverUpdated, rescanQueued, bookDeleted
        case resourceUpdated
        case metadataApplied, kindleQueued, readingStatusUpdated
    }

    @Published private(set) var capabilityChecked = false
    @Published private(set) var supported = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorCode: String?
    @Published private(set) var completedAction: Action?
    @Published private(set) var coverMutation: ErmaoShared.CoverMutationOutcome?
    @Published private(set) var metadataProviders: [ErmaoShared.MetadataProvider] = []
    @Published private(set) var metadataCandidates: [ErmaoShared.MetadataCandidate] = []
    @Published private(set) var kindleSettings: ErmaoShared.KindleSettings?

    private let repository: any ErmaoShared.WorkManagementRepository
    private let context: ErmaoShared.BookManagementContext
    private let bookID: String

    init(
        repository: any ErmaoShared.WorkManagementRepository,
        context: ContentRequestContext,
        bookID: String
    ) {
        self.repository = repository
        self.context = ErmaoShared.PublicKt.createWorkManagementContext(
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS,
            userId: context.userID,
            authorizationVersion: context.authorizationVersion
        )
        self.bookID = bookID
        capabilityChecked = true
        supported = true
    }

    func consumeCompletion() {
        completedAction = nil
        coverMutation = nil
        errorCode = nil
    }

    func setReadingStatus(resourceID: String, status: ErmaoShared.ManagedReadingStatus) {
        run(.readingStatusUpdated) { [repository, context] in
            try await repository.setReadingStatus(context: context, resourceId: resourceID, status: status)
        }
    }

    func setBookReadingStatus(_ status: ErmaoShared.ManagedReadingStatus) {
        run(.readingStatusUpdated) { [repository, context, bookID] in
            try await repository.setBookReadingStatus(context: context, bookId: bookID, status: status)
        }
    }



    private func run(
        _ action: Action,
        operation: @escaping @Sendable () async throws -> any ErmaoShared.WorkManagementResult
    ) {
        runValue {
            let result = try await operation()
            try Self.requireSuccess(result)
            self.completedAction = action
        }
    }



    private func runValue(_ operation: @escaping @MainActor () async throws -> Void) {
        guard !isBusy else { return }
        isBusy = true
        errorCode = nil
        Task {
            do { try await operation(); isBusy = false }
            catch {
                isBusy = false
                errorCode = (error as? WorkManagementClientError)?.code ?? "MANAGEMENT_FAILED"
            }
        }
    }

    private static func requireSuccess(_ result: any ErmaoShared.WorkManagementResult) throws {
        guard ErmaoShared.PublicKt.workManagementResultSucceeded(result: result) else {
            throw WorkManagementClientError(
                code: ErmaoShared.PublicKt.workManagementResultErrorCode(result: result)
                    ?? "MANAGEMENT_INVALID_RESPONSE"
            )
        }
    }

    private static func error(_ result: any ErmaoShared.WorkManagementResult) -> WorkManagementClientError {
        WorkManagementClientError(
            code: ErmaoShared.PublicKt.workManagementResultErrorCode(result: result)
                ?? "MANAGEMENT_INVALID_RESPONSE"
        )
    }
}

@MainActor
final class WorkManagementStoreHolder: ObservableObject {
    let store: WorkManagementStore?
    private var observation: AnyCancellable?

    init(store: WorkManagementStore?) {
        self.store = store
        observation = store?.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
    }
}

private struct WorkManagementClientError: Error {
    let code: String
}
