import Foundation
import XCTest
import UIKit
@preconcurrency import ErmaoShared
#if canImport(ShukuPdfium)
@preconcurrency import ShukuPdfium
#endif
@testable import ErmaoLibrary

final class PdfReaderTests: XCTestCase {
    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    func testOnlyCanonicalPageTopProgressionIsAccepted() {
        XCTAssertTrue(IosPdfPositionPolicy.accepts(pageProgression: 0))
        XCTAssertFalse(IosPdfPositionPolicy.accepts(pageProgression: 0.0001))
        XCTAssertFalse(IosPdfPositionPolicy.accepts(pageProgression: 1))
    }

    func testLocalPdfiumByteSourceReadsExactRandomRangesWithoutChangingOriginal() throws {
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).pdf")
        let original = Data((0 ..< 251).map { UInt8($0) })
        try original.write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }

        let reader = try IosPdfiumLocalFileReader(fileURL: file)
        defer { reader.close() }

        XCTAssertEqual(reader.length, UInt64(original.count))
        XCTAssertEqual(read(reader, offset: 17, size: 31), original.subdata(in: 17 ..< 48))
        XCTAssertEqual(read(reader, offset: 233, size: 18), original.subdata(in: 233 ..< 251))
        XCTAssertNil(read(reader, offset: 250, size: 2))
        XCTAssertNil(read(reader, offset: 0, size: 0))
        XCTAssertEqual(try Data(contentsOf: file), original)
    }

    func testClosedLocalPdfiumByteSourceCannotRead() throws {
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).pdf")
        try Data([1, 2, 3, 4]).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        let reader = try IosPdfiumLocalFileReader(fileURL: file)

        reader.close()

        XCTAssertNil(read(reader, offset: 0, size: 1))
    }

    @MainActor
    func testLocalPdfOpensThroughRepositoryPdfiumDocument() async throws {
        #if canImport(ShukuPdfium)
        XCTAssertTrue(IosPdfiumFeatureFlags.nativeLibraryMatchesLock)
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).pdf")
        let original = minimalPdf()
        try original.write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        let managed = IosManagedPublication(
            resourceID: "resource-pdfium-local",
            displayTitle: "Local PDFium",
            fileURL: file,
            byteCount: Int64(original.count),
            bookID: "book-pdfium-local",
            assetID: "asset-pdfium-local",
            namespace: "namespace-pdfium-local",
            sourceFormat: .pdf
        )

        let document = try await IosPdfiumDocument.open(publication: managed)
        defer { document.close() }

        XCTAssertEqual(document.pageCount, 1)
        let size = try await document.pageSize(0)
        XCTAssertEqual(size.width, 200, accuracy: 0.01)
        XCTAssertEqual(size.height, 300, accuracy: 0.01)
        XCTAssertEqual(try Data(contentsOf: file), original)
        #else
        XCTFail("The locked repository-owned ShukuPdfium artifact is required on physical iOS.")
        #endif
    }

    @MainActor
    func testPdfNavigatorAppliesReaderThemeBackgroundBeforeAndAfterLoading() async throws {
        #if canImport(ShukuPdfium)
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString).pdf")
        let original = minimalPdf()
        try original.write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        let managed = IosManagedPublication(
            resourceID: "resource-pdfium-theme",
            displayTitle: "PDF theme",
            fileURL: file,
            byteCount: Int64(original.count),
            bookID: "book-pdfium-theme",
            assetID: "asset-pdfium-theme",
            namespace: "namespace-pdfium-theme",
            sourceFormat: .pdf
        )
        let document = try await IosPdfiumDocument.open(publication: managed)
        let navigator = IosPdfiumNavigatorViewController(document: document, initialPageIndex: 0)
        defer { navigator.close() }
        let warmBackground = UIColor(red: 0.992, green: 0.965, blue: 0.918, alpha: 1)
        navigator.setReaderBackgroundColor(warmBackground)

        navigator.loadViewIfNeeded()

        XCTAssertEqual(navigator.view.backgroundColor, warmBackground)
        let scrollView = try XCTUnwrap(navigator.view.subviews.compactMap { $0 as? UIScrollView }.first)
        XCTAssertEqual(scrollView.backgroundColor, warmBackground)

        let greenBackground = UIColor(red: 0.91, green: 0.94, blue: 0.89, alpha: 1)
        navigator.setReaderBackgroundColor(greenBackground)
        XCTAssertEqual(navigator.view.backgroundColor, greenBackground)
        XCTAssertEqual(scrollView.backgroundColor, greenBackground)
        #else
        XCTFail("The locked repository-owned ShukuPdfium artifact is required on physical iOS.")
        #endif
    }

    func testPdfiumNeedDataWithoutANewRangeHintRetriesInsteadOfReportingEngineFailure() async throws {
        #if canImport(ShukuPdfium)
        let probe = PdfAvailabilityProbe()

        try await IosPdfiumDocument.driveAvailability(
            step: { await probe.nextStatus() },
            drainRequested: { await probe.drainWithoutRequest() }
        )

        let counts = await probe.counts()
        XCTAssertEqual(counts.steps, 2)
        XCTAssertEqual(counts.drains, 1)
        #else
        XCTFail("The locked repository-owned ShukuPdfium artifact is required on physical iOS.")
        #endif
    }

    @MainActor
    func testReadiumRuntimeHasNoPdfFallback() async throws {
        let managed = IosManagedPublication(
            resourceID: "resource-no-readium-pdf",
            displayTitle: "No Readium PDF",
            fileURL: URL(fileURLWithPath: "/not-opened-by-readium.pdf"),
            byteCount: 1,
            bookID: nil,
            assetID: nil,
            namespace: nil,
            sourceFormat: .pdf
        )

        do {
            _ = try await IosReadiumRuntime().open(managed)
            XCTFail("PDF must never enter the Readium/PDFKit runtime.")
        } catch let failure as IosReaderFailure {
            XCTAssertEqual(failure.code, .unsupportedFormat)
        }
    }

    func testPageCountBindingIsSourceScoped() throws {
        let suite = "PdfReaderTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = IosPdfPageCountStore(defaults: defaults)
        store.save(pageCount: 7, resourceID: "resource-pdf")

        XCTAssertEqual(store.load(resourceID: "resource-pdf"), 7)
        XCTAssertNil(store.load(resourceID: "another-resource"))
    }

    func testChangingReadingUnitReleasesPreviousBodyBytes() throws {
        let cache = ErmaoShared.PdfRangeMemory()
        let source = try remoteSource()
        let identity = ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId)
        cache.activateUnit(pageIndex: 0)
        try cache.writeAlignedRange(identity: identity, begin: 0, bytes: KotlinByteArray(size: 32), expectedEpoch: nil)
        cache.activateUnit(pageIndex: 1)
        XCTAssertNil(cache.readCached(identity: identity, offset: 0, count: 1))
    }

    func testRangeCacheReadsOnlyCompleteCachedBytes() throws {
        let cache = ErmaoShared.PdfRangeMemory()
        let source = try remoteSource()
        let identity = ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId)
        let chunk = KotlinByteArray(size: Int32(Int64(256 * 1024)))
        for index in 0 ..< chunk.size { chunk.set(index: index, value: 7) }

        try cache.writeAlignedRange(identity: identity, begin: 0, bytes: chunk, expectedEpoch: nil)

        XCTAssertEqual(cache.readCached(identity: identity, offset: 11, count: 16)?.foundationData(), Data(repeating: 7, count: 16))
        XCTAssertNil(cache.readCached(
            identity: identity,
            offset: Int64(256 * 1024),
            count: 1
        ))
    }

    func testRangeCacheRemovesPreviousAuthorizationNamespace() throws {
        let cache = ErmaoShared.PdfRangeMemory()
        let previous = ErmaoShared.PdfRangeCacheIdentity(namespace: try remoteSource(authorizationVersion: 1).namespace_, resourceId: "resource-pdf")
        let current = ErmaoShared.PdfRangeCacheIdentity(namespace: try remoteSource(authorizationVersion: 2).namespace_, resourceId: "resource-pdf")
        try cache.writeAlignedRange(identity: previous, begin: 0, bytes: KotlinByteArray(size: 32), expectedEpoch: nil)

        cache.activateNamespace(namespace: current.namespace_)

        XCTAssertNil(cache.readCached(identity: previous, offset: 0, count: 1))
    }

    private func remoteSource(authorizationVersion: Int64 = 2) throws -> ErmaoShared.RemoteByteRangeReaderSource {
        let namespace = ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: "server",
            userId: "user",
            authorizationVersion: authorizationVersion
        )
        return ErmaoShared.RemoteByteRangeReaderSource(
            resourceId: "resource-pdf",
            displayTitle: "PDF",
            bookId: "work-pdf",
            assetId: "asset-pdf",
            namespace: namespace,
            apiPath: "/api/assets/asset-pdf",
            expectedSizeBytes: 2 * Int64(256 * 1024)
        )
    }

    private func minimalPdf() -> Data {
        var body = "%PDF-1.4\n"
        var offsets: [Int] = [0]
        let objects = [
            "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
            "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
            "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Resources <<>> /Contents 4 0 R >>\nendobj\n",
            "4 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n",
        ]
        for object in objects {
            offsets.append(body.utf8.count)
            body += object
        }
        let xrefOffset = body.utf8.count
        body += "xref\n0 5\n0000000000 65535 f \n"
        for offset in offsets.dropFirst() {
            body += String(format: "%010d 00000 n \n", offset)
        }
        body += "trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n\(xrefOffset)\n%%EOF\n"
        return Data(body.utf8)
    }

    private func read(
        _ reader: IosPdfiumLocalFileReader,
        offset: UInt64,
        size: UInt64
    ) -> Data? {
        guard size > 0, size <= UInt64(Int.max) else { return nil }
        var data = Data(count: Int(size))
        let copied = data.withUnsafeMutableBytes { buffer in
            guard let destination = buffer.baseAddress else { return false }
            return reader.copy(offset: offset, size: size, destination: destination)
        }
        return copied ? data : nil
    }
}

#if canImport(ShukuPdfium)
private actor PdfAvailabilityProbe {
    private var stepCount = 0
    private var drainCount = 0

    func nextStatus() -> ShukuPdfiumStatus {
        stepCount += 1
        return stepCount == 1 ? SHUKU_PDFIUM_NEED_DATA : SHUKU_PDFIUM_OK
    }

    func drainWithoutRequest() -> Bool {
        drainCount += 1
        return false
    }

    func counts() -> (steps: Int, drains: Int) {
        (stepCount, drainCount)
    }
}
#endif
