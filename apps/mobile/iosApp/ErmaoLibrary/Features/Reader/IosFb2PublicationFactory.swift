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
            resources[resource.href] = try IosPublicationSecurityPolicy.generatedChapter(resource.xhtml)
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
                search: ContentSearchService.makeFactory()
            )
        )
    }

    static func read(fileURL: URL, fallbackTitle: String) throws -> IosParsedFb2Source {
        do {
            guard let size = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize else {
                throw IosReaderFailure.fileRead(
                    NSError(domain: NSCocoaErrorDomain, code: NSFileReadUnknownError)
                )
            }
            let sourceByteCount = Int64(size)
            if let failure = ErmaoShared.ReaderAdmission.shared.localSafetyFailure(
                format: "fb2",
                bytes: sourceByteCount
            ) {
                throw IosReaderFailure.safety(failure)
            }
            if let failure = ErmaoShared.PublicKt.readerSafetyFb2TextBudgetFailure(
                sourceByteCount: sourceByteCount
            ) {
                throw IosReaderFailure.safety(failure)
            }
            let data = try Data(contentsOf: fileURL, options: [.mappedIfSafe])
            if let failure = ErmaoShared.PublicKt.readerSafetyFb2TextBudgetFailure(
                sourceByteCount: Int64(data.count)
            ) {
                throw IosReaderFailure.safety(failure)
            }
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
            var totalSize: Int64 = 0
            let maximumImageBytes = ErmaoShared.PublicKt.readerSafetyFb2DecodedImageMaxBytes()
            let maximumTotalImageBytes = ErmaoShared.PublicKt.readerSafetyFb2DecodedImagesTotalMaxBytes()
            for image in try decoder.embeddedImages() {
                guard let content = Data(base64Encoded: image.encoded),
                      Int64(content.count) <= maximumImageBytes,
                      Int64(content.count) <= maximumTotalImageBytes - totalSize
                else {
                    // FB2.IMAGE_BUDGET is BLOCK_RESOURCE: one bad image must not reject the book.
                    continue
                }
                totalSize += Int64(content.count)
                let digest = SHA256.hash(data: Data(image.identifier.utf8)).prefix(10)
                    .map { String(format: "%02x", $0) }.joined()
                let fileExtension = ErmaoShared.PublicKt.readerSafetyFb2EmbeddedImageExtension(
                    mediaType: image.mediaType
                ) ?? ""
                let href = "fb2/images/\(digest)\(fileExtension)"
                images[href] = content
                links.append(ErmaoShared.Fb2ImageLink(
                    identifier: image.identifier,
                    href: href,
                    mediaType: image.mediaType
                ))
            }
            let document = try decoder.finish(fallbackTitle: fallbackTitle, images: links)
            let projection = try IosChapterCore.parseXML(
                format: UInt32(ERMAO_CHAPTER_FB2),
                events: delegate.chapterEvents
            )
            let navigation = try Self.navigationEntries(projection.entries)
            return IosParsedFb2Source(
                document: document.withTableOfContents(entries: navigation),
                images: images
            )
        } catch {
            let underlyingError = error as NSError
            guard let failure = underlyingError.kotlinException as? ErmaoShared.ReaderSafetyException else {
                throw error
            }
            throw IosReaderFailure.safety(failure.failure, underlyingError: underlyingError)
        }
    }

    private static func navigationLink(_ entry: ErmaoShared.Fb2NavigationEntry) -> Link {
        Link(
            href: entry.href ?? "",
            mediaType: .xhtml,
            title: entry.title,
            properties: Properties(["shuku:navigationKey": .string(entry.navigationKey)]),
            children: entry.children.map(navigationLink)
        )
    }

    private static func navigationEntries(_ entries: [IosChapterCoreEntry]) throws -> [ErmaoShared.Fb2NavigationEntry] {
        var childrenByParent: [Int: [Int]] = [:]
        for (index, entry) in entries.enumerated() {
            childrenByParent[entry.parentIndex ?? -1, default: []].append(index)
        }
        func make(_ index: Int) throws -> ErmaoShared.Fb2NavigationEntry {
            let entry = entries[index]
            let children = try childrenByParent[index, default: []].map(make)
            return ErmaoShared.Fb2NavigationEntry(
                href: entry.href,
                title: entry.title,
                children: children,
                navigationKey: entry.key
            )
        }
        return try childrenByParent[-1, default: []].map(make)
    }

}

struct IosParsedFb2Source {
    let document: ErmaoShared.Fb2PublicationDocument
    let images: [String: Data]
}

private final class IosFb2Parser: NSObject, XMLParserDelegate {
    private let decoder: ErmaoShared.Fb2PublicationDecoder
    private(set) var failure: Error?
    private(set) var chapterEvents: [IosChapterCoreXmlEvent] = []
    private var sourceOrdinal: UInt64 = 0
    private var bodyDepth = 0
    private var topSectionCount = 0
    private var sectionHrefs: [String] = []

    init(decoder: ErmaoShared.Fb2PublicationDecoder) { self.decoder = decoder }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) {
        record(parser) {
            let name = elementName.split(separator: ":").last.map(String.init) ?? elementName
            let ordinal = sourceOrdinal
            sourceOrdinal += 1
            if name == "body" { bodyDepth += 1 }
            let targetHref: String?
            if name == "section", bodyDepth > 0 {
                let href = sectionHrefs.last ?? {
                    topSectionCount += 1
                    return "fb2/section-\(String(format: "%04d", topSectionCount)).xhtml"
                }()
                sectionHrefs.append(href)
                targetHref = "\(href)#chapter-node-\(ordinal)"
            } else {
                targetHref = nil
            }
            let attributes = attributeDict.reduce(into: [String: String]()) { result, item in
                result[item.key.split(separator: ":").last.map(String.init) ?? item.key] = item.value
            }
            try decoder.startElement(name: name, attributes: attributes, sourceStart: Int64(ordinal))
            chapterEvents.append(IosChapterCoreXmlEvent(
                kind: 1,
                name: name,
                text: nil,
                attributes: attributes.map { IosChapterCoreXmlAttribute(name: $0.key, value: $0.value) },
                href: targetHref
            ))
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        record(parser) {
            try decoder.text(value: string)
            if !string.isEmpty {
                chapterEvents.append(IosChapterCoreXmlEvent(kind: 2, name: nil, text: string, attributes: [], href: nil))
            }
        }
    }

    func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
        guard let text = String(data: CDATABlock, encoding: .utf8) else {
            failure = IosFb2PublicationError.invalidXML
            parser.abortParsing()
            return
        }
        record(parser) {
            try decoder.text(value: text)
            if !text.isEmpty {
                chapterEvents.append(IosChapterCoreXmlEvent(kind: 2, name: nil, text: text, attributes: [], href: nil))
            }
        }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        record(parser) {
            let name = elementName.split(separator: ":").last.map(String.init) ?? elementName
            try decoder.endElement(name: name)
            chapterEvents.append(IosChapterCoreXmlEvent(kind: 3, name: name, text: nil, attributes: [], href: nil))
            if name == "section", !sectionHrefs.isEmpty { sectionHrefs.removeLast() }
            if name == "body" { bodyDepth -= 1 }
        }
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
