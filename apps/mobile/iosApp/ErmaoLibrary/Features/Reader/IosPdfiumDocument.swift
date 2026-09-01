import Darwin
import Foundation
import OSLog
import UIKit
@preconcurrency import ErmaoShared

#if canImport(ShukuPdfium)
import ShukuPdfium
#endif

@MainActor
final class IosPdfiumDownloadMaterializer: @unchecked Sendable {
    private let downloads: DownloadCenterStore
    private let completedDownloads: any CompletedDownloadProviding
    private let managedStore: IosManagedPublicationStore
    private let context: ContentRequestContext

    init(
        downloads: DownloadCenterStore,
        completedDownloads: any CompletedDownloadProviding,
        managedStore: IosManagedPublicationStore,
        context: ContentRequestContext
    ) {
        self.downloads = downloads
        self.completedDownloads = completedDownloads
        self.managedStore = managedStore
        self.context = context
    }

    func materialize(
        descriptor: ErmaoShared.DownloadDescriptor
    ) async throws -> IosManagedPublication {
        guard downloads.isCurrent(context) else {
            throw IosReaderFailure(code: .unauthorized)
        }
        let record = try await downloads.awaitVerifiedReaderDownload(
            descriptor: descriptor,
            context: context
        )
        guard record.resourceID == descriptor.identity.resourceId,
              record.assetID == descriptor.identity.assetId,
              record.bookID == descriptor.identity.bookId,
              record.namespace == context.namespaceKey,
              record.isVerifiedOfflineCopy,
              let artifact = record.verifiedSharedArtifact,
              PublicKt.downloadDescriptorsMatch(expected: artifact.descriptor, candidate: descriptor),
              artifact.verifiedBytes == descriptor.totalBytes else {
            throw IosReaderFailure(code: .publicationChanged)
        }

        guard let completed = try await completedDownloads.completedFile(
            recordID: record.id,
            namespace: context.namespaceKey
        ), completed.resourceID == descriptor.identity.resourceId,
              completed.assetID == descriptor.identity.assetId,
              completed.bookID == descriptor.identity.bookId,
              completed.sourceFormat.caseInsensitiveCompare(descriptor.format) == .orderedSame,
              completed.byteCount == descriptor.totalBytes else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        guard let sourceFormat = IosManagedPublicationStore.sourceFormat(completed.sourceFormat),
              sourceFormat == .pdf else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let publication = IosManagedPublication(
            resourceID: completed.resourceID,
            displayTitle: completed.displayTitle,
            fileURL: completed.fileURL,
            byteCount: completed.byteCount,
            bookID: completed.bookID,
            assetID: completed.assetID,
            namespace: context.namespaceKey,
            sourceFormat: sourceFormat
        )
        await managedStore.bindCompleted(publication)
        return publication
    }

}

/// All calls into the repository PDFium wrapper run through one background
/// actor.  The C wrapper also serializes its calls, but keeping the actor here
/// guarantees that the MainActor never performs a synchronous PDFium step and
/// prevents multiple documents from interleaving lifecycle operations.
private actor IosPdfiumExecutor {
    static let shared = IosPdfiumExecutor()

    func run<T: Sendable>(_ operation: @Sendable () throws -> T) async throws -> T {
        try operation()
    }
}

enum IosPdfiumFeatureFlags {
    static let expectedRevision = "153.0.8009.0"
    static let expectedWrapperABI: Int32 = 1

    static var nativeLibraryMatchesLock: Bool {
        #if canImport(ShukuPdfium)
        guard let revision = shuku_pdfium_revision() else { return false }
        return String(cString: revision) == expectedRevision
            && shuku_pdfium_wrapper_abi_version() == expectedWrapperABI
        #else
        return false
        #endif
    }
}

final class IosPdfiumDocument: @unchecked Sendable {
    let pageCount: Int

#if canImport(ShukuPdfium)
    private struct NativeHandle: @unchecked Sendable {
        let pointer: OpaquePointer
    }

