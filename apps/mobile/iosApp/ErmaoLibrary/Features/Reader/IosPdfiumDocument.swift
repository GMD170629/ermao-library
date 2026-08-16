import Foundation
import UIKit
@preconcurrency import ErmaoShared

#if canImport(ShukuPdfium)
import ShukuPdfium
#endif

enum IosPdfiumFeatureFlags {
    static let expectedRevision = "875172eae557a308d0c5b2be43822814c8a885bb"
    static let expectedWrapperABI: Int32 = 1

    /// Enabled for physical-device acceptance; the locked native artifact and ABI check remain mandatory.
    private static let rolloutEnabled = true

    static var nativePdfiumRangeV1: Bool {
        rolloutEnabled && nativeLibraryMatchesLock
    }

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
        cache: IosPdfRangeCache,
        server: any ErmaoShared.PdfRangeServerPort
    ) async throws -> IosPdfiumDocument {
        #if canImport(ShukuPdfium)
        guard IosPdfiumFeatureFlags.nativeLibraryMatchesLock else {
            throw IosReaderFailure(code: .engineError)
        }
        let loader = IosPdfRangeLoader(source: source, cache: cache, server: server)
        try await loader.ensureAvailable()
        let context = IosPdfiumByteSourceContext(
            loader: loader,
            cache: cache,
            identity: IosPdfRangeCacheIdentity(source: source)
        )
        let retained = Unmanaged.passRetained(context)
        var byteSource = ShukuPdfiumByteSource(
            length: UInt64(source.expectedSizeBytes),
            user_data: retained.toOpaque(),
            is_range_cached: iosPdfiumIsRangeCached,
            read_cached_block: iosPdfiumReadCachedBlock,
            request_range: iosPdfiumRequestRange
        )
        guard shuku_pdfium_initialize() == SHUKU_PDFIUM_OK else {
            retained.release()
            throw IosReaderFailure(code: .engineError)
        }
        var document: OpaquePointer?
        let createStatus = shuku_pdfium_document_create(&byteSource, &document)
        guard createStatus == SHUKU_PDFIUM_OK, let document else {
            retained.release()
            shuku_pdfium_shutdown()
            throw IosReaderFailure(code: IosPdfiumDocument.failureCode(createStatus))
        }
        do {
            try await advanceUntilAvailable(context: context) {
                shuku_pdfium_document_step(document)
            }
            let count = Int(shuku_pdfium_page_count(document))
            guard count > 0 else { throw IosReaderFailure(code: .pdfInvalid) }
            return IosPdfiumDocument(native: document, context: context, pageCount: count)
        } catch {
            shuku_pdfium_document_close(document)
            retained.release()
            shuku_pdfium_shutdown()
            throw error
        }
        #else
        throw IosReaderFailure(code: .engineError)
        #endif
    }

    func pageSize(_ pageIndex: Int) async throws -> CGSize {
        #if canImport(ShukuPdfium)
        try await ensurePage(pageIndex)
        return try operationLock.withLock {
            try requireOpen()
            var size = ShukuPdfiumPageSize(width_points: 0, height_points: 0)
            let status = shuku_pdfium_page_size(native, Int32(pageIndex), &size)
            guard status == SHUKU_PDFIUM_OK else {
                throw IosReaderFailure(code: Self.failureCode(status))
            }
            guard size.width_points > 0, size.height_points > 0 else {
                throw IosReaderFailure(code: .pdfInvalid)
            }
            return CGSize(width: CGFloat(size.width_points), height: CGFloat(size.height_points))
        }
        #else
        throw IosReaderFailure(code: .engineError)
        #endif
    }

    func render(pageIndex: Int, viewport: CGSize, scale: CGFloat) async throws -> UIImage {
        #if canImport(ShukuPdfium)
        let points = try await pageSize(pageIndex)
        let fit = min(viewport.width / points.width, viewport.height / points.height)
        let renderScale = max(0.1, fit * max(1, scale))
        let width = max(1, Int((points.width * renderScale).rounded(.up)))
        let height = max(1, Int((points.height * renderScale).rounded(.up)))
        let pixelCount = Int64(width) * Int64(height)
        guard pixelCount <= 12_000_000, width <= Int(Int32.max) / 4 else {
            throw IosReaderFailure(code: .outOfMemoryRisk)
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
                    12_000_000,
                    buffer.baseAddress
                )
            }
            guard status == SHUKU_PDFIUM_OK else {
                throw IosReaderFailure(code: Self.failureCode(status))
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
        return UIImage(cgImage: image, scale: UIScreen.main.scale, orientation: .up)
        #else
        throw IosReaderFailure(code: .engineError)
        #endif
    }

    func prefetch(pageIndex: Int) async {
        guard pageIndex >= 0, pageIndex < pageCount else { return }
        try? await ensurePage(pageIndex)
    }

    func close() {
        #if canImport(ShukuPdfium)
        operationLock.withLock {
            guard !closed else { return }
            closed = true
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
            throw IosReaderFailure(code: .pdfRangeInvalid)
        }
        try await Self.advanceUntilAvailable(context: context) { [self] in
            operationLock.withLock { shuku_pdfium_page_step(native, Int32(pageIndex)) }
        }
        #else
        throw IosReaderFailure(code: .engineError)
        #endif
    }

    #if canImport(ShukuPdfium)
    private static func advanceUntilAvailable(
        context: IosPdfiumByteSourceContext,
        step: () -> ShukuPdfiumStatus
    ) async throws {
        for _ in 0 ..< 256 {
            let status = step()
            if status == SHUKU_PDFIUM_OK { return }
            guard status == SHUKU_PDFIUM_NEED_DATA else {
                throw IosReaderFailure(code: failureCode(status))
            }
            let hints = context.hints.takeAll()
            guard !hints.isEmpty else { throw IosReaderFailure(code: .pdfRangeInvalid) }
            try await context.loader.load(hints)
        }
        throw IosReaderFailure(code: .pdfRangeInvalid)
    }

    private static func failureCode(_ status: ShukuPdfiumStatus) -> IosReaderFailureCode {
        switch status {
        case SHUKU_PDFIUM_ENCRYPTED: .pdfEncrypted
        case SHUKU_PDFIUM_PAGE_LOAD_FAILED: .pdfPageLoadFailed
        case SHUKU_PDFIUM_RENDER_FAILED: .pdfRenderFailed
        case SHUKU_PDFIUM_OUT_OF_MEMORY_RISK: .outOfMemoryRisk
        case SHUKU_PDFIUM_INVALID_ARGUMENT: .pdfRangeInvalid
        default: .pdfInvalid
        }
    }

    private func requireOpen() throws {
        if closed { throw IosReaderFailure(code: .engineError) }
    }
    #endif
}

