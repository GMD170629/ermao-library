import Foundation
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

enum IosFb2PublicationError: Error, Sendable {
    case invalidXML
    case invalidResourcePath
    case limitExceeded
}

struct IosFb2PublicationFactory: Sendable {
    func open(_ managed: IosManagedPublication) throws -> Publication {
        let data = try Data(contentsOf: managed.fileURL, options: [.mappedIfSafe])
        guard !data.isEmpty, data.count <= 64 * 1_024 * 1_024 else {
            throw IosFb2PublicationError.limitExceeded
        }
        guard let probe = String(data: data, encoding: .isoLatin1),
              probe.range(
                of: #"<!DOCTYPE\b|<!ENTITY\b"#,
                options: String.CompareOptions([.regularExpression, .caseInsensitive])
              ) == nil
        else {
            throw IosFb2PublicationError.invalidXML
        }
        let delegate = IosFb2Parser(fallbackTitle: managed.displayTitle)
        let parser = XMLParser(data: data)
        parser.shouldProcessNamespaces = true
        parser.shouldReportNamespacePrefixes = false
        parser.shouldResolveExternalEntities = false
        parser.externalEntityResolvingPolicy = .never
        parser.delegate = delegate
        guard parser.parse() else { throw delegate.failure ?? IosFb2PublicationError.invalidXML }
        let document = try delegate.document()

        var storedResources: [String: Data] = [:]
        var readingOrder: [Link] = []
        for (offset, section) in document.sections.enumerated() {
            let href = String(format: "fb2/section-%04d.xhtml", offset + 1)
            let title = section.title.isEmpty ? "\(document.title) \(offset + 1)" : section.title
            let content = section.blocks.map { block in
                let element = block.isHeading ? "h2" : "p"
                return "<\(element) id=\"fb2-node-\(block.index)\">\(block.text.escapedXML)</\(element)>"
            }.joined(separator: "\n")
            let xhtml = """
            <?xml version="1.0" encoding="utf-8"?>
            <html xmlns="http://www.w3.org/1999/xhtml"><head><title>\(title.escapedXML)</title>
            <link rel="stylesheet" type="text/css" href="reader.css"/></head>
            <body><section>\(content)</section></body></html>
            """
            storedResources[href] = try IosPublicationSecurityPolicy.decorate(data: Data(xhtml.utf8))
            readingOrder.append(Link(href: href, mediaType: .xhtml, title: title))
        }
        let stylesheetHref = "fb2/reader.css"
        storedResources[stylesheetHref] = Data(Self.stylesheet.utf8)
        let container = try IosFb2Container(resources: storedResources)
        return Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:fb2:\(managed.resourceID)",
                    conformsTo: [.epub],
                    title: document.title,
                    layout: .reflowable,
                    readingProgression: .ltr
                ),
                readingOrder: readingOrder,
                resources: [Link(href: stylesheetHref, mediaType: .css)],
                tableOfContents: readingOrder
            ),
            container: container,
            servicesBuilder: PublicationServicesBuilder(
                content: DefaultContentService.makeFactory(
                    resourceContentIteratorFactories: [HTMLResourceContentIterator.Factory()]
                ),
                positions: EPUBPositionsService.makeFactory(
                    reflowableStrategy: .archiveEntryLength(pageLength: 1024)
                ),
                search: StringSearchService.makeFactory()
            )
        )
    }

    private static let stylesheet = """
    body { margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere; }
    section { margin: 0 0 2rem; } h2 { line-height: 1.3; }
    p { margin: 0 0 1em; }
    """
}

private final class IosFb2Parser: NSObject, XMLParserDelegate {
    private let fallbackTitle: String
    private var path: [String] = []
    private var sections: [IosMutableFb2Section] = []
    private var currentSection: IosMutableFb2Section?
    private var sectionDepth = 0
    private var elementCount = 0
    private var blockIndex = 0
    private var captureElement: String?
    private var capture = ""
    private var bookTitle: String?
    private(set) var failure: IosFb2PublicationError?

