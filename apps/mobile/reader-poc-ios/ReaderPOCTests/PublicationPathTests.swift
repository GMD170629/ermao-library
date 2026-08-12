import XCTest
@testable import ReaderPOC

final class PublicationPathTests: XCTestCase {
    func testNormalizesSafePublicationPaths() {
        XCTAssertEqual(PublicationPath.normalizedResourcePath("/OPS/./text/../chapter.xhtml"), "OPS/chapter.xhtml")
        XCTAssertEqual(PublicationPath.normalizedReference("OPS/chapter.xhtml#section-1"), "OPS/chapter.xhtml#section-1")
        XCTAssertEqual(PublicationPath.resourcePath(from: "OPS/chapter.xhtml?mode=1#section"), "OPS/chapter.xhtml")
    }

    func testRejectsTraversalOutsidePublicationRoot() {
        XCTAssertNil(PublicationPath.normalizedResourcePath("../../private/secret"))
        XCTAssertNil(PublicationPath.normalizedResourcePath("../chapter.xhtml"))
        XCTAssertNil(PublicationPath.normalizedResourcePath("\0chapter.xhtml"))
    }

    func testAllowsFragmentOnlyReferences() {
        XCTAssertEqual(PublicationPath.normalizedReference("#note-1"), "#note-1")
    }
}
