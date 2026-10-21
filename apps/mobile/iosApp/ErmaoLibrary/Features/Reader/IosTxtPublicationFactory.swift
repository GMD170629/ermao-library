import Foundation
import Darwin
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
        let decoded = try IosTxtDecoder.decode(data)

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

enum IosTxtDecoder {
    static func decode(_ data: Data) throws -> String {
        if data.starts(with: [0xEF, 0xBB, 0xBF]) {
            return String(decoding: data.dropFirst(3), as: UTF8.self)
        } else if data.starts(with: [0xFF, 0xFE]) {
            return decodeUTF16(data.dropFirst(2), littleEndian: true)
        } else if data.starts(with: [0xFE, 0xFF]) {
            return decodeUTF16(data.dropFirst(2), littleEndian: false)
        }
        if let decoded = String(data: data, encoding: .utf8) {
            return decoded
        }
        return try decodeGB18030(data)
    }

    private static func decodeUTF16(_ data: Data, littleEndian: Bool) -> String {
        let bytes = Array(data)
        var units: [UInt16] = []
        for index in stride(from: 0, to: bytes.count - bytes.count % 2, by: 2) {
            let first = UInt16(bytes[index])
            let second = UInt16(bytes[index + 1])
            units.append(littleEndian ? first | second << 8 : first << 8 | second)
        }
        if bytes.count % 2 != 0 { units.append(0xFFFD) }
        return String(decoding: units, as: UTF16.self)
    }

    private static func decodeGB18030(_ data: Data) throws -> String {
        guard let converter = iconv_open("UTF-8", "GB18030"),
              converter != UnsafeMutableRawPointer(bitPattern: -1) else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        defer { iconv_close(converter) }
        var input = Array(data)
        var result: [UInt8] = []
        try input.withUnsafeMutableBytes { inputBuffer in
            var inputPointer = inputBuffer.baseAddress?.assumingMemoryBound(to: CChar.self)
            var inputLeft = inputBuffer.count
            while inputLeft > 0 {
                var output = [UInt8](repeating: 0, count: 4096)
                var outputLeft = output.count
                var conversionError: Int32 = 0
                let converted = output.withUnsafeMutableBytes { outputBuffer in
                    var outputPointer = outputBuffer.baseAddress?.assumingMemoryBound(to: CChar.self)
                    let status = iconv(converter, &inputPointer, &inputLeft, &outputPointer, &outputLeft)
                    conversionError = errno
                    return status
                }
                result.append(contentsOf: output.prefix(output.count - outputLeft))
                if converted != -1 { continue }
                if conversionError == E2BIG { continue }
                if conversionError == EILSEQ || conversionError == EINVAL {
                    result.append(contentsOf: [0xEF, 0xBF, 0xBD])
                    let consumed = conversionError == EINVAL ? inputLeft : 1
                    inputPointer = inputPointer?.advanced(by: consumed)
                    inputLeft -= consumed
                } else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(conversionError))
                }
            }
        }
        return String(decoding: result, as: UTF8.self)
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
