import Foundation
import ReadiumShared
import ReadiumStreamer

struct PublicationPreflightReport: Equatable, Sendable {
    let resourceCount: Int
    let totalBytes: Int
    let verifiedReferenceCount: Int
}

struct MobiPublicationResult {
    let book: MobiExtractedBook
    let publication: Publication
    let preflight: PublicationPreflightReport
}

enum MobiPublicationError: Error, Equatable, LocalizedError, Sendable {
    case unsupportedMediaType(String)
    case unresolvedResource(source: String, target: String)
    case unresolvedFragment(source: String, target: String, fragment: String)
    case unreadablePublicationResource(String)
    case missingReadingOrder

    var errorDescription: String? {
        switch self {
        case let .unsupportedMediaType(type):
            String(format: String(localized: "error.unsupportedMediaType"), type)
        case let .unresolvedResource(source, target):
            String(format: String(localized: "error.unresolvedResource"), source, target)
        case let .unresolvedFragment(source, target, fragment):
            String(format: String(localized: "error.unresolvedFragment"), source, target, fragment)
        case let .unreadablePublicationResource(href):
            String(format: String(localized: "error.unreadablePublicationResource"), href)
        case .missingReadingOrder:
            String(localized: "error.missingReadingOrder")
        }
    }
}

struct MobiPublicationFactory: Sendable {
    private let extractor: any MobiExtracting

    init(extractor: any MobiExtracting = NativeMobiExtractor()) {
        self.extractor = extractor
    }

    func open(_ file: URL) async throws -> MobiPublicationResult {
        let book = try await extractor.extract(file)
        return try await build(book)
    }

    func build(_ book: MobiExtractedBook) async throws -> MobiPublicationResult {
        guard !book.readingOrder.isEmpty else {
            throw MobiPublicationError.missingReadingOrder
        }
        let container = try InMemoryMobiContainer(resources: book.allResources)
        let readingOrder = try book.readingOrder.map(makeLink)
        let readingOrderHREFs = Set(readingOrder.map(\.href))
        let resources = try book.resources
            .filter { !readingOrderHREFs.contains($0.href) }
            .map(makeLink)
        let toc = try book.tableOfContents.map(makeTOCLink)

        let metadata = Metadata(
            identifier: "urn:shuku:mobi:\(book.format.rawValue):\(book.metadata.title)",
            conformsTo: [.epub],
            title: book.metadata.title,
            languages: book.metadata.language.map { [$0] } ?? [],
            authors: book.metadata.author.map { [Contributor(name: $0)] } ?? [],
            layout: .reflowable,
            readingProgression: book.metadata.readingProgression == .rightToLeft ? .rtl : .ltr,
            description: book.metadata.description,
            otherMetadata: [
                "https://shuku.app/reader/source-format": .string(book.format.rawValue),
                "https://shuku.app/reader/adapter": .string("libmobi-v0.12"),
            ]
        )
        let manifest = Manifest(
            metadata: metadata,
            readingOrder: readingOrder,
            resources: resources,
            tableOfContents: toc
        )
        let publication = Publication(
            manifest: manifest,
            container: container,
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
        let preflight = try await preflight(book: book, publication: publication)
        return MobiPublicationResult(book: book, publication: publication, preflight: preflight)
    }

    private func makeLink(_ resource: MobiResource) throws -> Link {
        guard let mediaType = MediaType(resource.mediaType) else {
            throw MobiPublicationError.unsupportedMediaType(resource.mediaType)
        }
        return Link(href: resource.href, mediaType: mediaType)
    }

    private func makeTOCLink(_ item: MobiNavigationItem) throws -> Link {
        guard let href = PublicationPath.normalizedReference(item.href) else {
            throw MobiExtractionError.invalidResourcePath(item.href)
        }
        return Link(
            href: href,
            mediaType: MediaType("text/html"),
            title: item.title,
            children: try item.children.map(makeTOCLink)
        )
    }

    private func preflight(book: MobiExtractedBook, publication: Publication) async throws -> PublicationPreflightReport {
        for resource in book.allResources {
            guard let readiumResource = publication.get(try makeLink(resource)),
                  case .success = await readiumResource.read()
            else {
                throw MobiPublicationError.unreadablePublicationResource(resource.href)
            }
        }

        let scanner = InternalReferenceScanner()
        let references = book.allResources.flatMap(scanner.references)
        let resourcesByHREF = Dictionary(uniqueKeysWithValues: book.allResources.map { ($0.href, $0) })
        for reference in references {
            guard let target = resourcesByHREF[reference.targetHREF] else {
                throw MobiPublicationError.unresolvedResource(source: reference.sourceHREF, target: reference.targetHREF)
            }
            if let fragment = reference.fragment, !fragment.isEmpty,
               target.isHTML, !containsAnchor(fragment, in: target.data)
            {
                throw MobiPublicationError.unresolvedFragment(
                    source: reference.sourceHREF,
                    target: reference.targetHREF,
                    fragment: fragment
                )
            }
        }
        for item in book.tableOfContents.flattened {
            guard let targetPath = PublicationPath.resourcePath(from: item.href),
                  let target = resourcesByHREF[targetPath]
            else {
                throw MobiPublicationError.unresolvedResource(source: "toc", target: item.href)
            }
            if let hash = item.href.firstIndex(of: "#") {
                let fragment = String(item.href[item.href.index(after: hash)...])
                if !fragment.isEmpty, !containsAnchor(fragment, in: target.data) {
                    throw MobiPublicationError.unresolvedFragment(source: "toc", target: targetPath, fragment: fragment)
                }
            }
        }
        return PublicationPreflightReport(
            resourceCount: book.allResources.count,
            totalBytes: book.allResources.reduce(0) { $0 + $1.data.count },
            verifiedReferenceCount: references.count + book.tableOfContents.flattened.count
        )
    }

    private func containsAnchor(_ fragment: String, in data: Data) -> Bool {
        guard let html = String(data: data, encoding: .utf8),
              let decoded = fragment.removingPercentEncoding
        else {
            return false
        }
        let escaped = NSRegularExpression.escapedPattern(for: decoded)
        let pattern = #"(?i)\b(?:id|name)\s*=\s*[\"']"# + escaped + #"[\"']"#
        return html.range(of: pattern, options: .regularExpression) != nil
    }
}