    private let native: NativeHandle
    private let context: IosPdfiumByteSourceContext
    private let stateLock = NSLock()
    private var closed = false

    private init(native: OpaquePointer, context: IosPdfiumByteSourceContext, pageCount: Int) {
        self.native = NativeHandle(pointer: native)
        self.context = context
        self.pageCount = pageCount
    }
    #else
    private init(pageCount: Int) {
        self.pageCount = pageCount
    }
    #endif

    @MainActor
    static func open(
        source: ErmaoShared.RemoteByteRangeReaderSource,
        cache: ErmaoShared.PdfRangeMemory,
        server: any ErmaoShared.PdfRangeServerPort,
        descriptor: ErmaoShared.DownloadDescriptor? = nil,
        materializer: IosPdfiumDownloadMaterializer? = nil
    ) async throws -> IosPdfiumDocument {
        #if canImport(ShukuPdfium)
        guard IosPdfiumFeatureFlags.nativeLibraryMatchesLock else {
            throw engineUnavailable()
        }
        guard source.expectedSizeBytes >= 0 else {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyPdfRangeProtocolFailure()
            )
        }
        if let descriptor {
            guard Self.descriptor(descriptor, matches: source) else {
                throw IosReaderFailure(code: .pdfResourceChanged)
            }
        }
        let loader = ErmaoShared.PdfRangeLoader(source: source,
            identity: ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId), cache: cache, server: server)
        do { try await loader.probe() }
        catch { loader.close(); throw rangeFailure(error) }
        let context = IosPdfiumByteSourceContext(
            loader: loader,
            cache: cache,
            identity: ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId),
            length: UInt64(source.expectedSizeBytes),
            descriptor: descriptor,
            materializer: materializer
        )
        return try await open(context: context)
        #else
        throw engineUnavailable()
        #endif
    }

    #if canImport(ShukuPdfium)
    private static func descriptor(
        _ descriptor: ErmaoShared.DownloadDescriptor,
        matches source: ErmaoShared.RemoteByteRangeReaderSource
    ) -> Bool {
        let downloadNamespace = descriptor.identity.namespace_
        let readerNamespace = source.namespace_
        return descriptor.identity.resourceId == source.resourceId
            && descriptor.identity.bookId == source.bookId
            && descriptor.identity.assetId == source.assetId
            && downloadNamespace.serverIdentity == readerNamespace.serverIdentity
            && downloadNamespace.userId == readerNamespace.userId
            && downloadNamespace.authorizationVersion == readerNamespace.authorizationVersion
            && descriptor.format.caseInsensitiveCompare("pdf") == .orderedSame
            && descriptor.readerType.name.caseInsensitiveCompare("pdf") == .orderedSame
            && descriptor.artifactKind == .singleoriginalasset
            && descriptor.source.apiPath == source.apiPath
            && descriptor.source.totalBytes == source.expectedSizeBytes
            && descriptor.totalBytes == source.expectedSizeBytes
    }
    #endif

    @MainActor
    static func open(publication: IosManagedPublication) async throws -> IosPdfiumDocument {
        #if canImport(ShukuPdfium)
        guard IosPdfiumFeatureFlags.nativeLibraryMatchesLock else {
            throw engineUnavailable()
        }
        guard publication.byteCount >= 0 else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let reader = try await IosPdfiumExecutor.shared.run { () throws -> IosPdfiumLocalFileReader in
            let reader: IosPdfiumLocalFileReader
            do {
                reader = try IosPdfiumLocalFileReader(fileURL: publication.fileURL)
            } catch let failure as IosReaderFailure {
                throw failure
            } catch {
                throw IosReaderFailure.fileRead(error)
            }
            guard reader.length == UInt64(publication.byteCount) else {
                reader.close()
                throw IosReaderFailure(code: .corruptFile)
            }
            return reader
        }
        return try await open(context: IosPdfiumByteSourceContext(reader: reader))
        #else
        throw engineUnavailable()
        #endif
    }

    #if canImport(ShukuPdfium)
    private static func open(context: IosPdfiumByteSourceContext) async throws -> IosPdfiumDocument {
        let retained = Unmanaged.passRetained(context)
        let creation = try await IosPdfiumExecutor.shared.run { () -> NativeCreation in
            var byteSource = ShukuPdfiumByteSource(
                length: context.length,
                user_data: retained.toOpaque(),
                is_range_cached: iosPdfiumIsRangeCached,
                read_cached_block: iosPdfiumReadCachedBlock,
                request_range: iosPdfiumRequestRange
            )
            let initializeStatus = shuku_pdfium_initialize()
            guard initializeStatus == SHUKU_PDFIUM_OK else {
                return NativeCreation(status: initializeStatus, document: nil, initialized: false)
            }
            var document: OpaquePointer?
            let createStatus = shuku_pdfium_document_create(&byteSource, &document)
            let handle = document.map { NativeHandle(pointer: $0) }
            return NativeCreation(status: createStatus, document: handle, initialized: true)
        }
        guard creation.initialized else {
            try? await IosPdfiumExecutor.shared.run { context.close() }
            retained.release()
            throw engineUnavailable()
        }
        guard creation.status == SHUKU_PDFIUM_OK, let document = creation.document else {
            try? await IosPdfiumExecutor.shared.run {
                context.close()
                if let document = creation.document {
                    shuku_pdfium_document_close(document.pointer)
                }
                shuku_pdfium_shutdown()
            }
            retained.release()
            if context.length == 0, creation.status == SHUKU_PDFIUM_INVALID_ARGUMENT {
                throw IosReaderFailure(code: .pdfInvalid)
            }
            throw IosPdfiumDocument.failure(creation.status)
        }
        do {
            try await advanceUntilAvailable(context: context) {
                try await IosPdfiumExecutor.shared.run {
                    shuku_pdfium_document_step(document.pointer)
                }
            }
            let count = try await IosPdfiumExecutor.shared.run {
                Int(shuku_pdfium_page_count(document.pointer))
            }
            guard count > 0 else { throw IosReaderFailure(code: .pdfInvalid) }
            guard Int64(count) <= ErmaoShared.PublicKt.readerSafetyPdfPageMaxCount() else {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
                )
            }
            return IosPdfiumDocument(native: document.pointer, context: context, pageCount: count)
        } catch {
            try? await IosPdfiumExecutor.shared.run {
                context.close()
                shuku_pdfium_document_close(document.pointer)
                shuku_pdfium_shutdown()
            }
            retained.release()
            throw error
        }
    }

    private struct NativeCreation: @unchecked Sendable {
        let status: ShukuPdfiumStatus
        let document: NativeHandle?
        let initialized: Bool
    }
    #endif

    func pageSize(_ pageIndex: Int) async throws -> CGSize {
        #if canImport(ShukuPdfium)
        try await ensurePage(pageIndex)
        let size = try await IosPdfiumExecutor.shared.run { () throws -> CGSize in
            try requireOpen()
            var nativeSize = ShukuPdfiumPageSize(width_points: 0, height_points: 0)
            let status = shuku_pdfium_page_size(native.pointer, Int32(pageIndex), &nativeSize)
            if status == SHUKU_PDFIUM_INVALID_DOCUMENT {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
                )
            }
            guard status == SHUKU_PDFIUM_OK else {
                throw Self.failure(status)
            }
            guard nativeSize.width_points.isFinite, nativeSize.height_points.isFinite,
                  nativeSize.width_points > 0, nativeSize.height_points > 0 else {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
                )
            }
            return CGSize(width: CGFloat(nativeSize.width_points), height: CGFloat(nativeSize.height_points))
        }
        return size
        #else
        throw Self.engineUnavailable()
        #endif
    }

    func render(pageIndex: Int, viewport: CGSize, scale: CGFloat) async throws -> UIImage {
        #if canImport(ShukuPdfium)
        let points = try await pageSize(pageIndex)
        guard viewport.width.isFinite, viewport.height.isFinite, scale.isFinite,
              viewport.width > 0, viewport.height > 0, scale > 0 else {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyPdfRenderBudgetFailure()
            )
        }
        let fit = min(viewport.width / points.width, viewport.height / points.height)
        let renderScale = max(0.1, fit * max(1, scale))
        let rawWidth = (points.width * renderScale).rounded(.up)
        let rawHeight = (points.height * renderScale).rounded(.up)
        let maximumCanvasDimension = ErmaoShared.PublicKt.readerSafetyPdfCanvasMaxDimension()
        guard rawWidth.isFinite, rawHeight.isFinite,
              rawWidth > 0, rawHeight > 0,
              rawWidth <= CGFloat(maximumCanvasDimension),
              rawHeight <= CGFloat(maximumCanvasDimension) else {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyPdfRenderBudgetFailure()
            )
        }
        let width = max(1, Int(rawWidth))
        let height = max(1, Int(rawHeight))
        let pixelCount = Int64(width) * Int64(height)
        let maximumRenderPixels = ErmaoShared.PublicKt.readerSafetyPdfRenderMaxPixels()
        guard pixelCount <= maximumRenderPixels else {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyPdfRenderBudgetFailure()
            )
        }
        let stride = width * 4
        let pixels = try await IosPdfiumExecutor.shared.run { () throws -> Data in
            var pixels = Data(count: stride * height)
            try requireOpen()
            let status = pixels.withUnsafeMutableBytes { buffer in
                shuku_pdfium_render_page_bgra(
                    native.pointer,
                    Int32(pageIndex),
                    Int32(width),
                    Int32(height),
                    Int32(stride),
                    UInt64(maximumRenderPixels),
                    buffer.baseAddress
                )
            }
            if status == SHUKU_PDFIUM_OUT_OF_MEMORY_RISK {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfRenderBudgetFailure()
                )
            }
            guard status == SHUKU_PDFIUM_OK else {
                throw Self.failure(status)
            }
            return pixels
        }
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let provider = CGDataProvider(data: pixels as CFData),
              let image = CGImage(
                  width: width,
                  height: height,
                  bitsPerComponent: 8,
                  bitsPerPixel: 32,
                  bytesPerRow: stride,
                  space: colorSpace,
                  bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedFirst.rawValue)
                      .union(.byteOrder32Little),
                  provider: provider,
                  decode: nil,
                  shouldInterpolate: true,
                  intent: .defaultIntent
              ) else {
            throw IosReaderFailure(code: .pdfRenderFailed)
        }
        return UIImage(cgImage: image, scale: 1, orientation: .up)
        #else
        throw Self.engineUnavailable()
        #endif
    }

    func close() {
        #if canImport(ShukuPdfium)
        let shouldClose = stateLock.withLock { () -> Bool in
            guard !closed else { return false }
            closed = true
            return true
        }
        guard shouldClose else { return }
        let native = native
        let context = context
        Task.detached(priority: .userInitiated) {
            try? await IosPdfiumExecutor.shared.run {
                context.close()
                shuku_pdfium_document_close(native.pointer)
                Unmanaged.passUnretained(context).release()
                shuku_pdfium_shutdown()
            }
        }
        #endif
    }

    deinit { close() }

    private func ensurePage(_ pageIndex: Int) async throws {
        #if canImport(ShukuPdfium)
        guard pageIndex >= 0, pageIndex < pageCount else {
            throw IosReaderFailure(code: .locationRestoreFailed)
        }
        context.activateUnit(pageIndex: Int32(pageIndex))
        try await Self.advanceUntilAvailable(context: context) { [self] in
            try await IosPdfiumExecutor.shared.run {
                try requireOpen()
                return shuku_pdfium_page_step(native.pointer, Int32(pageIndex))
            }
        }
        #else
        throw Self.engineUnavailable()
        #endif
    }

    #if canImport(ShukuPdfium)
    private static func advanceUntilAvailable(
        context: IosPdfiumByteSourceContext,
        step: @escaping @Sendable () async throws -> ShukuPdfiumStatus
    ) async throws {
        try await driveAvailability(
            step: step,
            drainRequested: { try await context.drainRequested() }
        )
    }

    /// Drives PDFium's bounded availability state machine. A NEED_DATA result
    /// without a new AddSegment hint is a legal transient state after the byte
    /// source changes to a complete local file, so it is retried rather than
    /// surfaced as a false Reader failure.
    static func driveAvailability(
        step: @escaping @Sendable () async throws -> ShukuPdfiumStatus,
        drainRequested: @escaping @Sendable () async throws -> Bool
    ) async throws {
        for _ in 0 ..< 256 {
            try Task.checkCancellation()
            let status = try await step()
            if status == SHUKU_PDFIUM_OK { return }
            guard status == SHUKU_PDFIUM_NEED_DATA else {
                throw failure(status)
            }
            do {
                let acquiredRequestedData = try await drainRequested()
                if !acquiredRequestedData {
                    // PDFium can require another availability pass even when
                    // the verified local source already covers every byte and
                    // AddSegment did not enqueue a new range. The bounded loop
                    // remains the progress guard; this state is not an engine
                    // failure by itself.
                    await Task.yield()
                }
            } catch { throw rangeFailure(error) }
        }
        throw IosReaderFailure(code: .pdfEngineLimit)
    }

    private static func rangeFailure(_ error: Error) -> Error {
        if error is CancellationError || error is IosReaderFailure { return error }
        let native = error as NSError
        let failure = native.kotlinException as? ErmaoShared.PdfRangeFailure
        if let safetyFailure = failure?.safetyFailure {
            return IosReaderFailure.safety(safetyFailure, underlyingError: native)
        }
        return IosReaderFailure(
            code: failure.map { IosReaderFailureCode(sharedCode: $0.code) } ?? .engineError,
            underlyingError: native
        )
    }

    private static func failure(_ status: ShukuPdfiumStatus) -> IosReaderFailure {
        switch status {
        case SHUKU_PDFIUM_ENCRYPTED:
            .safety(ErmaoShared.PublicKt.readerSafetyDrmFailure())
        case SHUKU_PDFIUM_PAGE_LOAD_FAILED:
            IosReaderFailure(code: .pdfPageLoadFailed)
        case SHUKU_PDFIUM_RENDER_FAILED:
            IosReaderFailure(code: .pdfRenderFailed)
        case SHUKU_PDFIUM_OUT_OF_MEMORY_RISK:
            IosReaderFailure(code: .outOfMemoryRisk)
        case SHUKU_PDFIUM_INVALID_ARGUMENT:
            .safety(ErmaoShared.PublicKt.readerSafetyPdfRangeProtocolFailure())
        default:
            IosReaderFailure(code: .pdfInvalid)
        }
    }

    private func requireOpen() throws {
        let isClosed = stateLock.withLock { closed }
        if isClosed { throw IosReaderFailure(code: .engineError) }
    }
    #endif

    private static func engineUnavailable() -> IosReaderFailure {
        let targetRule = ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
        let failure = ErmaoShared.PublicKt.readerSafetyEngineAlgorithmUnsupported(
            ruleId: targetRule.ruleId
        )
        let code = ErmaoShared.PublicKt.readerErrorCodeForFailure(
            failureCode: failure.errorCode,
            recoverable: false
        )
        return IosReaderFailure(
            code: IosReaderFailureCode(sharedCode: code),
            safeContext: ["ruleId": failure.ruleId, "errorCode": failure.errorCode]
        )
    }
}

