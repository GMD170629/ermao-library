import Foundation
@preconcurrency import ErmaoShared

final class IosPublicationDownloadSinkFactory: ErmaoShared.PublicationDownloadSinkFactory, @unchecked Sendable {
    private let store: IosManagedPublicationStore

    init(store: IosManagedPublicationStore) {
        self.store = store
    }

    func open(download: ErmaoShared.ReaderPublicationDownload) async throws -> ErmaoShared.PublicationDownloadSink {
        let staging = try await store.prepareDownload(
            sourceID: download.sourceId,
            expectedSize: download.expectedSizeBytes
        )
        return IosPublicationDownloadSink(
            store: store,
            staging: staging,
            download: download
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
    private var output: FileHandle?
    private var byteCount: Int64 = 0
    private var completed = false

    init(
        store: IosManagedPublicationStore,
        staging: URL,
        download: ErmaoShared.ReaderPublicationDownload
    ) {
        self.store = store
        self.staging = staging
        self.download = download
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
                sourceID: download.sourceId,
                displayTitle: download.displayTitle,
                byteCount: byteCount,
                expectedSize: download.expectedSizeBytes,
                parserVersion: "reader-v4",
                normalizationVersion: "reader-v4",
                sourceFormat: download.sourceFormat,
                workID: download.workId,
                volumeID: download.volumeId,
                validateWithReaderParser: true
            )
            return ErmaoShared.LocalReaderSource(
                sourceId: managed.sourceID,
                displayTitle: managed.displayTitle,
                format: managed.sourceFormat.readerFormat,
                workId: managed.workID,
                volumeId: managed.volumeID,
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
