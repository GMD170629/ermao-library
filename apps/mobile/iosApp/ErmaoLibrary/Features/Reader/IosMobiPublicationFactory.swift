import Foundation
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

enum IosMobiPublicationError: Error, Equatable, Sendable {
    case closed
    case duplicateResourcePath(String)
    case invalidSourceIdentity
    case invalidResourceIndex(Int)
    case invalidResourcePath(String)
    case invalidTextEncoding
    case invalidTableOfContents
    case missingReadingOrder
    case unsupportedMediaType(String)
}

enum IosMobiPublicationIdentity {
    static let normalizationIdentifier = "ermao-mobi-core-v1+shuku-locator-dom-v2"
}

struct IosMobiPublicationResult {
    let publication: Publication
    let format: IosMobiFormat
    let parserIdentifier: String
    let normalizationIdentifier: String

    private let lifetime: IosMobiPublicationLifetime

    init(
        publication: Publication,
        format: IosMobiFormat,
        lifetime: IosMobiPublicationLifetime
    ) {
        self.publication = publication
        self.format = format
        parserIdentifier = IosMobiBook.parserIdentifier
        normalizationIdentifier = IosMobiPublicationIdentity.normalizationIdentifier
        self.lifetime = lifetime
    }

    func close() async {
        publication.close()
        await lifetime.close()
    }
}

struct IosMobiPublicationFactory: Sendable {
    private let securityAdapter: IosPublicationSecurityAdapter

    init(securityAdapter: IosPublicationSecurityAdapter = IosPublicationSecurityAdapter()) {
        self.securityAdapter = securityAdapter
    }

    func open(
        fileURL: URL,
        resourceID: String,
        displayTitle: String? = nil
    ) async throws -> IosMobiPublicationResult {
        guard Self.isValidSourceIdentity(resourceID) else {
            throw IosMobiPublicationError.invalidSourceIdentity
        }
        let book = try IosMobiBook.open(fileURL: fileURL)
        do {
            return try await build(
                book: book,
                resourceID: resourceID,
                displayTitle: displayTitle
            )
        } catch {
            await book.close()
            throw error
        }
    }

    func build(
        book: any IosMobiBookAccess,
        resourceID: String,
        displayTitle: String? = nil
    ) async throws -> IosMobiPublicationResult {
        guard Self.isValidSourceIdentity(resourceID) else {
            throw IosMobiPublicationError.invalidSourceIdentity
        }

        let info = try await book.info()
        guard info.readingOrderCount > 0 else {
            throw IosMobiPublicationError.missingReadingOrder
        }

        var descriptors: [IosMobiResourceDescriptor] = []
        descriptors.reserveCapacity(info.resourceCount)
        var descriptorByIndex: [Int: IosMobiResourceDescriptor] = [:]
        var knownPaths: Set<String> = []
        for index in 0 ..< info.resourceCount {
            let coreResource = try await book.resource(at: index)
            guard let href = IosMobiPublicationPath.resourcePath(coreResource.sourceName) else {
                throw IosMobiPublicationError.invalidResourcePath(coreResource.sourceName)
            }
            guard knownPaths.insert(href).inserted else {
                throw IosMobiPublicationError.duplicateResourcePath(href)
            }
            guard MediaType(coreResource.mediaType) != nil else {
                throw IosMobiPublicationError.unsupportedMediaType(coreResource.mediaType)
            }
            let descriptor = IosMobiResourceDescriptor(
                index: index,
                href: href,
                mediaType: coreResource.mediaType,
                category: coreResource.category,
                decodedLength: coreResource.decodedLength
            )
            descriptors.append(descriptor)
            descriptorByIndex[index] = descriptor
        }

        var readingOrderDescriptors: [IosMobiResourceDescriptor] = []
        readingOrderDescriptors.reserveCapacity(info.readingOrderCount)
        for position in 0 ..< info.readingOrderCount {
            let index = try await book.readingOrderResourceIndex(at: position)
            guard let descriptor = descriptorByIndex[index] else {
                throw IosMobiPublicationError.invalidResourceIndex(index)
            }
            readingOrderDescriptors.append(descriptor)
        }

        let lifetime = IosMobiPublicationLifetime(book: book)
        let container = try IosMobiLazyContainer(
            descriptors: descriptors,
            lifetime: lifetime,
            securityAdapter: securityAdapter
        )
        let readingOrder = try readingOrderDescriptors.map { try makeLink($0) }
        let readingOrderPaths = Set(readingOrderDescriptors.map(\.href))
        var resources = try descriptors
            .filter { !readingOrderPaths.contains($0.href) }
            .map { try makeLink($0) }
        if let coverIndex = info.coverResourceIndex,
           let cover = descriptorByIndex[coverIndex]
        {
            resources.removeAll { $0.href == cover.href }
            resources.append(try makeLink(cover, relation: .cover))
        }

        var tocEntries: [IosMobiTocInfo] = []
        tocEntries.reserveCapacity(info.tocCount)
        for index in 0 ..< info.tocCount {
            tocEntries.append(try await book.toc(at: index))
        }
        let tableOfContents = try makeTableOfContents(
            entries: tocEntries,
            resources: descriptorByIndex
        )

        let title = try await book.metadata(.title)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallbackTitle = displayTitle?.trimmingCharacters(in: .whitespacesAndNewlines)
        let author = try await book.metadata(.author)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let language = try await book.metadata(.language)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let publisher = try await book.metadata(.publisher)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let description = try await book.metadata(.description)

        let metadata = Metadata(
            identifier: "urn:shuku:publication:\(resourceID)",
            conformsTo: [.epub],
            title: title.flatMap { $0.isEmpty ? nil : $0 }
                ?? fallbackTitle.flatMap { $0.isEmpty ? nil : $0 }
                ?? resourceID,
            languages: language.flatMap { $0.isEmpty ? nil : [$0] } ?? [],
            authors: author.flatMap { $0.isEmpty ? nil : [Contributor(name: $0)] } ?? [],
            publishers: publisher.flatMap { $0.isEmpty ? nil : [Contributor(name: $0)] } ?? [],
            layout: .reflowable,
            readingProgression: Self.readingProgression(info.readingDirection),
            description: description,
            otherMetadata: [
                "https://shuku.app/reader/decoded-format": Self.decodedFormat(info.format),
                "https://shuku.app/reader/adapter": IosMobiBook.parserIdentifier,
                "https://shuku.app/reader/normalization": IosMobiPublicationIdentity.normalizationIdentifier,
            ]
        )
        let publication = Publication(
            manifest: Manifest(
                metadata: metadata,
                readingOrder: readingOrder,
                resources: resources,
                tableOfContents: tableOfContents
            ),
            container: container,
            servicesBuilder: PublicationServicesBuilder(
                content: DefaultContentService.makeFactory(
                    resourceContentIteratorFactories: [
                        HTMLResourceContentIterator.Factory(),
                    ]
                ),
                positions: EPUBPositionsService.makeFactory(
                    reflowableStrategy: .archiveEntryLength(pageLength: 1024)
                ),
                search: StringSearchService.makeFactory()
            )
        )
        return IosMobiPublicationResult(
            publication: publication,
            format: info.format,
            lifetime: lifetime
        )
    }