#if canImport(ShukuPdfium)
private final class IosPdfiumByteSourceContext: @unchecked Sendable {
    let length: UInt64

    private static let logger = Logger(subsystem: "com.ermao.library", category: "Pdfium")

    private enum Backing {
        case remote(
            loader: ErmaoShared.PdfRangeLoader,
            cache: ErmaoShared.PdfRangeMemory,
            identity: ErmaoShared.PdfRangeCacheIdentity
        )
        case local(IosPdfiumLocalFileReader)
    }

    private let stateLock = NSLock()
    private var backing: Backing
    private var closed = false
    private var materializationError: IosReaderFailure?
    private var materializationTask: Task<IosManagedPublication, Error>?
    private let expectedResourceID: String?
    private let expectedBookID: String?
    private let expectedAssetID: String?
    private let descriptor: ErmaoShared.DownloadDescriptor?
    private let materializer: IosPdfiumDownloadMaterializer?

    private enum DrainResult {
        case noPendingRequest
        case rangesAvailable
        case switchedToLocal
    }

    init(
        loader: ErmaoShared.PdfRangeLoader,
        cache: ErmaoShared.PdfRangeMemory,
        identity: ErmaoShared.PdfRangeCacheIdentity,
        length: UInt64,
        descriptor: ErmaoShared.DownloadDescriptor?,
        materializer: IosPdfiumDownloadMaterializer?
    ) {
        self.length = length
        backing = .remote(loader: loader, cache: cache, identity: identity)
        expectedResourceID = descriptor?.identity.resourceId
        expectedBookID = descriptor?.identity.bookId
        expectedAssetID = descriptor?.identity.assetId
        self.descriptor = descriptor
        self.materializer = materializer
    }

