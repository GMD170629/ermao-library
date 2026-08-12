#!/usr/bin/env swift

import AppKit
import Foundation

struct Chapter {
    let filename: String
    let title: String
    let body: String
}

indirect enum NavigationNode {
    case item(title: String, href: String, children: [NavigationNode] = [])
}

struct FixtureSource {
    let id: String
    let outputFilename: String
    let title: String
    let language: String
    let progression: String
    let css: String
    let chapters: [Chapter]
    let navigation: [NavigationNode]
    let includeFont: Bool
    let includeImages: Bool
}

enum GeneratorError: Error, CustomStringConvertible {
    case invalidArguments
    case missingFont(URL)
    case imageEncodingFailed

    var description: String {
        switch self {
        case .invalidArguments:
            "usage: GenerateFixtureSources.swift <output-directory> <font-file>"
        case let .missingFont(url):
            "OFL test font is missing: \(url.path)"
        case .imageEncodingFailed:
            "unable to create deterministic test raster"
        }
    }
}

private func main() throws {
    let arguments = CommandLine.arguments
    guard arguments.count == 3 else {
        throw GeneratorError.invalidArguments
    }

    let outputRoot = URL(fileURLWithPath: arguments[1], isDirectory: true)
    let fontURL = URL(fileURLWithPath: arguments[2])
    guard FileManager.default.fileExists(atPath: fontURL.path) else {
        throw GeneratorError.missingFont(fontURL)
    }

    let fixtures = makeFixtures()
    let fileManager = FileManager.default
    try fileManager.createDirectory(at: outputRoot, withIntermediateDirectories: true)

    for fixture in fixtures {
        let fixtureRoot = outputRoot.appendingPathComponent(fixture.id, isDirectory: true)
        if fileManager.fileExists(atPath: fixtureRoot.path) {
            try fileManager.removeItem(at: fixtureRoot)
        }
        let metadataRoot = fixtureRoot.appendingPathComponent("META-INF", isDirectory: true)
        let contentRoot = fixtureRoot.appendingPathComponent("OEBPS", isDirectory: true)
        try fileManager.createDirectory(at: metadataRoot, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: contentRoot, withIntermediateDirectories: true)

        try write("application/epub+zip", to: fixtureRoot.appendingPathComponent("mimetype"))
        try write(containerXML, to: metadataRoot.appendingPathComponent("container.xml"))
        try write(fixture.css, to: contentRoot.appendingPathComponent("styles.css"))

        for chapter in fixture.chapters {
            try write(chapterDocument(chapter, language: fixture.language), to: contentRoot.appendingPathComponent(chapter.filename))
        }

        if fixture.includeFont {
            try fileManager.copyItem(at: fontURL, to: contentRoot.appendingPathComponent("ShukuTestFont.ttf"))
        }
        if fixture.includeImages {
            try makeRaster(
                size: NSSize(width: 600, height: 800),
                background: NSColor(calibratedRed: 0.82, green: 0.27, blue: 0.16, alpha: 1),
                label: "SHUKU\nAZW3 POC",
                format: .png
            ).write(to: contentRoot.appendingPathComponent("cover.png"), options: .atomic)
            try makeRaster(
                size: NSSize(width: 420, height: 240),
                background: NSColor(calibratedRed: 0.13, green: 0.43, blue: 0.54, alpha: 1),
                label: "PNG 420 × 240",
                format: .png
            ).write(to: contentRoot.appendingPathComponent("figure.png"), options: .atomic)
            try makeRaster(
                size: NSSize(width: 360, height: 270),
                background: NSColor(calibratedRed: 0.24, green: 0.56, blue: 0.32, alpha: 1),
                label: "JPEG 360 × 270",
                format: .jpeg
            ).write(to: contentRoot.appendingPathComponent("photo.jpg"), options: .atomic)
        }

        try write(contentOPF(fixture), to: contentRoot.appendingPathComponent("content.opf"))
        try write(ncxDocument(fixture), to: contentRoot.appendingPathComponent("toc.ncx"))
    }
}

private func write(_ value: String, to url: URL) throws {
    try Data(value.utf8).write(to: url, options: .atomic)
}

private func chapterDocument(_ chapter: Chapter, language: String) -> String {
    """
    <?xml version="1.0" encoding="utf-8"?>
    <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
    <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="\(language)">
      <head>
        <title>\(chapter.title)</title>
        <link rel="stylesheet" type="text/css" href="styles.css" />
      </head>
      <body>
        <h1 id="chapter-title">\(chapter.title)</h1>
        \(chapter.body)
      </body>
    </html>
    """
}

