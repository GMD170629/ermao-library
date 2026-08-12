import Foundation
import XCTest
@testable import ReaderPOC

final class PackageParserTests: XCTestCase {
    func testOPFSpineIsAuthoritativeAndPreservesRTL() throws {
        let xml = Data("""
        <package xmlns="http://www.idpf.org/2007/opf">
          <manifest>
            <item id="second" href="text/b.xhtml" />
            <item id="first" href="text/a.xhtml" />
          </manifest>
          <spine page-progression-direction="rtl">
            <itemref idref="first" />
            <itemref idref="second" />
          </spine>
        </package>
        """.utf8)

        let package = try OPFPackageParser().parse(xml)

        XCTAssertEqual(package.readingOrderHREFs, ["text/a.xhtml", "text/b.xhtml"])
        XCTAssertEqual(package.progression, .rightToLeft)
    }

    func testNCXPreservesHierarchyFragmentsAndDuplicateTitles() throws {
        let xml = Data("""
        <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
          <navMap>
            <navPoint id="root-a"><navLabel><text>重复标题</text></navLabel><content src="a.xhtml#top" />
              <navPoint id="child-a"><navLabel><text>细目</text></navLabel><content src="a.xhtml#child" /></navPoint>
            </navPoint>
            <navPoint id="root-b"><navLabel><text>重复标题</text></navLabel><content src="b.xhtml#top" /></navPoint>
          </navMap>
        </ncx>
        """.utf8)

        let navigation = try NCXNavigationParser().parse(xml)

        XCTAssertEqual(navigation.map(\.title), ["重复标题", "重复标题"])
        XCTAssertEqual(navigation[0].href, "a.xhtml#top")
        XCTAssertEqual(navigation[0].children.first?.href, "a.xhtml#child")
        XCTAssertEqual(navigation.flattened.count, 3)
    }

    func testMalformedDocumentsFailExplicitly() {
        XCTAssertThrowsError(try OPFPackageParser().parse(Data("<package>".utf8)))
        XCTAssertThrowsError(try NCXNavigationParser().parse(Data("<ncx>".utf8)))
    }
}