    init(reader: IosPdfiumLocalFileReader) {
        length = reader.length
        backing = .local(reader)
        expectedResourceID = nil
        expectedBookID = nil
        expectedAssetID = nil
        descriptor = nil
        materializer = nil
    }

    func isRangeAvailable(offset: UInt64, size: UInt64) -> Bool {
        guard size > 0, offset <= length, size <= length - offset else { return false }
        stateLock.lock()
        defer { stateLock.unlock() }
        guard !closed else { return false }
        switch backing {
        case let .remote(_, cache, identity):
            guard offset <= UInt64(Int64.max), size <= UInt64(Int32.max) else { return false }
            return cache.isCached(
                identity: identity,
                offset: Int64(offset),
                count: Int32(size)
            )
        case let .local(reader):
            return reader.isRangeAvailable(offset: offset, size: size)
        }
    }

    func copyAvailableRange(
        offset: UInt64,
        size: UInt64,
        destination: UnsafeMutableRawPointer
    ) -> Bool {
        guard isRangeAvailable(offset: offset, size: size) else { return false }
        stateLock.lock()
        defer { stateLock.unlock() }
        guard !closed else { return false }
        switch backing {
        case let .remote(_, cache, identity):
            guard let bytes = cache.readCached(
                identity: identity,
                offset: Int64(offset),
                count: Int32(size)
            ) else { return false }
            let data = bytes.foundationData()
            guard data.count == Int(size) else { return false }
            data.copyBytes(
                to: destination.assumingMemoryBound(to: UInt8.self),
                count: data.count
            )
            return true
        case let .local(reader):
            return reader.copy(offset: offset, size: size, destination: destination)
        }
    }