    private func makeLink(
        _ descriptor: IosMobiResourceDescriptor,
        relation: LinkRelation? = nil
    ) throws -> Link {
        guard let mediaType = MediaType(descriptor.mediaType) else {
            throw IosMobiPublicationError.unsupportedMediaType(descriptor.mediaType)
        }
        return Link(
            href: descriptor.href,
            mediaType: mediaType,
            rel: relation
        )
    }

    private func makeTableOfContents(
        entries: [IosMobiTocInfo],
        resources: [Int: IosMobiResourceDescriptor]
    ) throws -> [Link] {
        var childrenByParent: [Int?: [Int]] = [:]
        for (index, entry) in entries.enumerated() {
            if let parent = entry.parentIndex {
                guard parent >= 0, parent < entries.count, parent != index else {
                    throw IosMobiPublicationError.invalidTableOfContents
                }
            }
            childrenByParent[entry.parentIndex, default: []].append(index)
        }

        var visiting: Set<Int> = []
        var visited: Set<Int> = []
        func makeNode(_ index: Int) throws -> Link {
            guard visiting.insert(index).inserted else {
                throw IosMobiPublicationError.invalidTableOfContents
            }
            defer {
                visiting.remove(index)
                visited.insert(index)
            }
            let entry = entries[index]
            let children = try childrenByParent[index, default: []].map(makeNode)
            let targetResource = entry.targetResourceIndex.flatMap { resources[$0] }
            if entry.targetResourceIndex != nil, targetResource == nil {
                throw IosMobiPublicationError.invalidTableOfContents
            }
            let targetHREF = targetResource.flatMap {
                IosMobiPublicationPath.reference(
                    path: $0.href,
                    fragment: entry.fragment
                )
            } ?? children.first?.href
            guard let targetHREF else {
                throw IosMobiPublicationError.invalidTableOfContents
            }
            return Link(
                href: targetHREF,
                mediaType: targetResource.flatMap { MediaType($0.mediaType) }
                    ?? children.first?.mediaType,
                title: entry.title?.trimmingCharacters(in: .whitespacesAndNewlines),
                children: children
            )
        }

        let roots = try childrenByParent[nil, default: []].map(makeNode)
        guard visited.count == entries.count else {
            throw IosMobiPublicationError.invalidTableOfContents
        }
        return roots
    }

    private static func isValidSourceIdentity(_ value: String) -> Bool {
        guard (1 ... 512).contains(value.utf8.count) else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || "-_.:".unicodeScalars.contains($0)
        }
    }

    private static func decodedFormat(_ format: IosMobiFormat) -> String {
        switch format {
        case .mobi6:
            "mobi6"
        case .kf8:
            "kf8"
        case .hybridKf8:
            "hybrid-kf8"
        case .hybridMobi6Fallback:
            "hybrid-mobi6-fallback"
        }
    }

    private static func readingProgression(
        _ direction: IosMobiReadingDirection
    ) -> ReadingProgression {
        switch direction {
        case .unknown:
            .auto
        case .leftToRight:
            .ltr
        case .rightToLeft:
            .rtl
        }
    }
}
