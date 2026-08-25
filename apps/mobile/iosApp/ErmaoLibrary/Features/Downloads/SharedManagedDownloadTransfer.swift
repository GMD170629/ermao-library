import Foundation
@preconcurrency import ErmaoShared

/// Foreground-only authenticated transfer. The device owns manifest/task state;
/// the server only authorizes a Reader resource and serves its Asset bytes.
final class SharedManagedDownloadTransfer: ManagedDownloadTransferring, @unchecked Sendable {
    private let cookieStore: KeychainCookiePayloadStore
    private let descriptors = SharedDownloadDescriptorCache()

    init(cookieStore: KeychainCookiePayloadStore) { self.cookieStore = cookieStore }

    func prepare(context: ContentRequestContext, resourceID: String) async throws -> ManagedDownloadBootstrap {
        let descriptor = try await loadDescriptor(context: context, resourceID: resourceID)
        descriptors.save(descriptor, key: descriptorKey(context, resourceID))
        return ManagedDownloadBootstrap(
            bookID: descriptor.identity.bookId,
            resourceID: descriptor.identity.resourceId,
            assetID: descriptor.identity.assetId,
            readerType: try readerType(descriptor.readerType),
            expectedBytes: descriptor.source.totalBytes
        )
    }

    func download(_ request: ManagedDownloadRequest, progress: @escaping @Sendable (ManagedDownloadProgress) async -> Void) async throws -> ManagedDownloadReceipt {
        let key = descriptorKey(request.context, request.record.resourceID)
        let descriptor: ErmaoShared.DownloadDescriptor
        if let cached = descriptors.value(for: key) {
            descriptor = cached
        } else {
            descriptor = try await loadDescriptor(
                context: request.context,
                resourceID: request.record.resourceID
            )
        }
        guard let expectedBytes = request.record.expectedBytes else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        guard descriptor.identity.bookId == request.record.bookID,
              descriptor.identity.resourceId == request.record.resourceID,
              descriptor.identity.assetId == request.record.assetID,
              descriptor.source.totalBytes == expectedBytes else { throw ManagedDownloadTransferError.invalidResponse }
        descriptors.save(descriptor, key: key)
        let sink = SharedPartialFileSink(record: request.record, destination: request.destination)
        let observer = SharedDownloadProgressSink { transferred, total in
            Task { await progress(ManagedDownloadProgress(receivedBytes: transferred, expectedBytes: total)) }
        }
        let partialBytes = ((try? FileManager.default.attributesOfItem(atPath: request.destination.partialFileURL.path)[.size]) as? NSNumber)?.int64Value ?? 0
        let resumeBytes = partialBytes > 0 && partialBytes < expectedBytes ? partialBytes : 0
        if resumeBytes == 0 && partialBytes > 0 { try? FileManager.default.removeItem(at: request.destination.partialFileURL) }
        let result = try await makeGateway(request.context).transfer(
            context: sharedContext(request.context),
            request: DownloadTransferRequest(
                taskId: request.record.id,
                descriptor: descriptor,
                resumeFromBytes: resumeBytes,
                ifRangeValidator: nil,
                preservePartialOnCancellation: true
            ),
            sink: sink,
            progressObserver: observer
        )
        guard let success = result as? ErmaoShared.DownloadTransferResultSuccess else {
            if let failure = result as? ErmaoShared.DownloadTransferResultFailure { throw map(failure.error) }
            throw ManagedDownloadTransferError.invalidResponse
        }
        return ManagedDownloadReceipt(receivedBytes: success.transfer.verifiedBytes, expectedBytes: descriptor.source.totalBytes)
    }

    private func makeGateway(_ context: ContentRequestContext) -> KtorDownloadsGateway {
        IosCompositionKt.createIosDownloadsGateway(
            cookieStore: cookieStore, profileId: context.profileID, displayName: context.profileDisplayName,
            baseUrl: context.baseURL, serverIdentity: context.serverIdentity, acceptsInsecureTls: context.acceptsInsecureTLS
        )
    }

    private func loadDescriptor(context: ContentRequestContext, resourceID: String) async throws -> ErmaoShared.DownloadDescriptor {
        let result = try await makeGateway(context).load(context: sharedContext(context), resourceId: resourceID)
        if let success = result as? ErmaoShared.DownloadBootstrapResultSuccess,
           success.bootstrap.descriptor.identity.resourceId == resourceID {
            return success.bootstrap.descriptor
        }
        if let failure = result as? ErmaoShared.DownloadBootstrapResultFailure { throw map(failure.error) }
        throw ManagedDownloadTransferError.invalidResponse
    }

