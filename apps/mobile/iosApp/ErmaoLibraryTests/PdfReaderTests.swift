import Foundation
import XCTest
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

    func testPageCountBindingIsFingerprintScoped() throws {
        let suite = "PdfReaderTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = IosPdfPageCountStore(defaults: defaults)
        let first = try fingerprint("0")
        let replacement = try fingerprint("f")

        store.save(pageCount: 7, sourceID: "volume-pdf", fingerprint: first)

        XCTAssertEqual(store.load(sourceID: "volume-pdf", fingerprint: first), 7)
        XCTAssertNil(store.load(sourceID: "volume-pdf", fingerprint: replacement))
    }

    private func fingerprint(_ character: Character) throws -> IosContentFingerprint {
        try IosContentFingerprint(
            originalFileHash: "sha256:" + String(repeating: String(character), count: 64),
            parserVersion: "readium-swift:3.8.0",
            normalizationVersion: "pdf-native-v1"
        )
    }
}
