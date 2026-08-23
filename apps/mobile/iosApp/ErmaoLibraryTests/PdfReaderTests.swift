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

    func testRangePolicyAlignsMergesAndCapsRequests() throws {
        let chunk = IosPdfRangePolicy.chunkBytes
        let ranges = try IosPdfRangePolicy.alignedRanges(
            offset: 17,
            length: 6 * chunk - 17,
            resourceLength: 8 * chunk,
            isChunkCached: { $0 == 2 }
        )

        XCTAssertEqual(ranges, [0 ..< 2 * chunk, 3 * chunk ..< 6 * chunk])
        XCTAssertTrue(ranges.allSatisfy { Int64($0.count) <= IosPdfRangePolicy.maximumRequestBytes })
    }

    func testRangeCacheReadsOnlyCompleteCachedBytes() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("PdfReaderTests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let cache = try IosPdfRangeCache(root: root)
        let source = try remoteSource()
        let identity = IosPdfRangeCacheIdentity(source: source)
        let chunk = Data(repeating: 7, count: Int(IosPdfRangePolicy.chunkBytes))

        try cache.writeAlignedRange(identity: identity, offset: 0, bytes: chunk)

        XCTAssertEqual(cache.readCached(identity: identity, offset: 11, length: 16), Data(repeating: 7, count: 16))
        XCTAssertNil(cache.readCached(
            identity: identity,
            offset: IosPdfRangePolicy.chunkBytes,
            length: 1
        ))
    }

    func testRangeCacheRemovesPreviousAuthorizationNamespace() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("PdfReaderAuthzTests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let cache = try IosPdfRangeCache(root: root)
        let previous = IosPdfRangeCacheIdentity(source: try remoteSource(authorizationVersion: 1))
        let current = IosPdfRangeCacheIdentity(source: try remoteSource(authorizationVersion: 2))
        try cache.writeAlignedRange(identity: previous, offset: 0, bytes: Data(repeating: 1, count: 32))

        try cache.activateNamespace(current)

        XCTAssertNil(cache.readCached(identity: previous, offset: 0, length: 1))
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
            expectedSizeBytes: 2 * IosPdfRangePolicy.chunkBytes
        )
    }
}
