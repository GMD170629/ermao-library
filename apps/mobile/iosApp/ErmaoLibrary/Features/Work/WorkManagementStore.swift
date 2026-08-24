import Foundation
@preconcurrency import ErmaoShared

@MainActor
final class WorkManagementStore: ObservableObject {
    enum Action: Equatable {
        case workUpdated, coverUpdated
        case resourceUpdated, resourceReclassified
        case metadataApplied, kindleQueued, readingStatusUpdated
    }

    @Published private(set) var capabilityChecked = false
    @Published private(set) var supported = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorCode: String?
    @Published private(set) var completedAction: Action?
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
        errorCode = nil
    }

    func updateWork(
        title: String,
        author: String,
        description: String,
        seriesName: String?,
        seriesIndex: Double?,
        tags: [String]
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
                    tags: tags
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

    func uploadCover(
        data: Data,
        mimeType: String,
        fileName: String,
        sourceNodeID: String,
        title: String,
        description: String?
    ) {
        let bytes = KotlinByteArray(size: Int32(data.count))
        for (index, byte) in data.enumerated() { bytes.set(index: Int32(index), value: Int8(bitPattern: byte)) }
        run(.coverUpdated) { [repository, context, bookID] in
            try await repository.uploadCover(
                context: context,
                bookId: bookID,
                sourceNodeId: sourceNodeID,
                title: title,
                description: description,
                upload: ErmaoShared.CoverUpload(fileName: fileName, mimeType: mimeType, bytes: bytes)
            )
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

    func reclassify(
        _ resource: BookResource,
        kind: ErmaoShared.ManagedMediaKind
    ) {
        runMutation(.resourceReclassified) { [repository, context, bookID] in
            try await repository.reclassifyResource(
                context: context, bookId: bookID, resourceId: resource.id, mediaKind: kind
            )
        }
    }

    func loadMetadata(kind: ErmaoShared.ManagedMediaKind) {
        runValue { [repository, context] in
            let result = try await repository.loadMetadataProviders(context: context, mediaKind: kind)
            let values: [ErmaoShared.MetadataProvider] = try Self.value(result)
            self.metadataProviders = values
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
            let search: ErmaoShared.MetadataSearchResult = try Self.value(result)
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
            let settings: ErmaoShared.KindleSettings = try Self.value(result)
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

    private func checkCapability() {
        Task {
            do {
                let result = try await repository.supportsNativeManagement(context: context)
                let value: KotlinBoolean = try Self.value(result)
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
            let _: ErmaoShared.BookMutationOutcome = try Self.value(result)
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

    private static func value<Value>(_ result: any ErmaoShared.WorkManagementResult) throws -> Value {
        if let failure = result as? ErmaoShared.WorkManagementResultFailure {
            throw WorkManagementClientError(code: failure.error.code)
        }
        guard let content = result as? ErmaoShared.WorkManagementResultContent<AnyObject>,
              let value = content.value as? Value else { throw WorkManagementClientError(code: "MANAGEMENT_INVALID_RESPONSE") }
        return value
    }

    private static func requireSuccess(_ result: any ErmaoShared.WorkManagementResult) throws {
        if let failure = result as? ErmaoShared.WorkManagementResultFailure {
            throw WorkManagementClientError(code: failure.error.code)
        }
        guard result is ErmaoShared.WorkManagementResultContent<AnyObject> else {
            throw WorkManagementClientError(code: "MANAGEMENT_INVALID_RESPONSE")
        }
    }
}

private struct WorkManagementClientError: Error {
    let code: String
}
