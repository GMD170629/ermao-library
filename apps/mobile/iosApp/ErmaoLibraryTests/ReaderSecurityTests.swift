import XCTest
@testable import ErmaoLibrary

final class ReaderSecurityTests: XCTestCase {
    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    func testSanitizerRemovesActiveContentRemoteAssetsAndEventHandlers() {
        let unsafe = #"<html><head><meta http-equiv="refresh" content="0;https://bad.example"><style>body{background:url('https://bad.example/a.png')}</style></head><body onload="steal()"><script>steal()</script><iframe src="chapter.xhtml"></iframe><img src="https://bad.example/cover.jpg"><a href="https://example.com/help">Help</a><a href="javascript:steal()">Bad</a><img src="images/local.jpg"></body></html>"#

        let sanitized = IosEpubContentSanitizer.sanitize(unsafe, resource: "OPS/chapter.xhtml")

        XCTAssertFalse(sanitized.lowercased().contains("<script"))
        XCTAssertFalse(sanitized.lowercased().contains("<iframe"))
        XCTAssertFalse(sanitized.lowercased().contains("http-equiv=\"refresh\""))
        XCTAssertFalse(sanitized.lowercased().contains("onload="))
        XCTAssertFalse(sanitized.contains("https://bad.example"))
        XCTAssertFalse(sanitized.lowercased().contains("javascript:"))
        XCTAssertTrue(sanitized.contains("href=\"https://example.com/help\""))
        XCTAssertTrue(sanitized.contains("src=\"images/local.jpg\""))
    }

    func testOversizedMarkupFailsClosed() {
        let oversized = String(repeating: "x", count: 8 * 1_024 * 1_024 + 1)
        XCTAssertEqual(
            IosEpubContentSanitizer.sanitize(oversized, resource: "chapter.xhtml"),
            "<html><body></body></html>"
        )
    }
}
