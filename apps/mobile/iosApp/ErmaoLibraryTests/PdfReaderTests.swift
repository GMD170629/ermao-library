import Foundation
import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

final class PdfReaderTests: XCTestCase {
    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    func testReadiumPositionMapsToCanonicalZeroBasedPage() {
        XCTAssertEqual(IosPdfPositionPolicy.pageIndex(position: 1, pageCount: 3), 0)
        XCTAssertEqual(IosPdfPositionPolicy.pageIndex(position: 3, pageCount: 3), 2)
        XCTAssertNil(IosPdfPositionPolicy.pageIndex(position: 0, pageCount: 3))
        XCTAssertNil(IosPdfPositionPolicy.pageIndex(position: 4, pageCount: 3))
    }

    func testOnlyCanonicalPageTopProgressionIsAccepted() {
        XCTAssertTrue(IosPdfPositionPolicy.accepts(pageProgression: 0))
        XCTAssertFalse(IosPdfPositionPolicy.accepts(pageProgression: 0.0001))
        XCTAssertFalse(IosPdfPositionPolicy.accepts(pageProgression: 1))
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
        try cache.writeAlignedRange(identity: identity, begin: 0, bytes: KotlinByteArray(size: 32))
        cache.activateUnit(pageIndex: 1)
        XCTAssertNil(cache.readCached(identity: identity, offset: 0, count: 1))
    }

    func testRangeCacheReadsOnlyCompleteCachedBytes() throws {
        let cache = ErmaoShared.PdfRangeMemory()
        let source = try remoteSource()
        let identity = ErmaoShared.PdfRangeCacheIdentity(namespace: source.namespace_, resourceId: source.resourceId)
        let chunk = KotlinByteArray(size: Int32(Int64(256 * 1024)))
        for index in 0 ..< chunk.size { chunk.set(index: index, value: 7) }

        try cache.writeAlignedRange(identity: identity, begin: 0, bytes: chunk)

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
        try cache.writeAlignedRange(identity: previous, begin: 0, bytes: KotlinByteArray(size: 32))

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
}