    func request(offset: UInt64, size: UInt64) {
        guard size > 0, offset <= length, size <= length - offset else { return }
        stateLock.lock()
        defer { stateLock.unlock() }
        guard !closed else { return }
        switch backing {
        case let .remote(loader, _, _):
            guard offset <= UInt64(Int64.max), size <= UInt64(Int64.max) else { return }
            loader.request(offset: Int64(offset), size: Int64(size))
        case .local:
            break
        }
    }

    func drainRequested() async throws -> Bool {
        switch try await drain() {
        case .noPendingRequest: return false
        case .rangesAvailable, .switchedToLocal: return true
        }
    }

    private func drain() async throws -> DrainResult {
        let loader: ErmaoShared.PdfRangeLoader? = stateLock.withLock {
            guard !closed else { return nil }
            guard case let .remote(loader, _, _) = backing else { return nil }
            return loader
        }
        guard let loader else { return .noPendingRequest }
        let result = try await loader.drainRequested()
        switch result {
        case is ErmaoShared.PdfRangeDrainResultNoPendingRequest:
            return .noPendingRequest
        case is ErmaoShared.PdfRangeDrainResultRangesAvailable:
            return .rangesAvailable
        case is ErmaoShared.PdfRangeDrainResultCompleteOriginalRequired:
            guard descriptor != nil, materializer != nil else {
                throw IosReaderFailure(code: .engineError)
            }
            return try await materialize()
        default:
            throw IosReaderFailure(code: .engineError)
        }
    }