#if canImport(ShukuPdfium)
private final class IosPdfiumByteSourceContext: @unchecked Sendable {
    let loader: IosPdfRangeLoader
    let cache: IosPdfRangeCache
    let identity: IosPdfRangeCacheIdentity
    let hints = IosPdfRangeHintQueue()

    init(
        loader: IosPdfRangeLoader,
        cache: IosPdfRangeCache,
        identity: IosPdfRangeCacheIdentity
    ) {
        self.loader = loader
        self.cache = cache
        self.identity = identity
    }
}

private func iosPdfiumIsRangeCached(
    _ opaque: UnsafeMutableRawPointer?,
    _ offset: UInt64,
    _ size: UInt64
) -> Int32 {
    guard let opaque, offset <= UInt64(Int64.max), size <= UInt64(Int.max) else { return 0 }
    let context = Unmanaged<IosPdfiumByteSourceContext>.fromOpaque(opaque).takeUnretainedValue()
    return context.cache.readCached(
        identity: context.identity,
        offset: Int64(offset),
        length: Int(size)
    ) == nil ? 0 : 1
}

private func iosPdfiumReadCachedBlock(
    _ opaque: UnsafeMutableRawPointer?,
    _ offset: UInt64,
    _ destination: UnsafeMutableRawPointer?,
    _ size: UInt64
) -> Int32 {
    guard let opaque, let destination,
          offset <= UInt64(Int64.max), size <= UInt64(Int.max) else { return 0 }
    let context = Unmanaged<IosPdfiumByteSourceContext>.fromOpaque(opaque).takeUnretainedValue()
    guard let bytes = context.cache.readCached(
        identity: context.identity,
        offset: Int64(offset),
        length: Int(size)
    ) else { return 0 }
    bytes.copyBytes(to: destination.assumingMemoryBound(to: UInt8.self), count: bytes.count)
    return 1
}

private func iosPdfiumRequestRange(
    _ opaque: UnsafeMutableRawPointer?,
    _ offset: UInt64,
    _ size: UInt64
) {
    guard let opaque,
          offset <= UInt64(Int64.max), size <= UInt64(Int64.max) else { return }
    Unmanaged<IosPdfiumByteSourceContext>.fromOpaque(opaque).takeUnretainedValue().hints.append(
        offset: Int64(offset),
        length: Int64(size)
    )
}
#endif

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