    init(fallbackTitle: String) { self.fallbackTitle = fallbackTitle }

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        let name = elementName.lowercased()
        elementCount += 1
        guard elementCount <= 200_000, path.count < 128 else {
            failure = .limitExceeded
            parser.abortParsing()
            return
        }
        if path.isEmpty, name != "fictionbook" {
            failure = .invalidXML
            parser.abortParsing()
            return
        }
        path.append(name)
        if name == "section", path.contains("body") {
            if sectionDepth == 0 {
                let section = IosMutableFb2Section()
                sections.append(section)
                currentSection = section
                guard sections.count <= 10_000 else {
                    failure = .limitExceeded
                    parser.abortParsing()
                    return
                }
            }
            sectionDepth += 1
        }
        if ["p", "subtitle", "v", "text-author"].contains(name) {
            captureElement = name
            capture = ""
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        guard captureElement != nil else { return }
        capture += string
        if capture.count > 1_000_000 {
            failure = .limitExceeded
            parser.abortParsing()
        }
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        let name = elementName.lowercased()
        if name == captureElement {
            let text = capture.normalizedXMLText
            if !text.isEmpty {
                if path.contains("description"), path.contains("book-title") {
                    bookTitle = text
                } else if path.contains("body") {
                    let section: IosMutableFb2Section
                    if let currentSection {
                        section = currentSection
                    } else {
                        section = IosMutableFb2Section()
                        sections.append(section)
                        currentSection = section
                    }
                    blockIndex += 1
                    guard blockIndex <= 200_000 else {
                        failure = .limitExceeded
                        parser.abortParsing()
                        return
                    }
                    let isHeading = path.contains("title") || name == "subtitle"
                    section.blocks.append(IosFb2Block(index: blockIndex, text: text, isHeading: isHeading))
                    if isHeading, section.title.isEmpty { section.title = text }
                }
            }
            captureElement = nil
            capture = ""
        }
        if name == "section", sectionDepth > 0 {
            sectionDepth -= 1
            if sectionDepth == 0 { currentSection = nil }
        }
        guard path.last == name else {
            failure = .invalidXML
            parser.abortParsing()
            return
        }
        path.removeLast()
    }

    func parser(_ parser: XMLParser, parseErrorOccurred parseError: Error) {
        if failure == nil { failure = .invalidXML }
    }

    func document() throws -> IosFb2Document {
        if let failure { throw failure }
        let nonEmpty = sections.filter { !$0.blocks.isEmpty }
        guard !nonEmpty.isEmpty else { throw IosFb2PublicationError.invalidXML }
        return IosFb2Document(
            title: bookTitle?.isEmpty == false ? bookTitle! : fallbackTitle,
            sections: nonEmpty.map { IosFb2Section(title: $0.title, blocks: $0.blocks) }
        )
    }
}

private struct IosFb2Document { let title: String; let sections: [IosFb2Section] }
private struct IosFb2Section { let title: String; let blocks: [IosFb2Block] }
private struct IosFb2Block { let index: Int; let text: String; let isHeading: Bool }
private final class IosMutableFb2Section { var title = ""; var blocks: [IosFb2Block] = [] }

private final class IosFb2Container: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let resources: [String: IosFb2Resource]

    init(resources: [String: Data]) throws {
        var mapped: [String: IosFb2Resource] = [:]
        var entries: Set<AnyURL> = []
        for (href, data) in resources {
            guard let url = AnyURL(string: href) else { throw IosFb2PublicationError.invalidResourcePath }
            mapped[href] = IosFb2Resource(data: data)
            entries.insert(url)
        }
        self.resources = mapped
        self.entries = entries
    }

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
        resources[url.anyURL.removingQuery().removingFragment().string]
    }

    func close() {}
}

private final class IosFb2Resource: ReadiumShared.Resource, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    private let data: Data

    init(data: Data) { self.data = data }
    func estimatedLength() async -> ReadResult<UInt64?> { .success(UInt64(data.count)) }
    func properties() async -> ReadResult<ResourceProperties> { .success(ResourceProperties()) }
    func stream(range: Range<UInt64>?, consume: @escaping (Data) -> Void) async -> ReadResult<Void> {
        let lower = Int(min(range?.lowerBound ?? 0, UInt64(data.count)))
        let upper = Int(min(range?.upperBound ?? UInt64(data.count), UInt64(data.count)))
        if lower < upper { consume(data[lower ..< upper]) }
        return .success(())
    }
}

private extension String {
    var normalizedXMLText: String {
        replacingOccurrences(of: #"[\s\p{Z}]+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var escapedXML: String {
        replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&apos;")
    }
}
