import Foundation
@preconcurrency import ErmaoShared

@MainActor
final class WorkManagementStore: ObservableObject {
    struct PendingOwnership {
        let volumeID: String
        let workID: String?
        let workTitle: String
        let workAuthor: String
        let mediaKind: LibraryMediaKind
    }
    enum Action: Equatable {
        case workUpdated, coverUpdated, workDeleted
        case volumeUpdated, volumeReclassified, volumeSplit, volumeDeleted
        case metadataApplied, kindleQueued, readingStatusUpdated
    }

    @Published private(set) var capabilityChecked = false
    @Published private(set) var supported = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorCode: String?
    @Published private(set) var completedAction: Action?
    @Published private(set) var lastOutcome: ErmaoShared.WorkMutationOutcome?
    @Published private(set) var pendingOwnership: PendingOwnership?
    @Published private(set) var metadataProviders: [ErmaoShared.MetadataProvider] = []
    @Published private(set) var metadataCandidates: [ErmaoShared.MetadataCandidate] = []
    @Published private(set) var kindleSettings: ErmaoShared.KindleSettings?

    private let repository: any ErmaoShared.WorkManagementRepository
    private let context: ErmaoShared.WorkManagementContext
    private let workID: String

    init(
        repository: any ErmaoShared.WorkManagementRepository,
        context: ContentRequestContext,
        workID: String
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
        self.workID = workID
        checkCapability()
    }

    func consumeCompletion() {
        completedAction = nil
        lastOutcome = nil
        pendingOwnership = nil
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
        run(.workUpdated) { [repository, context, workID] in
            try await repository.updateWork(
                context: context,
                workId: workID,
                draft: ErmaoShared.WorkMetadataDraft(
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

    func regenerateCover() {
        run(.coverUpdated) { [repository, context, workID] in
            try await repository.regenerateCover(context: context, workId: workID)
        }
    }

    func uploadCover(data: Data, mimeType: String, fileName: String) {
        let bytes = KotlinByteArray(size: Int32(data.count))
        for (index, byte) in data.enumerated() { bytes.set(index: Int32(index), value: Int8(bitPattern: byte)) }
        run(.coverUpdated) { [repository, context, workID] in
            try await repository.uploadCover(
                context: context,
                workId: workID,
                upload: ErmaoShared.CoverUpload(fileName: fileName, mimeType: mimeType, bytes: bytes)
            )
        }
    }

    func deleteWork() {
        runMutation(.workDeleted) { [repository, context, workID] in
            try await repository.deleteWork(context: context, workId: workID)
        }
    }

    func updateVolume(
        _ volume: WorkVolume,
        title: String,
        index: Double?,
        sortOrder: Int32,
        publisher: String?,
        language: String?,
        isbn: String?,
        identifier: String?,
        narrator: String?
    ) {
        runMutation(.volumeUpdated) { [repository, context, workID] in
            try await repository.updateVolume(
                context: context,
                workId: workID,
                volumeId: volume.id,
                draft: ErmaoShared.VolumeMetadataDraft(
                    title: title,
                    volumeIndex: index.map(KotlinDouble.init(double:)),
                    sortOrder: sortOrder,
                    publisher: publisher,
                    language: language,
                    isbn: isbn,
                    identifier: identifier,
                    narrator: narrator
                )
            )
        }
    }

    func reclassify(
        _ volume: WorkVolume,
        kind: ErmaoShared.ManagedMediaKind,
        work: WorkCard,
        localKind: LibraryMediaKind
    ) {
        pendingOwnership = PendingOwnership(
            volumeID: volume.id, workID: work.id, workTitle: work.title,
            workAuthor: work.author, mediaKind: localKind
        )
        runMutation(.volumeReclassified) { [repository, context, workID] in
            try await repository.reclassifyVolume(
                context: context, workId: workID, volumeId: volume.id, mediaKind: kind
            )
        }
    }

    func split(_ volume: WorkVolume, title: String, author: String?, mediaKind: LibraryMediaKind) {
        pendingOwnership = PendingOwnership(
            volumeID: volume.id, workID: nil, workTitle: title,
            workAuthor: author ?? "", mediaKind: mediaKind
        )
        runMutation(.volumeSplit) { [repository, context, workID] in
            try await repository.splitVolume(
                context: context, workId: workID, volumeId: volume.id, title: title, author: author
            )
        }
    }

    func deleteVolume(_ volume: WorkVolume) {
        runMutation(.volumeDeleted) { [repository, context, workID] in
            try await repository.deleteVolume(context: context, workId: workID, volumeId: volume.id)
        }
    }

    func loadMetadata(kind: ErmaoShared.ManagedMediaKind) {
        runValue { [repository, context] in
            let result = try await repository.loadMetadataProviders(context: context, mediaKind: kind)
            let values: [ErmaoShared.MetadataProvider] = try Self.value(result)
            self.metadataProviders = values
        }
    }

    func searchMetadata(providerID: String, query: String) {
        runValue { [repository, context, workID] in
            let result = try await repository.searchMetadata(
                context: context, workId: workID, providerId: providerID, query: query
            )
            let search: ErmaoShared.MetadataSearchResult = try Self.value(result)
            self.metadataCandidates = search.candidates
        }
    }

    func applyMetadata(
        providerID: String,
        candidate: ErmaoShared.MetadataCandidate,
        fields: Set<ErmaoShared.MetadataField>,
        volumeID: String?,
        applyToAllVolumes: Bool
    ) {
        run(.metadataApplied) { [repository, context, workID] in
            try await repository.applyMetadata(
                context: context,
                workId: workID,
                providerId: providerID,
                candidate: candidate,
                fields: fields,
                volumeId: volumeID,
                applyToAllVolumes: applyToAllVolumes
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

    func sendToKindle(fileID: String) {
        run(.kindleQueued) { [repository, context, workID] in
            try await repository.sendToKindle(context: context, workId: workID, fileId: fileID)
        }
    }

    func setReadingStatus(volumeID: String, status: ErmaoShared.ManagedReadingStatus) {
        run(.readingStatusUpdated) { [repository, context] in
            try await repository.setReadingStatus(context: context, volumeId: volumeID, status: status)
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
            let _: KotlinUnit = try Self.value(result)
            self.completedAction = action
        }
    }

    private func runMutation(
        _ action: Action,
        operation: @escaping @Sendable () async throws -> any ErmaoShared.WorkManagementResult
    ) {
        runValue {
            let result = try await operation()
            let outcome: ErmaoShared.WorkMutationOutcome = try Self.value(result)
            self.lastOutcome = outcome
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
}

private struct WorkManagementClientError: Error {
    let code: String
}
