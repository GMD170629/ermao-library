import Foundation
@preconcurrency import ErmaoShared

/// Foreground-only authenticated transfer. iOS background execution is deliberately not claimed here.
final class SharedManagedDownloadTransfer: ManagedDownloadTransferring, @unchecked Sendable {
    private let cookieStore: KeychainCookiePayloadStore
    private let descriptors = SharedDownloadDescriptorCache()

    init(cookieStore: KeychainCookiePayloadStore) {
        self.cookieStore = cookieStore
    }

    func prepare(
        context: ContentRequestContext,
        volumeID: String
    ) async throws -> ManagedDownloadBootstrap {
        let descriptor = try await loadDescriptor(context: context, volumeID: volumeID)
        descriptors.save(descriptor, key: descriptorKey(context, volumeID))
        return ManagedDownloadBootstrap(
            mediaVersionID: descriptor.mediaVersionId,
            mediaKind: try mediaKind(descriptor.mediaKind),
            readerType: try readerType(descriptor.readerType),
            contentFingerprint: descriptor.identity.contentFingerprint,
            expectedBytes: descriptor.source.totalBytes
        )
    }

    func download(
        _ request: ManagedDownloadRequest,
        progress: @escaping @Sendable (ManagedDownloadProgress) async -> Void
    ) async throws -> ManagedDownloadReceipt {
        let key = descriptorKey(request.context, request.record.volumeID)
        let descriptor = if let cached = descriptors.value(for: key) {
            cached
        } else {
            try await loadDescriptor(context: request.context, volumeID: request.record.volumeID)
        }
        guard descriptor.identity.workId == request.record.workID,
              descriptor.identity.volumeId == request.record.volumeID,
              descriptor.identity.contentFingerprint == request.record.contentFingerprint,
              descriptor.source.totalBytes == request.record.expectedBytes else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        descriptors.save(descriptor, key: key)
        let sink = SharedPartialFileSink(
            record: request.record,
            destination: request.destination
        )
        let observer = SharedDownloadProgressSink { transferred, total in
            Task { await progress(ManagedDownloadProgress(receivedBytes: transferred, expectedBytes: total)) }
        }
        let result = try await makeGateway(request.context).transfer(
            context: sharedContext(request.context),
            request: DownloadTransferRequest(
                taskId: request.record.id,
                descriptor: descriptor,
                resumeFromBytes: 0
            ),
            sink: sink,
            progressObserver: observer
        )
        guard let success = result as? DownloadTransferResultSuccess else {
            if let failure = result as? DownloadTransferResultFailure {
                throw map(failure.error)
            }
            throw ManagedDownloadTransferError.invalidResponse
        }
        return ManagedDownloadReceipt(
            receivedBytes: success.transfer.verifiedBytes,
            expectedBytes: descriptor.source.totalBytes,
            contentFingerprint: descriptor.identity.contentFingerprint
        )
    }

    private func makeGateway(_ context: ContentRequestContext) -> KtorDownloadsGateway {
        IosCompositionKt.createIosDownloadsGateway(
            cookieStore: cookieStore,
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS
        )
    }

    private func loadDescriptor(
        context: ContentRequestContext,
        volumeID: String
    ) async throws -> DownloadDescriptor {
        let result = try await makeGateway(context).load(
            context: sharedContext(context),
            volumeId: volumeID
        )
        if let success = result as? DownloadBootstrapResultSuccess,
           success.bootstrap.descriptor.identity.volumeId == volumeID {
            return success.bootstrap.descriptor
        }
        if let failure = result as? DownloadBootstrapResultFailure {
            throw map(failure.error)
        }
        throw ManagedDownloadTransferError.invalidResponse
    }

    private func sharedContext(_ context: ContentRequestContext) -> DownloadRequestContext {
        PublicKt.createDownloadRequestContext(
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS,
            userId: context.userID,
            authorizationVersion: context.authorizationVersion
        )
    }

    private func descriptorKey(_ context: ContentRequestContext, _ volumeID: String) -> String {
        "\(context.namespaceKey)|\(volumeID)"
    }