private func contentOPF(_ fixture: FixtureSource) -> String {
    let chapterManifest = fixture.chapters.enumerated().map { index, chapter in
        "    <item id=\"chapter\(index + 1)\" href=\"\(chapter.filename)\" media-type=\"application/xhtml+xml\" />"
    }.joined(separator: "\n")
    let chapterSpine = fixture.chapters.indices.map { index in
        "    <itemref idref=\"chapter\(index + 1)\" />"
    }.joined(separator: "\n")
    let fontManifest = fixture.includeFont
        ? "    <item id=\"test-font\" href=\"ShukuTestFont.ttf\" media-type=\"application/x-font-ttf\" />\n"
        : ""
    let imageManifest = fixture.includeImages
        ? """
            <item id="cover-image" href="cover.png" media-type="image/png" />
            <item id="figure-image" href="figure.png" media-type="image/png" />
            <item id="photo-image" href="photo.jpg" media-type="image/jpeg" />
          """
        : ""
    let coverMetadata = fixture.includeImages ? "    <meta name=\"cover\" content=\"cover-image\" />\n" : ""
    return """
    <?xml version="1.0" encoding="utf-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="2.0">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>\(fixture.title)</dc:title>
        <dc:creator opf:role="aut">书库技术验证组</dc:creator>
        <dc:language>\(fixture.language)</dc:language>
        <dc:identifier id="book-id" opf:scheme="URI">urn:shuku:reader-poc:\(fixture.id)</dc:identifier>
        <dc:description>Self-authored fixture for native libmobi and Readium Navigator validation.</dc:description>
    \(coverMetadata)  </metadata>
      <manifest>
        <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
        <item id="style" href="styles.css" media-type="text/css" />
    \(chapterManifest)
    \(fontManifest)\(imageManifest)
      </manifest>
      <spine toc="ncx" page-progression-direction="\(fixture.progression)">
    \(chapterSpine)
      </spine>
    </package>
    """
}

private func ncxDocument(_ fixture: FixtureSource) -> String {
    var playOrder = 0
    func render(_ node: NavigationNode, depth: Int) -> String {
        switch node {
        case let .item(title, href, children):
            playOrder += 1
            let currentOrder = playOrder
            let indentation = String(repeating: "  ", count: depth)
            let childXML = children.map { render($0, depth: depth + 1) }.joined(separator: "\n")
            let childBlock = childXML.isEmpty ? "" : "\n\(childXML)\n\(indentation)"
            return """
            \(indentation)<navPoint id="nav-\(currentOrder)" playOrder="\(currentOrder)">
            \(indentation)  <navLabel><text>\(title)</text></navLabel>
            \(indentation)  <content src="\(href)" />\(childBlock)</navPoint>
            """
        }
    }
    let navigationXML = fixture.navigation.map { render($0, depth: 2) }.joined(separator: "\n")
    return """
    <?xml version="1.0" encoding="utf-8"?>
    <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="\(fixture.language)">
      <head>
        <meta name="dtb:uid" content="urn:shuku:reader-poc:\(fixture.id)" />
        <meta name="dtb:depth" content="3" />
      </head>
      <docTitle><text>\(fixture.title)</text></docTitle>
      <navMap>
    \(navigationXML)
      </navMap>
    </ncx>
    """
}

private func makeRaster(
    size: NSSize,
    background: NSColor,
    label: String,
    format: NSBitmapImageRep.FileType
) throws -> Data {
    let image = NSImage(size: size)
    image.lockFocus()
    background.setFill()
    NSBezierPath(rect: NSRect(origin: .zero, size: size)).fill()
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: min(size.width, size.height) * 0.075, weight: .bold),
        .foregroundColor: NSColor.white,
        .paragraphStyle: paragraph,
    ]
    let labelRect = NSRect(x: 24, y: size.height * 0.38, width: size.width - 48, height: size.height * 0.3)
    NSString(string: label).draw(in: labelRect, withAttributes: attributes)
    image.unlockFocus()
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let data = bitmap.representation(using: format, properties: format == .jpeg ? [.compressionFactor: 0.9] : [:])
    else {
        throw GeneratorError.imageEncodingFailed
    }
    return data
}