    private func materialize() async throws -> DrainResult {
        let task = try stateLock.withLock { () throws -> Task<IosManagedPublication, Error> in
            if let materializationTask { return materializationTask }
            if let materializationError { throw materializationError }
            guard !closed, case .remote = backing,
                  let descriptor, let materializer else {
                throw IosReaderFailure(code: .engineError)
            }
            let task = Task { [self] in
                do {
                    logMaterialization(stage: "materialization_start", result: "requested")
                    let publication = try await materializer.materialize(descriptor: descriptor)
                    // Opening the verified file and changing the backing are
                    // serialized with every native call. This keeps a
                    // callback from observing a half-installed source and
                    // keeps all file I/O off MainActor.
                    try await IosPdfiumExecutor.shared.run {
                        try installLocal(publication, descriptor: descriptor)
                    }
                    logMaterialization(stage: "source_installed", result: "verified_local")
                    return publication
                } catch is CancellationError {
                    logMaterialization(stage: "materialization_cancelled", result: "cancelled")
                    throw CancellationError()
                } catch let failure as IosReaderFailure {
                    stateLock.withLock { materializationError = failure }
                    logMaterialization(stage: "materialization_failed", result: failure.code.rawValue)
                    throw failure
                } catch {
                    let failure = IosReaderFailure(code: .engineError, underlyingError: error as NSError)
                    stateLock.withLock { materializationError = failure }
                    logMaterialization(stage: "materialization_failed", result: failure.code.rawValue)
                    throw failure
                }
            }
            materializationTask = task
            return task
        }
        _ = try await task.value
        return try stateLock.withLock {
            guard !closed else { throw CancellationError() }
            guard case .local = backing else {
                if let materializationError { throw materializationError }
                throw IosReaderFailure(code: .engineError)
            }
            return .switchedToLocal
        }
    }

