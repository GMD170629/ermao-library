import Foundation
@preconcurrency import ErmaoShared

final class IosPublicationDownloadSinkFactory: ErmaoShared.PublicationDownloadSinkFactory, @unchecked Sendable {
    private let store: IosManagedPublicationStore
    private let namespace: String

    init(store: IosManagedPublicationStore, namespace: String) {
        self.store = store
        self.namespace = namespace
    }

    func open(download: ErmaoShared.ReaderPublicationDownload) async throws -> ErmaoShared.PublicationDownloadSink {
        let staging = try await store.prepareDownload(
            resourceID: download.resourceId,
            expectedSize: download.expectedSizeBytes,
            namespace: namespace
        )
        return IosPublicationDownloadSink(
            store: store,
            staging: staging,
            download: download,
            namespace: namespace
        )
    }
}

final class IosPublicationDownloadSink: ErmaoShared.PublicationDownloadSink, @unchecked Sendable {
    private let worker: IosPublicationDownloadWorker

    init(
        store: IosManagedPublicationStore,
        staging: URL,
        download: ErmaoShared.ReaderPublicationDownload
    ) {
        worker = IosPublicationDownloadWorker(store: store, staging: staging, download: download)
    }

    func write(bytes: KotlinByteArray, count: Int32) async throws {
        try await worker.write(bytes: bytes, count: count)
    }

    func commit() async throws -> ErmaoShared.ReaderSource {
        try await worker.commit()
    }

    func abort() async throws {
        try await worker.abort()
    }
}

private actor IosPublicationDownloadWorker {
    private let store: IosManagedPublicationStore
    private let staging: URL
    private let download: ErmaoShared.ReaderPublicationDownload
    private let namespace: String
    private var output: FileHandle?
    private var byteCount: Int64 = 0
    private var completed = false

    init(
        store: IosManagedPublicationStore,
        staging: URL,
        download: ErmaoShared.ReaderPublicationDownload,
        namespace: String
    ) {
        self.store = store
        self.staging = staging
        self.download = download
        self.namespace = namespace
    }

    func write(bytes: KotlinByteArray, count: Int32) throws {
        guard !completed,
              count >= 0,
              count <= bytes.size
        else { throw IosReaderFailure(code: .corruptFile) }
        let nextCount = byteCount + Int64(count)
        guard nextCount <= IosManagedPublicationStore.maximumPublicationBytes
        else { throw IosReaderFailure(code: .outOfMemoryRisk) }
        let chunk = Data((0..<Int(count)).map { UInt8(bitPattern: bytes.get(index: Int32($0))) })
        if output == nil { output = try FileHandle(forWritingTo: staging) }
        try output?.write(contentsOf: chunk)
        byteCount = nextCount
    }

    func commit() async throws -> ErmaoShared.ReaderSource {
        guard !completed else { throw IosReaderFailure(code: .persistenceFailed) }
        completed = true
        do {
            try output?.synchronize()
            try output?.close()
            output = nil
            let managed = try await store.commitDownload(
                staging: staging,
                resourceID: download.resourceId,
                displayTitle: download.displayTitle,
                byteCount: byteCount,
                expectedSize: download.expectedSizeBytes,
                parserVersion: "reader-v4",
                normalizationVersion: "reader-v4",
                sourceFormat: download.sourceFormat,
                bookID: download.bookId,
                namespace: namespace,
                validateWithReaderParser: true
            )
            return ErmaoShared.LocalReaderSource(
                resourceId: managed.resourceID,
                displayTitle: managed.displayTitle,
                format: managed.sourceFormat.readerFormat,
                bookId: managed.bookID,
                sourceFormat: managed.sourceFormat
            )
        } catch {
            try? await store.abortDownload(staging: staging)
            throw error
        }
    }

    func abort() async throws {
        guard !completed else { return }
        completed = true
        try? output?.close()
        output = nil
        try await store.abortDownload(staging: staging)
    }
}
