import XCTest
@testable import ErmaoLibrary

final class ReaderSecurityTests: XCTestCase {
    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    func testLocatorProjectionMatchesV2GoldenSemantics() throws {
        let markup = #"""
        <?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml"><head><title>Projection</title></head>
        <body><h1 id="chapter-title">&#22825;&#22320;&#29572;&#40644;</h1><form>
        <p id="target">Cafe&#769;   &#23431;&#23449;&#27946;&#33618;</p>
        <p>duplicate text</p><p>duplicate text</p></form><iframe src="remote"></iframe></body></html>
        """#

        XCTAssertEqual(
            try IosPublicationSecurityPolicy.locatorBodyProjection(data: Data(markup.utf8)),
            [
                ["path": "/body[1]", "localName": "body"],
                ["path": "/body[1]/h1[1]", "localName": "h1", "id": "chapter-title", "text": "天地玄黄"],
                ["path": "/body[1]/form[1]", "localName": "form"],
                ["path": "/body[1]/form[1]/p[1]", "localName": "p", "id": "target", "text": "Café 宇宙洪荒"],
                ["path": "/body[1]/form[1]/p[2]", "localName": "p", "text": "duplicate text"],
                ["path": "/body[1]/form[1]/p[3]", "localName": "p", "text": "duplicate text"],
                ["path": "/body[1]/iframe[1]", "localName": "iframe"],
            ]
        )
    }

    func testSecurityPolicyDecoratesOnlyHeadAndPreservesAuthorBody() throws {
        let unsafe = #"<html><head><meta http-equiv="refresh" content="0;https://bad.example"/><style>body{background:url('https://bad.example/a.png')}</style></head><body onload="steal()"><script>steal()</script><iframe src="chapter.xhtml"></iframe><img src="https://bad.example/cover.jpg"/><a href="https://example.com/help">Help</a><a href="javascript:steal()">Bad</a><img src="images/local.jpg"/></body></html>"#
        let originalBody = try XCTUnwrap(unsafe.range(of: #"(?s)<body.*</body>"#, options: .regularExpression))

        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(unsafe)

        let decoratedBody = try XCTUnwrap(decorated.range(of: #"(?s)<body.*</body>"#, options: .regularExpression))
        XCTAssertEqual(String(unsafe[originalBody]), String(decorated[decoratedBody]))
        XCTAssertTrue(decorated.contains("<script>steal()</script>"))
        XCTAssertTrue(decorated.contains("<iframe"))
        XCTAssertTrue(decorated.contains("onload=\"steal()\""))
        XCTAssertTrue(decorated.contains("javascript:steal()"))
        XCTAssertFalse(decorated.lowercased().contains("http-equiv=\"refresh\""))
        XCTAssertTrue(decorated.contains("data-shuku-security-profile=\"ios-v2\""))
        XCTAssertTrue(decorated.contains("script-src 'none'"))
    }

    func testStandardEpubDoctypeAndNonbreakingSpaceRemainReadable() throws {
        let markup = #"""
        <?xml version="1.0"?>
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
          "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
        <html xmlns="http://www.w3.org/1999/xhtml"><head><title>EPUB</title></head>
        <body><h1 id="chapter">Chapter&nbsp;One</h1></body></html>
        """#

        let projection = try IosPublicationSecurityPolicy.locatorBodyProjection(
            data: Data(markup.utf8)
        )
        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(markup)

        XCTAssertEqual(projection.last?["text"], "Chapter One")
        XCTAssertTrue(decorated.contains("<!DOCTYPE html PUBLIC"))
        XCTAssertTrue(decorated.contains("Chapter&nbsp;One"))
    }

    func testInvalidOrOversizedMarkupFailsClosedWithoutBlankDocument() {
        let oversized = "<html><head></head><body>" +
            String(repeating: "x", count: 64 * 1_024 * 1_024 + 1) +
            "</body></html>"
        XCTAssertThrowsError(try IosPublicationSecurityAdapter().decorateMarkup(oversized))
        XCTAssertThrowsError(
            try IosPublicationSecurityAdapter().decorateMarkup(
                "<html><body><p>Missing head</p></body></html>"
            )
        )
        XCTAssertThrowsError(
            try IosPublicationSecurityAdapter().decorateMarkup(
                #"<!DOCTYPE html SYSTEM "https://attacker.invalid/book.dtd"><html><head></head><body><p>Body</p></body></html>"#
            )
        )
    }

    func testFakeHeadInsideCommentAndCdataCannotCaptureSecurityDecoration() throws {
        let markup = #"""
        <?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml">
        <!-- <head><script>fake()</script></head> -->
        <head><title>Real</title></head>
        <body><script><![CDATA["<head>fake</head>"]]></script><p>Body</p></body>
        </html>
        """#

        let decorated = try IosPublicationSecurityAdapter().decorateMarkup(markup)
        let profile = try XCTUnwrap(decorated.range(of: "data-shuku-security-profile=\"ios-v2\""))
        let comment = try XCTUnwrap(decorated.range(of: "<!-- <head>"))
        let title = try XCTUnwrap(decorated.range(of: "<title>Real</title>"))

        XCTAssertGreaterThan(profile.lowerBound, comment.lowerBound)
        XCTAssertLessThan(profile.lowerBound, title.lowerBound)
        XCTAssertTrue(decorated.contains(#"<![CDATA["<head>fake</head>"]]>"#))
    }
}