private let containerXML = """
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""

private let baseCSS = """
html { -webkit-text-size-adjust: 100%; }
body { margin: 5%; color: #2d2926; background: #fffdf8; font-family: serif; line-height: 1.7; }
h1 { font-size: 1.65em; margin: 0 0 1.2em; }
p { margin: 0.8em 0; }
a { color: #8b3d2f; }
"""

private func makeFixtures() -> [FixtureSource] {
    let simpleChapters = [
        Chapter(filename: "chapter1.xhtml", title: "第一章 起点", body: #"<p id="start">原生解析从这里开始。This is the first deterministic MOBI paragraph.</p><p><a href="chapter2.xhtml#middle">前往第二章</a></p>"#),
        Chapter(filename: "chapter2.xhtml", title: "第二章 中段", body: #"<p id="middle">章节顺序必须来自 OPF spine，而不是文件名猜测。</p><p><a href="chapter3.xhtml#end">前往第三章</a></p>"#),
        Chapter(filename: "chapter3.xhtml", title: "第三章 终点", body: #"<p id="end">章节跳转、返回和连续翻页都必须稳定。</p>"#),
    ]
    let simpleNavigation: [NavigationNode] = [
        .item(title: "第一章 起点", href: "chapter1.xhtml#start"),
        .item(title: "第二章 中段", href: "chapter2.xhtml#middle"),
        .item(title: "第三章 终点", href: "chapter3.xhtml#end"),
    ]
    let longCJKText = String(repeating: "天地玄黄宇宙洪荒", count: 125_000)

    return [
        FixtureSource(
            id: "01-basic-mobi6",
            outputFilename: "01-basic-mobi6.mobi",
            title: "MOBI6 基础三章",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS,
            chapters: simpleChapters,
            navigation: simpleNavigation,
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "02-basic-kf8",
            outputFilename: "test.azw3",
            title: "KF8 基础冒烟",
            language: "en",
            progression: "ltr",
            css: baseCSS,
            chapters: [
                Chapter(filename: "chapter1.xhtml", title: "Smoke One", body: #"<p id="smoke-one">AZW3_SMOKE_MARKER_ONE</p><p><a href="chapter2.xhtml#smoke-two">Next</a></p>"#),
                Chapter(filename: "chapter2.xhtml", title: "Smoke Two", body: #"<p id="smoke-two">AZW3_SMOKE_MARKER_TWO</p>"#),
            ],
            navigation: [
                .item(title: "Smoke One", href: "chapter1.xhtml#smoke-one"),
                .item(title: "Smoke Two", href: "chapter2.xhtml#smoke-two"),
            ],
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "03-css",
            outputFilename: "03-css.azw3",
            title: "外链 CSS 验证",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS + "\n.css-proof { margin-left: 37px; text-indent: 2em; color: rgb(32, 78, 121); }\n.callout { border-left: 5px solid #b4533f; padding: 13px; }\n",
            chapters: [Chapter(filename: "chapter1.xhtml", title: "样式", body: #"<p id="css-proof" class="css-proof">CSS_COMPUTED_STYLE_MARKER</p><p class="callout">外链样式不能被丢弃。</p>"#)],
            navigation: [.item(title: "样式", href: "chapter1.xhtml#css-proof")],
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "04-font",
            outputFilename: "04-font.azw3",
            title: "内嵌字体验证",
            language: "en",
            progression: "ltr",
            css: "@font-face { font-family: 'Shuku Test Font'; src: url('ShukuTestFont.ttf') format('truetype'); }\n" + baseCSS + "\n.font-proof { font-family: 'Shuku Test Font', serif; font-size: 1.25em; }\n",
            chapters: [Chapter(filename: "chapter1.xhtml", title: "Embedded Font", body: #"<p id="font-proof" class="font-proof">FONT_EMBED_MARKER Hamburgefontsiv 0123456789</p>"#)],
            navigation: [.item(title: "Embedded Font", href: "chapter1.xhtml#font-proof")],
            includeFont: true,
            includeImages: false
        ),
        FixtureSource(
            id: "05-images",
            outputFilename: "05-images.azw3",
            title: "图片和相对路径验证",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS + "\nimg { display: block; max-width: 90%; height: auto; margin: 1em auto; }\n",
            chapters: [Chapter(filename: "chapter1.xhtml", title: "图片", body: #"<p id="images">IMAGE_RESOURCE_MARKER</p><img src="figure.png" alt="PNG test figure" /><img src="photo.jpg" alt="JPEG test photo" />"#)],
            navigation: [.item(title: "图片", href: "chapter1.xhtml#images")],
            includeFont: false,
            includeImages: true
        ),
        FixtureSource(
            id: "06-footnotes",
            outputFilename: "06-footnotes.azw3",
            title: "脚注往返验证",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS + "\n.footnote { font-size: 0.9em; border-top: 1px solid #999; }\n",
            chapters: [
                Chapter(filename: "chapter1.xhtml", title: "正文", body: ##"<p id="note-source-local">同章脚注<a epub:type="noteref" href="#note-local">[1]</a>与跨章脚注<a epub:type="noteref" href="chapter2.xhtml#note-cross">[2]</a>。</p><aside epub:type="footnote" id="note-local" class="footnote"><p>同章脚注内容。<a href="#note-source-local">返回</a></p></aside>"##),
                Chapter(filename: "chapter2.xhtml", title: "跨章注释", body: #"<aside epub:type="footnote" id="note-cross" class="footnote"><p>CROSS_CHAPTER_FOOTNOTE_MARKER。<a href="chapter1.xhtml#note-source-local">返回正文</a></p></aside>"#),
            ],
            navigation: [
                .item(title: "正文", href: "chapter1.xhtml#note-source-local"),
                .item(title: "跨章注释", href: "chapter2.xhtml#note-cross"),
            ],
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "07-complex-toc",
            outputFilename: "07-complex-toc.azw3",
            title: "复杂三级目录验证",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS,
            chapters: [
                Chapter(filename: "chapter1.xhtml", title: "卷一", body: #"<h2 id="part-a">重复标题</h2><p>TOC_LEVEL_2_A</p><h3 id="part-a-1">细目甲</h3><p>TOC_LEVEL_3_A</p>"#),
                Chapter(filename: "chapter2.xhtml", title: "卷二", body: #"<h2 id="part-b">重复标题</h2><p>TOC_LEVEL_2_B</p><h3 id="part-b-1">细目乙</h3><p>TOC_LEVEL_3_B</p>"#),
                Chapter(filename: "chapter3.xhtml", title: "附录", body: #"<p id="appendix">TOC_APPENDIX_MARKER</p>"#),
            ],
            navigation: [
                .item(title: "卷一", href: "chapter1.xhtml#chapter-title", children: [
                    .item(title: "重复标题", href: "chapter1.xhtml#part-a", children: [
                        .item(title: "细目甲", href: "chapter1.xhtml#part-a-1"),
                    ]),
                ]),
                .item(title: "卷二", href: "chapter2.xhtml#chapter-title", children: [
                    .item(title: "重复标题", href: "chapter2.xhtml#part-b", children: [
                        .item(title: "细目乙", href: "chapter2.xhtml#part-b-1"),
                    ]),
                ]),
                .item(title: "附录", href: "chapter3.xhtml#appendix"),
            ],
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "08-zh-hans",
            outputFilename: "08-zh-hans.azw3",
            title: "中文字符完整性验证",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS,
            chapters: [Chapter(filename: "chapter1.xhtml", title: "中文", body: #"<p id="zh-proof">ZH_TEXT_MARKER：天地玄黄，宇宙洪荒；“引号”、《书名号》、破折号——省略号……</p><p>生僻字：𠮷、龘、靐、齉。非 BMP：𠀀𡃁𪚥。扩展字符必须保持 UTF-8 完整。</p>"#)],
            navigation: [.item(title: "中文", href: "chapter1.xhtml#zh-proof")],
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "09-ja-vertical",
            outputFilename: "09-ja-vertical.azw3",
            title: "日本語縦書き検証",
            language: "ja",
            progression: "rtl",
            css: baseCSS + "\nhtml, body { writing-mode: vertical-rl; -webkit-writing-mode: vertical-rl; text-orientation: mixed; }\nruby { ruby-position: over; }\n",
            chapters: [
                Chapter(filename: "chapter1.xhtml", title: "縦書き一", body: #"<p id="vertical-proof">JA_VERTICAL_MARKER。<ruby>漢字<rt>かんじ</rt></ruby>と、句読点。「縦書き」の表示を確認する。</p>"#),
                Chapter(filename: "chapter2.xhtml", title: "縦書き二", body: #"<p id="vertical-two">右から左へのページ進行を確認する。</p>"#),
            ],
            navigation: [
                .item(title: "縦書き一", href: "chapter1.xhtml#vertical-proof"),
                .item(title: "縦書き二", href: "chapter2.xhtml#vertical-two"),
            ],
            includeFont: false,
            includeImages: false
        ),
        FixtureSource(
            id: "10-long-chapter",
            outputFilename: "10-long-chapter.azw3",
            title: "百万汉字超长单章",
            language: "zh-CN",
            progression: "ltr",
            css: baseCSS,
            chapters: [Chapter(filename: "chapter1.xhtml", title: "超长章节", body: "<p id=\"long-start\">LONG_CHAPTER_START</p><p>\(longCJKText)</p><p id=\"long-end\">LONG_CHAPTER_END</p>")],
            navigation: [
                .item(title: "超长章节开头", href: "chapter1.xhtml#long-start"),
                .item(title: "超长章节结尾", href: "chapter1.xhtml#long-end"),
            ],
            includeFont: false,
            includeImages: false
        ),
    ]
}

try main()