    private func readerType(_ value: DownloadReaderType) throws -> ManagedDownloadReaderType {
        switch value {
        case .reflowable: .reflowable
        case .pdf: .pdf
        case .comic: .comic
        case .audio: .audio
        default: throw ManagedDownloadTransferError.invalidResponse
        }
    }

    private func mediaKind(_ value: String) throws -> LibraryMediaKind {
        guard let kind = LibraryMediaKind(rawValue: value.uppercased()) else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        return kind
    }

    private func map(_ error: AppError) -> ManagedDownloadTransferError {
        switch error.kind {
        case .unauthorized: .unauthorized
        case .forbidden, .notfoundorunavailable, .gone: .inaccessible
        case .storagefailure: .insufficientSpace
        case .cancelled: .cancelled
        case .protocolviolation: .invalidResponse
        default: .transportUnavailable
        }
    }
}

private final class SharedDownloadDescriptorCache: @unchecked Sendable {
    private var descriptors: [String: DownloadDescriptor] = [:]
    private let lock = NSLock()

    func save(_ descriptor: DownloadDescriptor, key: String) {
        lock.lock()
        defer { lock.unlock() }
        descriptors[key] = descriptor
    }

    func value(for key: String) -> DownloadDescriptor? {
        lock.lock()
        defer { lock.unlock() }
        return descriptors[key]
    }
}

private final class SharedDownloadProgressSink: NSObject, DownloadProgressObserver {
    private let update: @Sendable (Int64, Int64) -> Void

    init(update: @escaping @Sendable (Int64, Int64) -> Void) {
        self.update = update
    }

    func onProgress(transferredBytes: Int64, totalBytes: Int64) {
        update(transferredBytes, totalBytes)
    }
}

private final class SharedPartialFileSink: NSObject, DownloadByteSink {
    private let record: ManagedDownloadRecord
    private let destination: ManagedDownloadDestination

    init(record: ManagedDownloadRecord, destination: ManagedDownloadDestination) {
        self.record = record
        self.destination = destination
    }

    func begin(request: DownloadSinkRequest) async throws -> DownloadByteSinkSession {
        guard request.taskId == record.id,
              request.volumeId == record.volumeID,
              request.contentFingerprint == record.contentFingerprint,
              request.expectedTotalBytes == record.expectedBytes,
              request.resumeFromBytes == 0 else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        return try SharedPartialFileSession(fileURL: destination.partialFileURL)
    }
}

private final class SharedPartialFileSession: NSObject, DownloadByteSinkSession, @unchecked Sendable {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "com.ermao.library.download-file-sink")
    private var handle: FileHandle?

    init(fileURL: URL) throws {
        self.fileURL = fileURL
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        FileManager.default.createFile(
            atPath: fileURL.path,
            contents: nil,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        handle = try FileHandle(forWritingTo: fileURL)
        try handle?.truncate(atOffset: 0)
    }

    func write(bytes: KotlinByteArray) async throws {
        let data = Data((0..<Int(bytes.size)).map {
            UInt8(bitPattern: bytes.get(index: Int32($0)))
        })
        try queue.sync {
            guard let handle else { throw ManagedDownloadTransferError.invalidResponse }
            try handle.write(contentsOf: data)
        }
    }

    func commit(expectedTotalBytes: Int64) async throws -> String {
        try queue.sync {
            guard let handle else { throw ManagedDownloadTransferError.invalidResponse }
            try handle.synchronize()
            try handle.close()
            self.handle = nil
            let attributes = try FileManager.default.attributesOfItem(atPath: fileURL.path)
            guard (attributes[.size] as? NSNumber)?.int64Value == expectedTotalBytes else {
                throw ManagedDownloadTransferError.invalidResponse
            }
            return "foreground-staged"
        }
    }

    func abort() async throws {
        try queue.sync {
            try handle?.close()
            handle = nil
            if FileManager.default.fileExists(atPath: fileURL.path) {
                try FileManager.default.removeItem(at: fileURL)
            }
        }
    }
}
