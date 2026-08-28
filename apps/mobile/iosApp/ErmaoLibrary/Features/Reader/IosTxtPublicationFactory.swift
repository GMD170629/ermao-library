import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

enum IosTxtPublicationError: Error, Sendable {
    case invalidEncoding
    case invalidResourcePath
}

struct IosTxtPublicationFactory: Sendable {
    func open(_ managed: IosManagedPublication) throws -> Publication {
        let bytes = Int64(try managed.fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0)
        if let failure = ErmaoShared.ReaderAdmission.shared.localFailure(format: "txt", bytes: bytes) {
            throw IosReaderFailure(code: IosReaderFailureCode(sharedCode: failure))
        }
        let data = try Data(contentsOf: managed.fileURL, options: [.mappedIfSafe])
        guard let decoded = IosStrictTxtDecoder.decode(data)
        else { throw IosTxtPublicationError.invalidEncoding }

        // Chapter boundaries, hrefs, block IDs, escaping and CSS are owned by KMP.
        let normalized = try ErmaoShared.TxtPublicationNormalizer().normalize(
            decodedText: decoded,
            publicationTitle: managed.displayTitle
        )
        var resources: [String: Data] = [:]
        var readingOrder: [Link] = []
        for resource in normalized.resources {
            resources[resource.href] = IosPublicationSecurityPolicy.generatedChapter(resource.xhtml)
            readingOrder.append(
                Link(href: resource.href, mediaType: .xhtml, title: resource.title)
            )
        }
        resources[normalized.stylesheetHref] = Data(normalized.stylesheet.utf8)
        let container = try IosTxtContainer(resources: resources)
        return Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:txt:\(managed.resourceID)",
                    conformsTo: [.epub],
                    title: normalized.title,
                    layout: .reflowable,
                    readingProgression: .ltr
                ),
                readingOrder: readingOrder,
                resources: [Link(href: normalized.stylesheetHref, mediaType: .css)],
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
                search: ContentSearchService.makeFactory()
            )
        )
    }

}

enum IosStrictTxtDecoder {
    static func decode(_ data: Data) -> String? {
        let decoded: String?
        if data.starts(with: [0xEF, 0xBB, 0xBF]) {
            decoded = String(data: data.dropFirst(3), encoding: .utf8)
        } else if data.starts(with: [0xFF, 0xFE]) {
            decoded = String(data: data.dropFirst(2), encoding: .utf16LittleEndian)
        } else if data.starts(with: [0xFE, 0xFF]) {
            decoded = String(data: data.dropFirst(2), encoding: .utf16BigEndian)
        } else {
            decoded = String(data: data, encoding: .utf8)
                ?? String(data: data, encoding: String.Encoding(rawValue: 0x8000_0632))
        }
        return decoded
    }
}

private final class IosTxtContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let resources: [String: IosTxtResource]

    init(resources: [String: Data]) throws {
        var mapped: [String: IosTxtResource] = [:]
        var entries: Set<AnyURL> = []
        for (href, data) in resources {
            guard let url = AnyURL(string: href) else { throw IosTxtPublicationError.invalidResourcePath }
            mapped[href] = IosTxtResource(data: data)
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

private final class IosTxtResource: ReadiumShared.Resource, @unchecked Sendable {
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
