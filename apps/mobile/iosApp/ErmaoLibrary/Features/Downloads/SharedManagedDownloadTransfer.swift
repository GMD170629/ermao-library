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
            sourceFormat: descriptor.format.uppercased(),
            mimeType: descriptor.source.mimeType.lowercased(),
            readerType: try readerType(descriptor.readerType),
            expectedBytes: descriptor.totalBytes,
            artifactKind: try artifactKind(descriptor.artifactKind)
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
              descriptor.format.caseInsensitiveCompare(request.record.format) == .orderedSame,
              descriptor.source.mimeType.caseInsensitiveCompare(request.record.mimeType ?? "") == .orderedSame,
              descriptor.totalBytes == expectedBytes,
              try artifactKind(descriptor.artifactKind) == request.record.effectiveArtifactKind else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        descriptors.save(descriptor, key: key)
        let sink = SharedPartialFileSink(record: request.record, destination: request.destination)
        let observer = SharedDownloadProgressSink { transferred, total in
            Task { await progress(ManagedDownloadProgress(receivedBytes: transferred, expectedBytes: total)) }
        }
        let partialBytes = request.record.effectiveArtifactKind == .singleOriginalAsset
            ? ((try? FileManager.default.attributesOfItem(atPath: request.destination.partialFileURL.path)[.size]) as? NSNumber)?.int64Value ?? 0
            : 0
        let resumeBytes = partialBytes > 0 && partialBytes < expectedBytes ? partialBytes : 0
        if request.record.effectiveArtifactKind == .originalPageSet || (resumeBytes == 0 && partialBytes > 0) {
            try? FileManager.default.removeItem(at: request.destination.partialFileURL)
        }
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
        return ManagedDownloadReceipt(receivedBytes: success.transfer.verifiedBytes, expectedBytes: descriptor.totalBytes)
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

    private func artifactKind(_ value: ErmaoShared.DownloadArtifactKind) throws -> ManagedDownloadArtifactKind {
        switch value {
        case .singleoriginalasset: .singleOriginalAsset
        case .originalpageset: .originalPageSet
        default: throw ManagedDownloadTransferError.invalidResponse
        }
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

private final class SharedPartialFileSink: NSObject, DownloadByteSink, DownloadBundleByteSink {
    private let record: ManagedDownloadRecord
    private let destination: ManagedDownloadDestination
    init(record: ManagedDownloadRecord, destination: ManagedDownloadDestination) { self.record = record; self.destination = destination }
    func begin(request: DownloadSinkRequest) async throws -> DownloadByteSinkSession {
        guard request.taskId == record.id, request.resourceId == record.resourceID, request.assetId == record.assetID,
              record.expectedBytes == Optional(request.expectedTotalBytes) else { throw ManagedDownloadTransferError.invalidResponse }
        return try SharedPartialFileSession(fileURL: destination.partialFileURL, resumeFromBytes: request.resumeFromBytes)
    }

    func beginBundle(request: DownloadBundleSinkRequest) async throws -> DownloadBundleByteSinkSession {
        guard record.effectiveArtifactKind == .originalPageSet,
              request.taskId == record.id,
              request.resourceId == record.resourceID,
              request.artifactId == record.assetID,
              request.memberCount > 0,
              record.expectedBytes == Optional(request.expectedTotalBytes) else {
            throw ManagedDownloadTransferError.invalidResponse
        }
        return try SharedPageSetSinkSession(
            request: request,
            stagingDirectory: destination.partialFileURL
        )
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

    init(request: DownloadBundleSinkRequest, stagingDirectory: URL) throws {
        self.request = request
        self.stagingDirectory = stagingDirectory
        try? FileManager.default.removeItem(at: stagingDirectory)
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
        return try SharedPageSetMemberSinkSession(
            partURL: partURL,
            finalURL: finalURL,
            expectedBytes: request.expectedBytes
        ) { [weak self] in
            guard let self else { throw ManagedDownloadTransferError.invalidResponse }
            self.lock.lock()
            defer { self.lock.unlock() }
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
            return "foreground-staged-bundle"
        }
    }

    func abort() async throws {
        let shouldDelete = lock.withLock {
            let value = !closed
            closed = true
            return value
        }
        if shouldDelete { try? FileManager.default.removeItem(at: stagingDirectory) }
    }
}

private final class SharedPageSetMemberSinkSession: NSObject, DownloadByteSinkSession, @unchecked Sendable {
    private let partURL: URL
    private let finalURL: URL
    private let expectedBytes: Int64
    private let onCommit: () throws -> Void
    private let lock = NSLock()
    private var handle: FileHandle?

    init(partURL: URL, finalURL: URL, expectedBytes: Int64, onCommit: @escaping () throws -> Void) throws {
        self.partURL = partURL
        self.finalURL = finalURL
        self.expectedBytes = expectedBytes
        self.onCommit = onCommit
        FileManager.default.createFile(
            atPath: partURL.path,
            contents: nil,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        handle = try FileHandle(forWritingTo: partURL)
    }

    func write(bytes: KotlinByteArray) async throws {
        let data = Data((0..<Int(bytes.size)).map { UInt8(bitPattern: bytes.get(index: Int32($0))) })
        try lock.withLock {
            guard let handle else { throw ManagedDownloadTransferError.invalidResponse }
            try handle.write(contentsOf: data)
        }
    }

    func commit(expectedTotalBytes: Int64) async throws -> String {
        try lock.withLock {
            guard let handle, expectedTotalBytes == expectedBytes else {
                throw ManagedDownloadTransferError.invalidResponse
            }
            try handle.synchronize()
            try handle.close()
            self.handle = nil
            guard fileSize(partURL) == expectedBytes else {
                try? FileManager.default.removeItem(at: partURL)
                throw ManagedDownloadTransferError.invalidResponse
            }
            if FileManager.default.fileExists(atPath: finalURL.path) {
                try FileManager.default.removeItem(at: finalURL)
            }
            try FileManager.default.moveItem(at: partURL, to: finalURL)
            try onCommit()
            return finalURL.lastPathComponent
        }
    }

    func abort() async throws {
        lock.withLock {
            try? handle?.close()
            handle = nil
            try? FileManager.default.removeItem(at: partURL)
            try? FileManager.default.removeItem(at: finalURL)
        }
    }

    func pause() async throws { try await abort() }
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