    private func sharedContext(_ context: ContentRequestContext) -> ErmaoShared.DownloadRequestContext {
        PublicKt.createDownloadRequestContext(
            profileId: context.profileID, displayName: context.profileDisplayName, baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity, acceptsInsecureTls: context.acceptsInsecureTLS,
            userId: context.userID, authorizationVersion: context.authorizationVersion
        )
    }

    private func descriptorKey(_ context: ContentRequestContext, _ resourceID: String) -> String { "\(context.namespaceKey)|\(resourceID)" }

    private func readerType(_ value: ErmaoShared.DownloadReaderType) throws -> ManagedDownloadReaderType {
        switch value { case .reflowable: .reflowable; case .pdf: .pdf; case .comic: .comic; case .audio: .audio; default: throw ManagedDownloadTransferError.invalidResponse }
    }

    private func map(_ error: ErmaoShared.AppError) -> ManagedDownloadTransferError {
        switch error.kind { case .unauthorized: .unauthorized; case .forbidden, .notfoundorunavailable, .gone: .inaccessible; case .storagefailure: .insufficientSpace; case .cancelled: .cancelled; case .protocolviolation: .invalidResponse; default: .transportUnavailable }
    }
}

private final class SharedDownloadDescriptorCache: @unchecked Sendable {
    private var descriptors: [String: ErmaoShared.DownloadDescriptor] = [:]
    private let lock = NSLock()
    func save(_ descriptor: ErmaoShared.DownloadDescriptor, key: String) { lock.lock(); defer { lock.unlock() }; descriptors[key] = descriptor }
    func value(for key: String) -> ErmaoShared.DownloadDescriptor? { lock.lock(); defer { lock.unlock() }; return descriptors[key] }
}

private final class SharedDownloadProgressSink: NSObject, DownloadProgressObserver {
    private let update: @Sendable (Int64, Int64) -> Void
    init(update: @escaping @Sendable (Int64, Int64) -> Void) { self.update = update }
    func onProgress(transferredBytes: Int64, totalBytes: Int64) { update(transferredBytes, totalBytes) }
}

private final class SharedPartialFileSink: NSObject, DownloadByteSink {
    private let record: ManagedDownloadRecord
    private let destination: ManagedDownloadDestination
    init(record: ManagedDownloadRecord, destination: ManagedDownloadDestination) { self.record = record; self.destination = destination }
    func begin(request: DownloadSinkRequest) async throws -> DownloadByteSinkSession {
        guard request.taskId == record.id, request.resourceId == record.resourceID, request.assetId == record.assetID,
              record.expectedBytes == Optional(request.expectedTotalBytes) else { throw ManagedDownloadTransferError.invalidResponse }
        return try SharedPartialFileSession(fileURL: destination.partialFileURL, resumeFromBytes: request.resumeFromBytes)
    }
}

private final class SharedPartialFileSession: NSObject, DownloadByteSinkSession, @unchecked Sendable {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "com.ermao.library.download-file-sink")
    private var handle: FileHandle?
    init(fileURL: URL, resumeFromBytes: Int64) throws {
        self.fileURL = fileURL
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            FileManager.default.createFile(atPath: fileURL.path, contents: nil, attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        }
        let size = (try FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber)?.int64Value ?? 0
        guard size == resumeFromBytes else { throw ManagedDownloadTransferError.invalidResponse }
        handle = try FileHandle(forWritingTo: fileURL)
        if resumeFromBytes == 0 { try handle?.truncate(atOffset: 0) }
        else { try handle?.seekToEnd() }
    }
    func write(bytes: KotlinByteArray) async throws {
        let data = Data((0..<Int(bytes.size)).map { UInt8(bitPattern: bytes.get(index: Int32($0))) })
        try queue.sync { guard let handle else { throw ManagedDownloadTransferError.invalidResponse }; try handle.write(contentsOf: data) }
    }
    func commit(expectedTotalBytes: Int64) async throws -> String {
        try queue.sync {
            guard let handle else { throw ManagedDownloadTransferError.invalidResponse }
            try handle.synchronize(); try handle.close(); self.handle = nil
            let size = try FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber
            guard size?.int64Value == expectedTotalBytes else { throw ManagedDownloadTransferError.invalidResponse }
            return "foreground-staged"
        }
    }
    func abort() async throws { try queue.sync { try handle?.close(); handle = nil; try? FileManager.default.removeItem(at: fileURL) } }
    func pause() async throws { try queue.sync { try handle?.synchronize(); try handle?.close(); handle = nil } }
}
