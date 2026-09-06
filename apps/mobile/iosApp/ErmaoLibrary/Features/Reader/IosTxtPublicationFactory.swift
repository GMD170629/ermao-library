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

        let parsed = try IosChapterCore.parseTXT(decoded)
        guard !parsed.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw IosTxtPublicationError.invalidEncoding
        }
        let normalized = try IosTxtResources.make(parsed: parsed, title: managed.displayTitle)
        var resources: [String: Data] = [:]
        var readingOrder: [Link] = []
        for resource in normalized.resources {
            resources[resource.href] = try IosPublicationSecurityPolicy.generatedChapter(resource.xhtml)
            readingOrder.append(
                Link(href: resource.href, mediaType: .xhtml, title: resource.title)
            )
        }
        resources["text/reader.css"] = Data(IosTxtResources.stylesheet.utf8)
        let toc = normalized.toc.map { entry in
            Link(
                href: entry.href,
                mediaType: .xhtml,
                title: entry.title,
                properties: Properties(["shuku:navigationKey": .string(entry.navigationKey)])
            )
        }
        let container = try IosTxtContainer(resources: resources)
        return Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:txt:\(managed.resourceID)",
                    conformsTo: [.epub],
                    title: managed.displayTitle,
                    layout: .reflowable,
                    readingProgression: .ltr
                ),
                readingOrder: readingOrder,
                resources: [Link(href: "text/reader.css", mediaType: .css)],
                tableOfContents: toc
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

private struct IosTxtResources {
    struct Resource {
        let href: String
        let title: String
        let xhtml: String
    }

    struct Toc {
        let href: String
        let title: String
        let navigationKey: String
    }

    let resources: [Resource]
    let toc: [Toc]
    static let stylesheet = """
html { color-scheme: light dark; }
body { margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere; }
h1 { font-size: 1.35em; margin: 1.5em 0 1em; }
p { margin: 0 0 1em; white-space: normal; }
"""

    static func make(parsed: IosChapterCoreResult, title: String) throws -> IosTxtResources {
        let entries = parsed.entries
        if entries.isEmpty {
            return IosTxtResources(
                resources: [Resource(href: "text/body.xhtml", title: title,
                                     xhtml: ErmaoShared.PublicKt.renderTxtXhtml(title: title, bodyText: parsed.text))],
                toc: []
            )
        }
        let bytes = Array(parsed.text.utf8)
        var output: [Resource] = []
        let firstStart = entries[0].sourceStart
        if firstStart > 0 {
            output.append(Resource(href: "text/frontmatter.xhtml", title: title,
                                   xhtml: ErmaoShared.PublicKt.renderTxtXhtml(
                                       title: title,
                                       bodyText: try Self.slice(bytes, 0, firstStart)
                                   )))
        }
        for entry in entries {
            guard let href = entry.href else {
                throw IosTxtPublicationError.invalidEncoding
            }
            output.append(Resource(
                href: href.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? href,
                title: entry.title,
                xhtml: ErmaoShared.PublicKt.renderTxtXhtml(
                    title: entry.title,
                    bodyText: try Self.slice(bytes, entry.contentStart, entry.sourceEnd)
                )
            ))
        }
        return IosTxtResources(
            resources: output,
            toc: try entries.map { entry in
                guard let href = entry.href else { throw IosTxtPublicationError.invalidEncoding }
                return Toc(href: href, title: entry.title, navigationKey: entry.key)
            }
        )
    }

    private static func slice(_ bytes: [UInt8], _ start: UInt64, _ end: UInt64) throws -> String {
        guard start <= end, end <= UInt64(bytes.count), start <= UInt64(Int.max) else {
            throw IosTxtPublicationError.invalidEncoding
        }
        let lower = Int(start)
        let upper = Int(end)
        guard let value = String(data: Data(bytes[lower ..< upper]), encoding: .utf8) else {
            throw IosTxtPublicationError.invalidEncoding
        }
        return value
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