    private func installLocal(
        _ publication: IosManagedPublication,
        descriptor: ErmaoShared.DownloadDescriptor
    ) throws {
        guard publication.resourceID == expectedResourceID,
              publication.resourceID == descriptor.identity.resourceId,
              publication.bookID == expectedBookID,
              publication.bookID == descriptor.identity.bookId,
              publication.assetID == expectedAssetID,
              publication.assetID == descriptor.identity.assetId,
              publication.sourceFormat == .pdf,
              publication.byteCount == Int64(length),
              descriptor.totalBytes == Int64(length) else {
            throw IosReaderFailure(code: .pdfResourceChanged)
        }
        let reader = try IosPdfiumLocalFileReader(fileURL: publication.fileURL)
        guard reader.length == length else {
            reader.close()
            throw IosReaderFailure(code: .pdfResourceChanged)
        }

        stateLock.lock()
        defer { stateLock.unlock() }
        guard !closed else {
            reader.close()
            throw CancellationError()
        }
        guard case let .remote(loader, cache, _) = backing else {
            reader.close()
            if case .local = backing { return }
            throw IosReaderFailure(code: .engineError)
        }
        backing = .local(reader)
        // The cache is private Reader state. It must not become a partial
        // Downloads file and is invalid once the verified original is active.
        loader.close()
        cache.clear()
    }

