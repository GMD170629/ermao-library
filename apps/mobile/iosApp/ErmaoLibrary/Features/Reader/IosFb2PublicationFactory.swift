import Foundation
import CryptoKit
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

enum IosFb2PublicationError: Error, Sendable {
    case invalidXML
    case invalidResourcePath
    case limitExceeded
}

struct IosFb2PublicationFactory: Sendable {
    func open(_ managed: IosManagedPublication) throws -> Publication {
        let parsed = try Self.read(fileURL: managed.fileURL, fallbackTitle: managed.displayTitle)
        let document = parsed.document
        var resources = parsed.images
        for resource in document.resources {
            resources[resource.href] = try IosPublicationSecurityPolicy.decorate(data: Data(resource.xhtml.utf8))
        }
        resources[document.stylesheetHref] = Data(document.stylesheet.utf8)
        return Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:fb2:\(managed.resourceID)",
                    conformsTo: [.epub],
                    title: document.title,
                    languages: document.language.map { [$0] } ?? [],
                    layout: .reflowable,
                    readingProgression: .ltr
                ),
                readingOrder: document.resources.map { Link(href: $0.href, mediaType: .xhtml, title: $0.title) },
                resources: [Link(href: document.stylesheetHref, mediaType: .css)] + document.images.map {
                    Link(href: $0.href, mediaType: MediaType($0.mediaType))
                },
                tableOfContents: document.tableOfContents.map(Self.navigationLink)
            ),
            container: try IosFb2Container(resources: resources),
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

    static func read(fileURL: URL, fallbackTitle: String) throws -> IosParsedFb2Source {
        let size = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= 64 * 1_024 * 1_024 else { throw IosFb2PublicationError.limitExceeded }
        let data = try Data(contentsOf: fileURL, options: [.mappedIfSafe])
        guard let probe = String(data: data, encoding: .isoLatin1),
              let prepared = try ErmaoShared.Fb2XmlPolicy().prepare(probe: probe).data(using: .isoLatin1)
        else { throw IosFb2PublicationError.invalidXML }
        let decoder = ErmaoShared.Fb2PublicationDecoder()
        let delegate = IosFb2Parser(decoder: decoder)
        let parser = XMLParser(data: prepared)
        parser.shouldProcessNamespaces = true
        parser.shouldReportNamespacePrefixes = true
        parser.shouldResolveExternalEntities = false
        parser.externalEntityResolvingPolicy = .never
        parser.delegate = delegate
        guard parser.parse(), delegate.failure == nil else {
            throw delegate.failure ?? IosFb2PublicationError.invalidXML
        }
        var images: [String: Data] = [:]
        var links: [ErmaoShared.Fb2ImageLink] = []
        var totalSize = 0
        for image in try decoder.embeddedImages() {
            guard let content = Data(base64Encoded: image.encoded),
                  content.count <= 20 * 1_024 * 1_024,
                  matchesImage(content, mediaType: image.mediaType)
            else { throw IosFb2PublicationError.invalidXML }
            totalSize += content.count
            guard totalSize <= 128 * 1_024 * 1_024 else { throw IosFb2PublicationError.limitExceeded }
            let digest = SHA256.hash(data: Data(image.identifier.utf8)).prefix(10)
                .map { String(format: "%02x", $0) }.joined()
            let extensions = ["image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"]
            guard let fileExtension = extensions[image.mediaType] else { throw IosFb2PublicationError.invalidXML }
            let href = "fb2/images/\(digest).\(fileExtension)"
            images[href] = content
            links.append(ErmaoShared.Fb2ImageLink(identifier: image.identifier, href: href, mediaType: image.mediaType))
        }
        return IosParsedFb2Source(document: try decoder.finish(fallbackTitle: fallbackTitle, images: links), images: images)
    }

    private static func navigationLink(_ entry: ErmaoShared.Fb2NavigationEntry) -> Link {
        Link(href: entry.href, mediaType: .xhtml, title: entry.title, children: entry.children.map(navigationLink))
    }

    private static func matchesImage(_ data: Data, mediaType: String) -> Bool {
        switch mediaType {
        case "image/jpeg": data.starts(with: [0xFF, 0xD8, 0xFF])
        case "image/png": data.starts(with: [0x89, 80, 78, 71, 13, 10, 26, 10])
        case "image/gif": data.starts(with: Data("GIF87a".utf8)) || data.starts(with: Data("GIF89a".utf8))
        case "image/webp": data.starts(with: Data("RIFF".utf8)) && data.count >= 12 && data[8..<12] == Data("WEBP".utf8)
        default: false
        }
    }
}

struct IosParsedFb2Source {
    let document: ErmaoShared.Fb2PublicationDocument
    let images: [String: Data]
}

private final class IosFb2Parser: NSObject, XMLParserDelegate {
    private let decoder: ErmaoShared.Fb2PublicationDecoder
    private var namespaces: [String: [String]] = ["xml": ["http://www.w3.org/XML/1998/namespace"]]
    private(set) var failure: Error?

    init(decoder: ErmaoShared.Fb2PublicationDecoder) { self.decoder = decoder }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) {
        record(parser) {
            // Foundation can accept undeclared attribute prefixes without a parse error.
            // Keep the same strict namespace boundary as Android and the server parser.
            for qualified in Array(attributeDict.keys) + [qName ?? elementName] {
                if let colon = qualified.firstIndex(of: ":"),
                   namespaces[String(qualified[..<colon])]?.last == nil {
                    throw IosFb2PublicationError.invalidXML
                }
            }
            try decoder.startElement(name: elementName, attributes: attributeDict)
        }
    }

    func parser(_ parser: XMLParser, didStartMappingPrefix prefix: String, toURI namespaceURI: String) {
        namespaces[prefix, default: []].append(namespaceURI)
    }

    func parser(_ parser: XMLParser, didEndMappingPrefix prefix: String) {
        namespaces[prefix]?.removeLast()
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        record(parser) { try decoder.text(value: string) }
    }

    func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
        guard let text = String(data: CDATABlock, encoding: .utf8) else {
            failure = IosFb2PublicationError.invalidXML
            parser.abortParsing()
            return
        }
        record(parser) { try decoder.text(value: text) }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        record(parser) { try decoder.endElement(name: elementName) }
    }

    func parser(_ parser: XMLParser, parseErrorOccurred parseError: Error) {
        if failure == nil { failure = parseError }
    }

    private func record(_ parser: XMLParser, _ operation: () throws -> Void) {
        guard failure == nil else { return }
        do { try operation() } catch {
            failure = error
            parser.abortParsing()
        }
    }
}

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
