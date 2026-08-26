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
        checkCapability()
    }

    func consumeCompletion() {
        completedAction = nil
        coverMutation = nil
        errorCode = nil
    }

    func updateWork(
        title: String,
        author: String,
        description: String,
        seriesName: String?,
        seriesIndex: Double?,
        tags: [String],
        originalTags: [String]
    ) {
        run(.workUpdated) { [repository, context, bookID] in
            try await repository.updateBook(
                context: context,
                bookId: bookID,
                draft: ErmaoShared.BookMetadataDraft(
                    title: title,
                    author: author,
                    description: description,
                    seriesName: seriesName,
                    seriesIndex: seriesIndex.map(KotlinDouble.init(double:)),
                    tags: tags,
                    originalTags: originalTags
                )
            )
        }
    }

    func regenerateCover(resourceID: String) {
        run(.coverUpdated) { [repository, context, bookID] in
            try await repository.regenerateResourceCover(
                context: context,
                bookId: bookID,
                resourceId: resourceID
            )
        }
    }

    func regenerateBookCover(anchoredResourceID: String) {
        run(.coverUpdated) { [repository, context, bookID] in
            try await repository.regenerateBookCover(
                context: context,
                bookId: bookID,
                anchoredResourceId: anchoredResourceID
            )
        }
    }

    func rescanBook(sourceNodeID: String) {
        run(.rescanQueued) { [repository, context] in
            try await repository.rescanBook(context: context, sourceNodeId: sourceNodeID)
        }
    }

    func deleteBook() {
        runValue { [repository, context, bookID] in
            let result = try await repository.deleteBook(context: context, bookId: bookID)
            guard ErmaoShared.PublicKt.workManagementBookDeletionOutcome(result: result) != nil else {
                throw WorkManagementClientError(
                    code: ErmaoShared.PublicKt.workManagementResultErrorCode(result: result)
                        ?? "MANAGEMENT_INVALID_RESPONSE"
                )
            }
            self.completedAction = .bookDeleted
        }
    }

    func uploadCover(
        data: Data,
        mimeType: String,
        fileName: String,
        resourceID: String
    ) {
        let bytes = KotlinByteArray(size: Int32(data.count))
        for (index, byte) in data.enumerated() { bytes.set(index: Int32(index), value: Int8(bitPattern: byte)) }
        runValue { [repository, context, bookID] in
            let result = try await repository.uploadCover(
                context: context,
                bookId: bookID,
                resourceId: resourceID,
                upload: ErmaoShared.CoverUpload(fileName: fileName, mimeType: mimeType, bytes: bytes)
            )
            guard let mutation = ErmaoShared.PublicKt.workManagementCoverMutationOutcome(result: result) else {
                throw Self.error(result)
            }
            self.coverMutation = mutation
            self.completedAction = .coverUpdated
        }
    }

    func updateResource(
        _ resource: BookResource,
        publisher: String?,
        language: String?,
        isbn: String?,
        identifier: String?,
        narrator: String?
    ) {
        runMutation(.resourceUpdated) { [repository, context, bookID] in
            try await repository.updateResource(
                context: context,
                bookId: bookID,
                resourceId: resource.id,
                draft: ErmaoShared.ResourceMetadataDraft(
                    title: nil,
                    description: nil,
                    publisher: publisher,
                    publishedAt: nil,
                    language: language,
                    isbn: isbn,
                    identifier: identifier,
                    narrator: narrator,
                    abridged: nil,
                    resourceIndex: nil
                )
            )
        }
    }

    func loadMetadata() {
        runValue { [repository, context] in
            let result = try await repository.loadMetadataProviders(context: context)
            guard let values = ErmaoShared.PublicKt.workManagementMetadataProviders(result: result) else {
                throw Self.error(result)
            }
            self.metadataProviders = values.compactMap { $0 as? ErmaoShared.MetadataProvider }
        }
    }

    func searchMetadata(providerID: String, sourceNodeID: String, query: String) {
        runValue { [repository, context, bookID] in
            let result = try await repository.searchMetadata(
                context: context,
                bookId: bookID,
                sourceNodeId: sourceNodeID,
                providerId: providerID,
                query: query
            )
            guard let search = ErmaoShared.PublicKt.workManagementMetadataSearchResult(result: result) else {
                throw Self.error(result)
            }
            self.metadataCandidates = search.candidates
        }
    }

    func applyMetadata(
        providerID: String,
        candidate: ErmaoShared.MetadataCandidate,
        fields: Set<ErmaoShared.MetadataField>,
        resourceID: String?,
        sourceNodeID: String,
        applyToAllResources: Bool
    ) {
        run(.metadataApplied) { [repository, context, bookID] in
            try await repository.applyMetadata(
                context: context,
                bookId: bookID,
                sourceNodeId: sourceNodeID,
                providerId: providerID,
                candidate: candidate,
                fields: fields,
                resourceId: resourceID,
                applyToAllResources: applyToAllResources
            )
        }
    }

    func loadKindleSettings() {
        runValue { [repository, context] in
            let result = try await repository.loadKindleSettings(context: context)
            guard let settings = ErmaoShared.PublicKt.workManagementKindleSettings(result: result) else {
                throw Self.error(result)
            }
            guard let settings = settings as? ErmaoShared.KindleSettings else {
                throw WorkManagementClientError(code: "MANAGEMENT_INVALID_RESPONSE")
            }
            self.kindleSettings = settings
        }
    }

    func sendToKindle(assetID: String) {
        run(.kindleQueued) { [repository, context, bookID] in
            try await repository.sendToKindle(context: context, bookId: bookID, assetId: assetID)
        }
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

    private func checkCapability() {
        Task {
            do {
                let result = try await repository.supportsNativeManagement(context: context)
                guard let value = ErmaoShared.PublicKt.workManagementBooleanValue(result: result) else {
                    throw Self.error(result)
                }
                supported = value.boolValue
                capabilityChecked = true
            } catch {
                capabilityChecked = true
                errorCode = "MANAGEMENT_CAPABILITY_FAILED"
            }
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

    private func runMutation(
        _ action: Action,
        operation: @escaping @Sendable () async throws -> any ErmaoShared.WorkManagementResult
    ) {
        runValue {
            let result = try await operation()
            guard ErmaoShared.PublicKt.workManagementBookMutationOutcome(result: result) != nil else {
                throw Self.error(result)
            }
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
