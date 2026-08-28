import Foundation
@preconcurrency import ErmaoShared

/// Native lifecycle and storage binding for the single shared Downloads use case.
@MainActor
final class SharedManagedDownloadTransfer: ManagedDownloadTransferring {
    private let cookieStore: KeychainCookiePayloadStore
    private var activeNamespace: String?
    private var runtime: DownloadResourceRuntime?
    private var catalog: IosDownloadCatalog?
    private var gateway: KtorDownloadsGateway?

    init(cookieStore: KeychainCookiePayloadStore) { self.cookieStore = cookieStore }

    private func activate(context: ContentRequestContext, repository: ManagedDownloadStore,
                          changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws {
        if activeNamespace != context.namespaceKey {
            gateway?.close()
            let catalog = IosDownloadCatalog(context: context, repository: repository, changed: changed)
            let gateway = IosCompositionKt.createIosDownloadsGateway(
                cookieStore: cookieStore, profileId: context.profileID, displayName: context.profileDisplayName,
                baseUrl: context.baseURL, serverIdentity: context.serverIdentity, acceptsInsecureTls: context.acceptsInsecureTLS
            )
            self.catalog = catalog
            self.gateway = gateway
            runtime = PublicKt.createDownloadResourceRuntime(catalog: catalog, gateway: gateway)
            activeNamespace = context.namespaceKey
            try await runtime?.recoverInterrupted(namespace: context.downloadRequestContext.namespace_)
        }
    }

    func readerCoordinator(context: ContentRequestContext, repository: ManagedDownloadStore,
                           changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws -> ReaderLaunchCoordinator {
        try await activate(context: context, repository: repository, changed: changed)
        guard let catalog, let gateway else { throw ManagedDownloadTransferError.invalidResponse }
        return ReaderLaunchCoordinator(catalog: catalog, gateway: gateway)
    }

    func download(context: ContentRequestContext, resourceID: String, repository: ManagedDownloadStore,
                  expectedDescriptor: DownloadDescriptor? = nil,
                  changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws {
        try await activate(context: context, repository: repository, changed: changed)
        guard let runtime, let catalog else { throw ManagedDownloadTransferError.invalidResponse }
        let cancellation = DownloadCancellation()
        try await withTaskCancellationHandler {
            let result = try await runtime.download(
                context: context.downloadRequestContext, resourceId: resourceID, taskId: UUID().uuidString,
                sink: IosDownloadFileSink(catalog: catalog, repository: repository), observer: nil,
                cancellation: cancellation, expectedDescriptor: expectedDescriptor
            )
            try Task.checkCancellation()
            if let failure = result as? DownloadResourceResultFailure {
                throw Self.map(failure.error)
            }
            guard result is DownloadResourceResultCompleted else { throw ManagedDownloadTransferError.invalidResponse }
        } onCancel: { cancellation.cancel() }
    }

    private static func map(_ error: ErmaoShared.AppError) -> ManagedDownloadTransferError {
        if error.code == "ASSET_VERSION_CHANGED" { return .versionChanged }
        return switch error.kind {
        case .unauthorized: .unauthorized
        case .forbidden, .notfoundorunavailable, .gone: .inaccessible
        case .storagefailure: .insufficientSpace
        case .cancelled: .cancelled
        case .protocolviolation: .invalidResponse
        default: .transportUnavailable
        }
    }
}

private final class IosDownloadCatalog: NSObject, DownloadCatalogRepository, @unchecked Sendable {
    private let context: ContentRequestContext
    private let repository: ManagedDownloadStore
    private let changed: @Sendable (ManagedDownloadRecord) async -> Void
    init(context: ContentRequestContext, repository: ManagedDownloadStore,
         changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) {
        self.context = context; self.repository = repository; self.changed = changed
    }

    private func requireNamespace(_ namespace: DownloadNamespace) throws {
        guard namespace.serverIdentity == context.serverIdentity, namespace.userId == context.userID,
              namespace.authorizationVersion == context.authorizationVersion else { throw ManagedDownloadTransferError.unauthorized }
    }

    func record(taskID: String) async throws -> ManagedDownloadRecord {
        guard let record = try await repository.records(namespace: context.namespaceKey).first(where: { $0.id == taskID }) else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        return record
    }

    func listTasks(namespace: DownloadNamespace) async throws -> [DownloadTask] {
        try requireNamespace(namespace)
        return try await repository.records(namespace: context.namespaceKey).compactMap { record in
            guard let encoded = record.sharedTaskJSON else { return nil }
            let task = try DownloadCatalogCodec.shared.decode(serialized: encoded)
            try requireNamespace(task.descriptor.identity.namespace_)
            return Self.validated(task: task, record: record)
        }
    }

    private static func validated(task: DownloadTask, record: ManagedDownloadRecord) -> DownloadTask {
        guard task.artifact != nil && !record.isVerifiedOfflineCopy else { return task }
        return DownloadTask(id: task.id, descriptor: task.descriptor, status: .failedterminal,
                            transferredBytes: task.transferredBytes, failureCode: "DOWNLOAD_LOCAL_FILE_INVALID", artifact: nil)
    }

    func findTask(descriptor: DownloadDescriptor) async throws -> DownloadTask? {
        try requireNamespace(descriptor.identity.namespace_)
        let candidates = try await repository.records(namespace: context.namespaceKey)
        for record in candidates where record.resourceID == descriptor.identity.resourceId && record.assetID == descriptor.identity.assetId {
            if let encoded = record.sharedTaskJSON {
                let task = try DownloadCatalogCodec.shared.decode(serialized: encoded)
                if task.matchesDescriptor(candidate: descriptor) { return Self.validated(task: task, record: record) }
                continue
            }
            // Migrate an existing user download in place; no file deletion or replacement.
            guard record.bookID == descriptor.identity.bookId, record.expectedBytes == descriptor.totalBytes,
                  record.format.caseInsensitiveCompare(descriptor.format) == .orderedSame,
                  record.mimeType == descriptor.source.mimeType else { continue }
            let artifact = record.isVerifiedOfflineCopy ? CompletedDownloadArtifact(
                descriptor: descriptor, localReference: record.localRelativePath ?? "",
                verifiedBytes: record.receivedBytes,
                completedAtEpochMillis: Int64((record.completedAt ?? record.updatedAt).timeIntervalSince1970 * 1000),
                lastOpenedAtEpochMillis: record.lastOpenedAt.map { KotlinLong(value: Int64($0.timeIntervalSince1970 * 1000)) }
            ) : nil
            let task = DownloadTask(id: record.id, descriptor: descriptor, status: record.state.sharedStatus,
                                    transferredBytes: record.receivedBytes, failureCode: record.stableErrorCode, artifact: artifact)
            try await saveTask(task: task)
            return task
        }
        return nil
    }

    func saveTask(task: DownloadTask) async throws {
        try requireNamespace(task.descriptor.identity.namespace_)
        let previous = try await repository.records(namespace: context.namespaceKey).first { $0.id == task.id }
        let descriptor = task.descriptor
        guard let readerType = ManagedDownloadReaderType(rawValue: descriptor.readerType.name.lowercased()) else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        let artifact = task.artifact
        let record = ManagedDownloadRecord(
            id: task.id, namespace: context.namespaceKey, bookID: descriptor.identity.bookId,
            bookTitle: descriptor.bookTitle, bookAuthor: descriptor.bookAuthor,
            resourceID: descriptor.identity.resourceId, resourceTitle: descriptor.resourceTitle,
            assetID: descriptor.identity.assetId, format: descriptor.format.uppercased(), mimeType: descriptor.source.mimeType,
            readerType: readerType, state: Self.nativeStatus(task.status),
            verification: artifact == nil ? .pending : .verified, expectedBytes: descriptor.totalBytes,
            artifactKind: descriptor.artifactKind == .originalpageset ? .originalPageSet : .singleOriginalAsset,
            receivedBytes: task.transferredBytes, localRelativePath: artifact?.localReference,
            stableErrorCode: task.failureCode, createdAt: previous?.createdAt ?? Date(), updatedAt: Date(),
            completedAt: artifact.map { Date(timeIntervalSince1970: Double($0.completedAtEpochMillis) / 1000) },
            lastOpenedAt: previous?.lastOpenedAt, sharedTaskJSON: DownloadCatalogCodec.shared.encode(task: task)
        )
        try await repository.update(record)
        await changed(record)
    }

    func listArtifacts(namespace: DownloadNamespace) async throws -> [CompletedDownloadArtifact] {
        try await listTasks(namespace: namespace).compactMap(\.artifact)
    }
    func deleteTask(namespace: DownloadNamespace, taskId: String) async throws {
        try requireNamespace(namespace)
        let stored = try await record(taskID: taskId)
        try await repository.remove(stored)
    }
    func deleteArtifact(namespace: DownloadNamespace, identity: DownloadIdentity) async throws {
        try requireNamespace(namespace)
        for record in try await repository.records(namespace: context.namespaceKey) where record.resourceID == identity.resourceId && record.assetID == identity.assetId {
            try await repository.remove(record)
        }
    }
    func clearNamespace(namespace: DownloadNamespace) async throws {
        try requireNamespace(namespace)
        try await repository.removeNamespace(context.namespaceKey)
    }
    private static func nativeStatus(_ status: DownloadTaskStatus) -> ManagedDownloadState {
        switch status {
        case .queued: .queued
        case .downloading: .downloading
        case .completed: .completed
        case .failedretryable, .insufficientspace: .failedRetryable
        case .failedterminal: .failedTerminal
        default: .paused
        }
    }
}

extension ManagedDownloadState {
    var sharedStatus: DownloadTaskStatus {
        switch self {
        case .queued: .queued
        case .downloading: .downloading
        case .paused: .paused
        case .completed: .completed
        case .failedRetryable: .failedretryable
        case .failedTerminal: .failedterminal
        }
    }
}

private final class IosDownloadFileSink: NSObject, DownloadByteSink, DownloadBundleByteSink {
    private let catalog: IosDownloadCatalog
    private let repository: ManagedDownloadStore
    init(catalog: IosDownloadCatalog, repository: ManagedDownloadStore) { self.catalog = catalog; self.repository = repository }
    func inspect(request: DownloadSinkRequest) async throws -> DownloadStoredBytes {
        let record = try await catalog.record(taskID: request.taskId)
        guard record.resourceID == request.resourceId, record.assetID == request.assetId,
              record.expectedBytes == request.expectedTotalBytes else { throw ManagedDownloadTransferError.invalidResponse }
        return try await repository.storedBytes(for: record)
    }
    func begin(request: DownloadSinkRequest) async throws -> DownloadByteSinkSession {
        let record = try await catalog.record(taskID: request.taskId)
        guard request.resourceId == record.resourceID, request.assetId == record.assetID,
              record.expectedBytes == request.expectedTotalBytes else { throw ManagedDownloadTransferError.invalidResponse }
        let destination = try await repository.destination(for: record)
        return try SharedPartialFileSession(fileURL: destination.partialFileURL, resumeFromBytes: request.resumeFromBytes) { [repository] bytes in
            try await repository.publishFile(record: record, destination: destination, verifiedBytes: bytes)
        }
    }
    func beginBundle(request: DownloadBundleSinkRequest) async throws -> DownloadBundleByteSinkSession {
        let record = try await catalog.record(taskID: request.taskId)
        guard record.effectiveArtifactKind == .originalPageSet, request.resourceId == record.resourceID,
              request.artifactId == record.assetID, record.expectedBytes == request.expectedTotalBytes else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        let destination = try await repository.destination(for: record)
        return try SharedPageSetSinkSession(request: request, stagingDirectory: destination.partialFileURL) { [repository] bytes in
            try await repository.publishFile(record: record, destination: destination, verifiedBytes: bytes)
        }
    }
}

private final class SharedPartialFileSession: NSObject, DownloadByteSinkSession, @unchecked Sendable {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "com.ermao.library.download-file-sink")
    private var handle: FileHandle?
    private let publish: (Int64) async throws -> String
    init(fileURL: URL, resumeFromBytes: Int64, publish: @escaping (Int64) async throws -> String) throws {
        self.publish = publish
        self.fileURL = fileURL
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            FileManager.default.createFile(atPath: fileURL.path, contents: nil, attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        }
        let size = (try FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber)?.int64Value ?? 0
        guard resumeFromBytes == 0 || size == resumeFromBytes else { throw ManagedDownloadTransferError.invalidResponse }
        handle = try FileHandle(forWritingTo: fileURL)
        if resumeFromBytes == 0 { try handle?.truncate(atOffset: 0) }
        else { try handle?.seekToEnd() }
    }
    func write(bytes: KotlinByteArray) async throws {
        let data = bytes.foundationData()
        try queue.sync { guard let handle else { throw ManagedDownloadTransferError.invalidResponse }; try handle.write(contentsOf: data) }
    }
    func commit(expectedTotalBytes: Int64) async throws -> String {
        try queue.sync {
            guard let handle else { throw ManagedDownloadTransferError.invalidResponse }
            try handle.synchronize(); try handle.close(); self.handle = nil
            let size = try FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber
            guard size?.int64Value == expectedTotalBytes else { throw ManagedDownloadTransferError.invalidResponse }
        }
        return try await publish(expectedTotalBytes)
    }
    func abort() async throws { try queue.sync { try handle?.close(); handle = nil; if FileManager.default.fileExists(atPath: fileURL.path) { try FileManager.default.removeItem(at: fileURL) } } }
    func pause() async throws { try queue.sync { try handle?.synchronize(); try handle?.close(); handle = nil } }
}

private struct SharedPageSetManifest: Codable {
    let contractVersion: Int
    let artifactKind: String
    let resourceId: String
    let artifactId: String
    let totalBytes: Int64
    let members: [SharedPageSetMember]
}

private struct SharedPageSetMember: Codable {
    let assetId: String
    let sequenceIndex: Int
    let mimeType: String
    let sizeBytes: Int64
    let fileName: String
}

private final class SharedPageSetSinkSession: NSObject, DownloadBundleByteSinkSession, @unchecked Sendable {
    private let request: DownloadBundleSinkRequest
    private let stagingDirectory: URL
    private let lock = NSLock()
    private var committedMembers: [Int: SharedPageSetMember] = [:]
    private var closed = false

    private let publish: (Int64) async throws -> String
    init(request: DownloadBundleSinkRequest, stagingDirectory: URL, publish: @escaping (Int64) async throws -> String) throws {
        self.publish = publish
        self.request = request
        self.stagingDirectory = stagingDirectory
        if FileManager.default.fileExists(atPath: stagingDirectory.path) { try FileManager.default.removeItem(at: stagingDirectory) }
        try FileManager.default.createDirectory(
            at: stagingDirectory,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
    }

    func beginMember(request: DownloadBundleMemberSinkRequest) async throws -> DownloadByteSinkSession {
        let index = Int(request.sequenceIndex)
        guard index >= 0, index < Int(self.request.memberCount),
              !request.assetId.isEmpty,
              request.expectedBytes > 0 else { throw ManagedDownloadTransferError.invalidResponse }
        let duplicate = lock.withLock { committedMembers[index] != nil || closed }
        guard !duplicate else { throw ManagedDownloadTransferError.invalidResponse }
        let fileName = String(format: "%06d-%@.%@", index, stableMemberName(request.assetId), try extensionForMime(request.mimeType))
        let partURL = stagingDirectory.appendingPathComponent(".\(fileName).part")
        let finalURL = stagingDirectory.appendingPathComponent(fileName)
        return try SharedPartialFileSession(fileURL: partURL, resumeFromBytes: 0) { [weak self] bytes in
            guard bytes == request.expectedBytes else { throw ManagedDownloadTransferError.invalidResponse }
            try FileManager.default.moveItem(at: partURL, to: finalURL)
            guard let self else { throw ManagedDownloadTransferError.invalidResponse }
            return try self.lock.withLock {
                guard !self.closed, self.committedMembers[index] == nil else {
                    throw ManagedDownloadTransferError.invalidResponse
                }
                self.committedMembers[index] = SharedPageSetMember(
                    assetId: request.assetId,
                    sequenceIndex: index,
                    mimeType: request.mimeType,
                    sizeBytes: request.expectedBytes,
                    fileName: fileName
                )
                return fileName
            }
        }
    }

    func commit() async throws -> String {
        try lock.withLock {
            guard !closed else { throw ManagedDownloadTransferError.invalidResponse }
            let ordered = (0..<Int(request.memberCount)).compactMap { committedMembers[$0] }
            guard ordered.count == Int(request.memberCount),
                  ordered.reduce(Int64(0), { $0 + $1.sizeBytes }) == request.expectedTotalBytes else {
                throw ManagedDownloadTransferError.invalidResponse
            }
            for member in ordered {
                let fileURL = stagingDirectory.appendingPathComponent(member.fileName)
                guard fileSize(fileURL) == member.sizeBytes,
                      detectImageMime(fileURL) == member.mimeType else {
                    throw ManagedDownloadTransferError.invalidResponse
                }
            }
            let manifest = SharedPageSetManifest(
                contractVersion: 4,
                artifactKind: "OriginalPageSet",
                resourceId: request.resourceId,
                artifactId: request.artifactId,
                totalBytes: request.expectedTotalBytes,
                members: ordered
            )
            try JSONEncoder().encode(manifest).write(
                to: stagingDirectory.appendingPathComponent("bundle.json"),
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            closed = true
        }
        return try await publish(request.expectedTotalBytes)
    }

    func abort() async throws {
        let shouldDelete = lock.withLock {
            let value = !closed
            closed = true
            return value
        }
        if shouldDelete && FileManager.default.fileExists(atPath: stagingDirectory.path) { try FileManager.default.removeItem(at: stagingDirectory) }
    }
}

private func stableMemberName(_ value: String) -> String {
    Data(value.utf8).base64EncodedString()
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "+", with: "-")
        .prefix(32).description
}

private func extensionForMime(_ mimeType: String) throws -> String {
    switch mimeType.lowercased() {
    case "image/jpeg": "jpg"
    case "image/png": "png"
    case "image/gif": "gif"
    case "image/webp": "webp"
    default: throw ManagedDownloadTransferError.invalidResponse
    }
}

private func fileSize(_ url: URL) -> Int64? {
    (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value
}

private func detectImageMime(_ url: URL) -> String? {
    guard let data = try? Data(contentsOf: url, options: [.mappedIfSafe]), data.count >= 3 else { return nil }
    let bytes = [UInt8](data.prefix(16))
    if bytes.count >= 3, bytes[0...2].elementsEqual([0xFF, 0xD8, 0xFF]) { return "image/jpeg" }
    if bytes.count >= 8, bytes[0..<8].elementsEqual([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) { return "image/png" }
    if bytes.count >= 6, String(bytes: bytes[0..<6], encoding: .ascii).map({ ["GIF87a", "GIF89a"].contains($0) }) == true { return "image/gif" }
    if bytes.count >= 12, String(bytes: bytes[0..<4], encoding: .ascii) == "RIFF", String(bytes: bytes[8..<12], encoding: .ascii) == "WEBP" { return "image/webp" }
    return nil
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
