import Darwin
import Foundation
import UIKit
@preconcurrency import ErmaoShared

#if canImport(ShukuPdfium)
import ShukuPdfium
#endif

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
    private let native: OpaquePointer
    private let context: IosPdfiumByteSourceContext
    private let operationLock = NSLock()
    private var closed = false

    private init(native: OpaquePointer, context: IosPdfiumByteSourceContext, pageCount: Int) {
        self.native = native
        self.context = context
        self.pageCount = pageCount
    }
    #else
    private init(pageCount: Int) {
        self.pageCount = pageCount
    }
    #endif

    static func open(
        source: ErmaoShared.RemoteByteRangeReaderSource,
        cache: ErmaoShared.PdfRangeMemory,
        server: any ErmaoShared.PdfRangeServerPort
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
        let loader = ErmaoShared.PdfRangeLoader(source: source,
            identity: ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId), cache: cache, server: server)
        do { try await loader.probe() }
        catch { loader.close(); throw rangeFailure(error) }
        let context = IosPdfiumByteSourceContext(
            loader: loader,
            cache: cache,
            identity: ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId),
            length: UInt64(source.expectedSizeBytes)
        )
        return try await open(context: context)
        #else
        throw engineUnavailable()
        #endif
    }

    static func open(publication: IosManagedPublication) async throws -> IosPdfiumDocument {
        #if canImport(ShukuPdfium)
        guard IosPdfiumFeatureFlags.nativeLibraryMatchesLock else {
            throw engineUnavailable()
        }
        guard publication.byteCount >= 0 else {
            throw IosReaderFailure(code: .corruptFile)
        }
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
        return try await open(context: IosPdfiumByteSourceContext(reader: reader))
        #else
        throw engineUnavailable()
        #endif
    }

    #if canImport(ShukuPdfium)
    private static func open(context: IosPdfiumByteSourceContext) async throws -> IosPdfiumDocument {
        let retained = Unmanaged.passRetained(context)
        var byteSource = ShukuPdfiumByteSource(
            length: context.length,
            user_data: retained.toOpaque(),
            is_range_cached: iosPdfiumIsRangeCached,
            read_cached_block: iosPdfiumReadCachedBlock,
            request_range: iosPdfiumRequestRange
        )
        guard shuku_pdfium_initialize() == SHUKU_PDFIUM_OK else {
            context.close()
            retained.release()
            throw engineUnavailable()
        }
        var document: OpaquePointer?
        let createStatus = shuku_pdfium_document_create(&byteSource, &document)
        guard createStatus == SHUKU_PDFIUM_OK, let document else {
            context.close()
            retained.release()
            shuku_pdfium_shutdown()
            if context.length == 0, createStatus == SHUKU_PDFIUM_INVALID_ARGUMENT {
                throw IosReaderFailure(code: .pdfInvalid)
            }
            throw IosPdfiumDocument.failure(createStatus)
        }
        do {
            try await advanceUntilAvailable(context: context) {
                shuku_pdfium_document_step(document)
            }
            let count = Int(shuku_pdfium_page_count(document))
            guard count > 0 else { throw IosReaderFailure(code: .pdfInvalid) }
            guard Int64(count) <= ErmaoShared.PublicKt.readerSafetyPdfPageMaxCount() else {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
                )
            }
            return IosPdfiumDocument(native: document, context: context, pageCount: count)
        } catch {
            context.close()
            shuku_pdfium_document_close(document)
            retained.release()
            shuku_pdfium_shutdown()
            throw error
        }
    }
    #endif

    func pageSize(_ pageIndex: Int) async throws -> CGSize {
        #if canImport(ShukuPdfium)
        try await ensurePage(pageIndex)
        return try operationLock.withLock {
            try requireOpen()
            var size = ShukuPdfiumPageSize(width_points: 0, height_points: 0)
            let status = shuku_pdfium_page_size(native, Int32(pageIndex), &size)
            if status == SHUKU_PDFIUM_INVALID_DOCUMENT {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
                )
            }
            guard status == SHUKU_PDFIUM_OK else {
                throw Self.failure(status)
            }
            guard size.width_points.isFinite, size.height_points.isFinite,
                  size.width_points > 0, size.height_points > 0 else {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyPdfPageGeometryFailure()
                )
            }
            return CGSize(width: CGFloat(size.width_points), height: CGFloat(size.height_points))
        }
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
        var pixels = Data(count: stride * height)
        try operationLock.withLock {
            try requireOpen()
            let status = pixels.withUnsafeMutableBytes { buffer in
                shuku_pdfium_render_page_bgra(
                    native,
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
        operationLock.withLock {
            guard !closed else { return }
            closed = true
            context.close()
            shuku_pdfium_document_close(native)
            Unmanaged.passUnretained(context).release()
            shuku_pdfium_shutdown()
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
            try operationLock.withLock {
                try requireOpen()
                return shuku_pdfium_page_step(native, Int32(pageIndex))
            }
        }
        #else
        throw Self.engineUnavailable()
        #endif
    }

    #if canImport(ShukuPdfium)
    private static func advanceUntilAvailable(
        context: IosPdfiumByteSourceContext,
        step: () throws -> ShukuPdfiumStatus
    ) async throws {
        for _ in 0 ..< 256 {
            try Task.checkCancellation()
            let status = try step()
            if status == SHUKU_PDFIUM_OK { return }
            guard status == SHUKU_PDFIUM_NEED_DATA else {
                throw failure(status)
            }
            do {
                guard try await context.drainRequested() else {
                    throw IosReaderFailure(code: .engineError)
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
        if closed { throw IosReaderFailure(code: .engineError) }
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

    private enum Backing {
        case remote(
            loader: ErmaoShared.PdfRangeLoader,
            cache: ErmaoShared.PdfRangeMemory,
            identity: ErmaoShared.PdfRangeCacheIdentity
        )
        case local(IosPdfiumLocalFileReader)
    }

    private let backing: Backing

    init(
        loader: ErmaoShared.PdfRangeLoader,
        cache: ErmaoShared.PdfRangeMemory,
        identity: ErmaoShared.PdfRangeCacheIdentity,
        length: UInt64
    ) {
        self.length = length
        backing = .remote(loader: loader, cache: cache, identity: identity)
    }

    init(reader: IosPdfiumLocalFileReader) {
        length = reader.length
        backing = .local(reader)
    }

    func isRangeAvailable(offset: UInt64, size: UInt64) -> Bool {
        guard size > 0, offset <= length, size <= length - offset else { return false }
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
        switch backing {
        case let .remote(loader, _, _):
            guard offset <= UInt64(Int64.max), size <= UInt64(Int64.max) else { return }
            loader.request(offset: Int64(offset), size: Int64(size))
        case .local:
            break
        }
    }

    func drainRequested() async throws -> Bool {
        switch backing {
        case let .remote(loader, _, _):
            return try await loader.drainRequested().boolValue
        case .local:
            return false
        }
    }

    func activateUnit(pageIndex: Int32) {
        guard case let .remote(loader, _, _) = backing else { return }
        loader.activateUnit(pageIndex: pageIndex)
    }

    func close() {
        switch backing {
        case let .remote(loader, _, _):
            loader.close()
        case let .local(reader):
            reader.close()
        }
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