    func activateUnit(pageIndex: Int32) {
        stateLock.lock()
        defer { stateLock.unlock() }
        guard !closed, case let .remote(loader, _, _) = backing else { return }
        loader.activateUnit(pageIndex: pageIndex)
    }

    func close() {
        let previous = stateLock.withLock { () -> Backing? in
            guard !closed else { return nil }
            closed = true
            materializationTask?.cancel()
            return backing
        }
        guard let previous else { return }
        switch previous {
        case let .remote(loader, _, _):
            loader.close()
        case let .local(reader):
            reader.close()
        }
    }

    private func logMaterialization(stage: String, result: String) {
        let resourceID = expectedResourceID ?? "unknown"
        Self.logger.notice(
            "pdf_materialization platform=ios resource_id=\(resourceID, privacy: .public) stage=\(stage, privacy: .public) result=\(result, privacy: .public) bytes=\(self.length, privacy: .public)"
        )
    }
}

private func iosPdfiumIsRangeCached(
    _ opaque: UnsafeMutableRawPointer?,
    _ offset: UInt64,
    _ size: UInt64
) -> Int32 {
    guard let opaque else { return 0 }
    let context = Unmanaged<IosPdfiumByteSourceContext>.fromOpaque(opaque).takeUnretainedValue()
    return context.isRangeAvailable(offset: offset, size: size) ? 1 : 0
}

private func iosPdfiumReadCachedBlock(
    _ opaque: UnsafeMutableRawPointer?,
    _ offset: UInt64,
    _ destination: UnsafeMutableRawPointer?,
    _ size: UInt64
) -> Int32 {
    guard let opaque, let destination, size <= UInt64(Int.max) else { return 0 }
    let context = Unmanaged<IosPdfiumByteSourceContext>.fromOpaque(opaque).takeUnretainedValue()
    return context.copyAvailableRange(
        offset: offset,
        size: size,
        destination: destination
    ) ? 1 : 0
}

private func iosPdfiumRequestRange(
    _ opaque: UnsafeMutableRawPointer?,
    _ offset: UInt64,
    _ size: UInt64
) {
    guard let opaque else { return }
    Unmanaged<IosPdfiumByteSourceContext>.fromOpaque(opaque).takeUnretainedValue().request(
        offset: offset,
        size: size
    )
}
#endif

final class IosPdfiumLocalFileReader: @unchecked Sendable {
    let length: UInt64

    private let handle: FileHandle
    private let lock = NSLock()
    private var closed = false

    init(fileURL: URL) throws {
        let values = try fileURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard fileURL.isFileURL,
              values.isRegularFile == true,
              values.isSymbolicLink != true else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        let handle = try FileHandle(forReadingFrom: fileURL)
        do {
            length = try handle.seekToEnd()
            try handle.seek(toOffset: 0)
            self.handle = handle
        } catch {
            try? handle.close()
            throw error
        }
    }

    func isRangeAvailable(offset: UInt64, size: UInt64) -> Bool {
        size > 0 && offset <= length && size <= length - offset
    }

    func copy(
        offset: UInt64,
        size: UInt64,
        destination: UnsafeMutableRawPointer
    ) -> Bool {
        guard offset <= UInt64(Int64.max),
              size <= UInt64(Int.max),
              isRangeAvailable(offset: offset, size: size) else {
            return false
        }
        return lock.withLock {
            guard !closed else { return false }
            var copied = 0
            while copied < Int(size) {
                let currentOffset = offset + UInt64(copied)
                let result = Darwin.pread(
                    handle.fileDescriptor,
                    destination.advanced(by: copied),
                    Int(size) - copied,
                    off_t(currentOffset)
                )
                if result > 0 {
                    copied += result
                    continue
                }
                if result < 0, errno == EINTR { continue }
                return false
            }
            return true
        }
    }

    func close() {
        lock.withLock {
            guard !closed else { return }
            closed = true
            try? handle.close()
        }
    }

    deinit { close() }
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
