import UIKit
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared
import XCTest
@testable import ErmaoLibrary

final class ReaderSecurityTests: XCTestCase {
    func testLegacyMobiEnvelopeBindsNamespacesWithoutChangingLocatorBody() async throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "01-basic-mobi6", withExtension: "mobi"))
        let book = try IosMobiBook.open(fileURL: url)
        let index = try await book.readingOrderResourceIndex(at: 0)
        let source = try await book.readResource(at: index, offset: 0, length: 4096)
        await book.close()
        let decorated = try IosPublicationSecurityAdapter().decorate(data: source, mediaType: "application/xhtml+xml")
        let originalMarkup = String(decoding: source, as: UTF8.self)
        let markup = String(decoding: decorated, as: UTF8.self)
        XCTAssertTrue(markup.contains("xmlns=\"http://www.w3.org/1999/xhtml\""))
        XCTAssertTrue(markup.contains("xmlns:mbp=\"urn:shuku:mobipocket\""))
        XCTAssertEqual(markup.components(separatedBy: "<body>").last, originalMarkup.components(separatedBy: "<body>").last)
        XCTAssertFalse(try IosPublicationSecurityPolicy.locatorBodyProjection(data: decorated).isEmpty)
    }

    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    @MainActor
    func testNativeTextControlsRenderBundledFontsAndThemesOnPhysicalDevice() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("reader-controls-\(UUID().uuidString).txt")
        defer { try? FileManager.default.removeItem(at: file) }
        let content = (1 ... 200).map { "Paragraph \($0). Native text controls preserve the publication. 中文字体与排版。" }.joined(separator: "\n\n")
        try Data(content.utf8).write(to: file)
        let managed = IosManagedPublication(resourceID: "controls", displayTitle: "Controls", fileURL: file, byteCount: Int64(content.utf8.count), bookID: "book", assetID: "asset", namespace: "test", sourceFormat: .txt)
        let opened = try await IosReadiumRuntime().open(managed)
        var preferences = IosReaderPreferences()
        preferences.fontSize = 24
        preferences.fontFamily = .songti
        preferences.theme = .night
        preferences.lineHeight = 2.2
        var navigator = try makeIosReflowableNavigator(publication: opened.publication, preferences: preferences.readium(for: .light), location: nil)
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let originalWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = navigator
        window.makeKeyAndVisible()
        defer { window.isHidden = true; originalWindow?.makeKey() }
        for _ in 0 ..< 50 where UIApplication.shared.applicationState != .active {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(UIApplication.shared.applicationState, .active, "Physical rendering acceptance requires the app in the foreground")
        let script = #"""
        (() => {
            const paragraph = document.querySelector('p');
            if (!paragraph) return false;
            const style = getComputedStyle(paragraph);
            return style.fontFamily.includes('Shuku Songti') &&
                [...document.fonts].some(font => font.family.includes('Shuku Songti') && font.status === 'loaded') &&
                Math.abs(parseFloat(style.fontSize) - 24) < 0.7 &&
                Math.abs(parseFloat(style.lineHeight) / parseFloat(style.fontSize) - 2.2) < 0.05 &&
                style.color === 'rgb(226, 232, 240)';
        })()
        """#
        var rendered = false
        for _ in 0 ..< 100 {
            if case let .success(value) = await navigator.evaluateJavaScript(script), value as? Bool == true { rendered = true; break }
            try await Task.sleep(for: .milliseconds(100))
        }
        if !rendered {
            if case let .success(value) = await navigator.evaluateJavaScript("JSON.stringify({root:document.documentElement.getAttribute('style'),rootName:document.documentElement.tagName,links:[...document.styleSheets].map(s=>s.href),font:getComputedStyle(document.querySelector('p')).fontFamily,size:getComputedStyle(document.querySelector('p')).fontSize,line:getComputedStyle(document.querySelector('p')).lineHeight,color:getComputedStyle(document.querySelector('p')).color,fonts:[...document.fonts].map(f=>({family:f.family,status:f.status}))})") {
                XCTFail("Native rendering mismatch: \(value)")
            } else { XCTFail("Native rendering did not become ready") }
        }
        func expectRendered(_ condition: String, _ message: String) async throws {
            for _ in 0 ..< 60 {
                if case let .success(value) = await navigator.evaluateJavaScript(condition), value as? Bool == true { return }
                try await Task.sleep(for: .milliseconds(100))
            }
            let diagnostic = await navigator.evaluateJavaScript("JSON.stringify({height:document.documentElement.scrollHeight,viewport:innerHeight,width:document.documentElement.scrollWidth,rootColumn:getComputedStyle(document.documentElement).columnWidth,bodyColumn:getComputedStyle(document.body).columnWidth,root:document.documentElement.getAttribute('style'),body:document.body.getAttribute('style')})")
            XCTFail("\(message): \(diagnostic)")
        }
        func applyNativePreferences() async throws {
            let anchor = await navigator.firstVisibleElementLocator()
            let next = try makeIosReflowableNavigator(publication: opened.publication, preferences: preferences.readium(for: .light), location: anchor)
            window.rootViewController = next
            navigator = next
        }
        for (family, nativeFamily) in [(IosReaderFontFamily.pingfang, "Shuku Sans"), (.kaiti, "Shuku Kaiti"), (.songti, "Shuku Songti")] {
            preferences.fontFamily = family
            try await applyNativePreferences()
            try await expectRendered("getComputedStyle(document.querySelector('p')).fontFamily.includes('\(nativeFamily)') && [...document.fonts].some(f=>f.family.includes('\(nativeFamily)') && f.status==='loaded')", "Bundled font must actually load: \(nativeFamily)")
        }
        for (theme, rgb) in [(IosReaderTheme.day, "rgb(30, 41, 59)"), (.warm, "rgb(43, 33, 24)"), (.green, "rgb(32, 49, 38)"), (.black, "rgb(248, 250, 252)"), (.night, "rgb(226, 232, 240)")] {
            preferences.theme = theme
            try await applyNativePreferences()
            try await expectRendered("getComputedStyle(document.querySelector('p')).color === '\(rgb)'", "Theme must update the paragraph immediately: \(theme)")
        }
        preferences.readingMode = .continuousScroll
        preferences.spreadMode = .double
        try await applyNativePreferences()
        XCTAssertEqual(UIApplication.shared.applicationState, .active, "Readium defers pagination reload while the app is inactive")
        XCTAssertTrue(navigator.settings.scroll)
        try await expectRendered("document.documentElement.scrollHeight > innerHeight && getComputedStyle(document.documentElement).columnWidth === 'auto'", "Continuous scrolling must change actual document layout")
        XCTAssertFalse(navigator.editor(of: preferences.readium(for: .light)).columnCount.isEffective)
        preferences.readingMode = .paged
        try await applyNativePreferences()
        XCTAssertEqual(navigator.settings.columnCount, ColumnCount.two)
        try await expectRendered("document.documentElement.scrollWidth > innerWidth && getComputedStyle(document.documentElement).columnWidth !== 'auto'", "Paged layout must restore horizontal columns")
        await opened.close()
    }

    func testTxtDecoderAllowsTrailingNulPaddingButRejectsEmbeddedNul() throws {
        let padded = Data("有效正文".data(using: .utf8)!) + Data(repeating: 0, count: 160)

        XCTAssertEqual(IosStrictTxtDecoder.decode(padded), "有效正文")
        XCTAssertNil(IosStrictTxtDecoder.decode(Data([0x41, 0x00, 0x42])))
    }

    @MainActor
    func testBlankTxtReturnsCorruptFileInsteadOfEscapingTheKotlinBoundary() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).txt")
        defer { try? FileManager.default.removeItem(at: file) }
        try Data(" \n\t".utf8).write(to: file)
        let managed = IosManagedPublication(
            resourceID: "invalid-txt", displayTitle: "Blank", fileURL: file, byteCount: 3,
            bookID: "book", assetID: "asset", namespace: "test", sourceFormat: .txt
        )
        do {
            _ = try await IosReadiumRuntime().open(managed)
            XCTFail("A blank TXT publication must fail")
        } catch let failure as IosReaderFailure {
            XCTAssertEqual(failure.code, .corruptFile)
        }
    }

    func testFb2RichContentMatchesServerBodiesAndPreservesOriginal() throws {
        let bundle = Bundle(for: Self.self)
        let source = try XCTUnwrap(bundle.url(forResource: "reader-contract", withExtension: "fb2"))
        let golden = try XCTUnwrap(bundle.url(forResource: "reader-contract-bodies", withExtension: "json"))
        let original = try Data(contentsOf: source)
        let expected = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: golden))
        let parsed = try IosFb2PublicationFactory.read(fileURL: source, fallbackTitle: "Fallback")

        XCTAssertEqual(parsed.document.title, "阅读 & Reading")
        XCTAssertEqual(parsed.document.language, "zh-CN")
        XCTAssertEqual(parsed.document.resources.count, expected.count)
        for resource in parsed.document.resources {
            let start = try XCTUnwrap(resource.xhtml.range(of: "<body>"))
            let end = try XCTUnwrap(resource.xhtml.range(of: "</body>"))
            XCTAssertEqual(String(resource.xhtml[start.upperBound..<end.lowerBound]), expected[resource.href])
        }
        XCTAssertEqual(parsed.document.tableOfContents.first?.children.first?.href,
                       "fb2/section-0001.xhtml#fb2-node-000002")
        XCTAssertEqual(Set(parsed.images.keys), ["fb2/images/498cc84b29cb560e15b4.png"])
        XCTAssertEqual(try Data(contentsOf: source), original)

        let upstream = try XCTUnwrap(bundle.url(forResource: "source_test_book_fb2", withExtension: "fb2"))
        XCTAssertEqual(try IosFb2PublicationFactory.read(fileURL: upstream, fallbackTitle: "Fallback").document.title,
                       "Sample FB2 book")
    }

    func testFb2InvalidXmlEntitiesAndImagesFailClosed() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("original.fb2")
        let examples = [
            "<FictionBook><body><p>broken</body></FictionBook>",
            "<!DOCTYPE FictionBook [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><FictionBook><body><p>&x;</p></body></FictionBook>",
            "<FictionBook><body><section id='x'/><section id='x'/></body></FictionBook>",
            "<FictionBook><body><p q:href='#x'>unbound</p></body></FictionBook>",
            "<FictionBook><body><p>text</p></body><binary id='image' content-type='image/png'>SGVsbG8=</binary></FictionBook>",
        ]
        for (index, example) in examples.enumerated() {
            let bytes = Data(example.utf8)
            try bytes.write(to: file)
            XCTAssertThrowsError(try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback"), "Invalid FB2 case \(index)")
            XCTAssertEqual(try Data(contentsOf: file), bytes)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), ["original.fb2"])
    }

    func testFb2Utf16AndUnsectionedBody() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).fb2")
        defer { try? FileManager.default.removeItem(at: file) }
        let xml = "<?xml version='1.0' encoding='UTF-16'?><FictionBook><body><p>中文正文</p></body></FictionBook>"
        try XCTUnwrap(xml.data(using: .utf16)).write(to: file)
        let parsed = try IosFb2PublicationFactory.read(fileURL: file, fallbackTitle: "Fallback")
        XCTAssertTrue(try XCTUnwrap(parsed.document.resources.first).xhtml.contains("<p>中文正文</p>"))
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
        let secured = try IosPublicationSecurityPolicy.decorate(data: Data("<html><head></head><body><p>Text</p></body></html>".utf8))
        let policy = String(decoding: secured, as: UTF8.self)
        XCTAssertTrue(policy.contains("style-src 'self' readium://assets"))
        XCTAssertTrue(policy.contains("font-src 'self' readium://assets"))
        XCTAssertTrue(policy.contains("script-src 'none'"))
        XCTAssertTrue(policy.contains("connect-src 'none'"))
        XCTAssertFalse(policy.contains("readium:;"))

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
