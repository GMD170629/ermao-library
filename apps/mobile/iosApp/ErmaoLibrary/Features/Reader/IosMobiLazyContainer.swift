import Foundation
@preconcurrency import ReadiumShared

protocol IosMobiBookAccess: Sendable {
    func info() async throws -> IosMobiBookInfo
    func metadata(_ field: IosMobiMetadataField) async throws -> String?
    func resource(at index: Int) async throws -> IosMobiResourceInfo
    func readResource(at index: Int, offset: UInt64, length: Int) async throws -> Data
    func readingOrderResourceIndex(at position: Int) async throws -> Int
    func toc(at index: Int) async throws -> IosMobiTocInfo
    func close() async
}

extension IosMobiBook: IosMobiBookAccess {}

enum IosMobiPublicationPath {
    static func resourcePath(_ rawValue: String) -> String? {
        guard
            !rawValue.isEmpty,
            !rawValue.contains("\0"),
            !rawValue.contains("\\"),
            !rawValue.contains("?"),
            !rawValue.contains("#"),
            !hasScheme(rawValue)
        else {
            return nil
        }

        let decoded = rawValue.removingPercentEncoding ?? rawValue
        guard
            !decoded.contains("\0"),
            !decoded.contains("\\"),
            !decoded.contains("?"),
            !decoded.contains("#"),
            !hasScheme(decoded)
        else {
            return nil
        }
        var segments: [String] = []
        for segment in decoded.split(separator: "/", omittingEmptySubsequences: true) {
            switch segment {
            case ".":
                continue
            case "..":
                guard !segments.isEmpty else { return nil }
                segments.removeLast()
            default:
                segments.append(String(segment))
            }
        }
        guard !segments.isEmpty else { return nil }

        let allowed = CharacterSet.urlPathAllowed.subtracting(
            CharacterSet(charactersIn: "?#%")
        )
        let encoded = segments.compactMap {
            $0.addingPercentEncoding(withAllowedCharacters: allowed)
        }
        guard encoded.count == segments.count else { return nil }
        return encoded.joined(separator: "/")
    }

    static func reference(path: String, fragment: String?) -> String? {
        guard let path = resourcePath(path) else { return nil }
        guard let fragment, !fragment.isEmpty else { return path }
        guard !fragment.contains("\0") else { return nil }
        let allowed = CharacterSet.urlFragmentAllowed.subtracting(
            CharacterSet(charactersIn: "%")
        )
        guard let encoded = fragment.addingPercentEncoding(withAllowedCharacters: allowed) else {
            return nil
        }
        return "\(path)#\(encoded)"
    }

    private static func hasScheme(_ value: String) -> Bool {
        guard let colon = value.firstIndex(of: ":") else { return false }
        let prefix = value[..<colon]
        guard let first = prefix.first, first.isLetter else { return false }
        return prefix.allSatisfy { $0.isLetter || $0.isNumber || "+-.".contains($0) }
    }
}

struct IosMobiResourceDescriptor: Equatable, Sendable {
    let index: Int
    let href: String
    let mediaType: String
    let category: IosMobiResourceCategory
    let decodedLength: UInt64

    var requiresSecurityDecoration: Bool {
        category == .markup || category == .flow || mediaType.lowercased() == "text/css"
    }
}

actor IosMobiPublicationLifetime {
    private var book: (any IosMobiBookAccess)?

    init(book: any IosMobiBookAccess) {
        self.book = book
    }

    deinit {
        let remainingBook = book
        if let remainingBook {
            Task { await remainingBook.close() }
        }
    }

    func readResource(at index: Int, offset: UInt64, length: Int) async throws -> Data {
        guard let book else { throw IosMobiPublicationError.closed }
        return try await book.readResource(at: index, offset: offset, length: length)
    }

    func close() async {
        guard let book else { return }
        self.book = nil
        await book.close()
    }
}

final class IosMobiLazyContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>

    private let lifetime: IosMobiPublicationLifetime
    private let resources: [String: IosMobiLazyResource]

    init(
        descriptors: [IosMobiResourceDescriptor],
        lifetime: IosMobiPublicationLifetime,
        securityAdapter: IosPublicationSecurityAdapter
    ) throws {
        var resources: [String: IosMobiLazyResource] = [:]
        var entries: Set<AnyURL> = []
        for descriptor in descriptors {
            guard let url = AnyURL(string: descriptor.href) else {
                throw IosMobiPublicationError.invalidResourcePath(descriptor.href)
            }
            guard resources[descriptor.href] == nil else {
                throw IosMobiPublicationError.duplicateResourcePath(descriptor.href)
            }
            resources[descriptor.href] = IosMobiLazyResource(
                descriptor: descriptor,
                lifetime: lifetime,
                securityAdapter: securityAdapter
            )
            entries.insert(url)
        }
        self.resources = resources
        self.entries = entries
        self.lifetime = lifetime
    }

    subscript(url: any URLConvertible) -> Resource? {
        guard let path = IosMobiPublicationPath.resourcePath(
            url.anyURL.removingQuery().removingFragment().string
        ) else {
            return nil
        }
        return resources[path]
    }

    func close() {
        Task { await lifetime.close() }
    }

}

final class IosMobiLazyResource: Resource, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil

    private let descriptor: IosMobiResourceDescriptor
    private let lifetime: IosMobiPublicationLifetime
    private let securityAdapter: IosPublicationSecurityAdapter

    init(
        descriptor: IosMobiResourceDescriptor,
        lifetime: IosMobiPublicationLifetime,
        securityAdapter: IosPublicationSecurityAdapter
    ) {
        self.descriptor = descriptor
        self.lifetime = lifetime
        self.securityAdapter = securityAdapter
    }

    func estimatedLength() async -> ReadResult<UInt64?> {
        // This is intentionally only a hint. Head decoration can change length, but
        // calculating it here would materialize every chapter when positions are built.
        return .success(descriptor.decodedLength)
    }

    func properties() async -> ReadResult<ResourceProperties> {
        .success(ResourceProperties())
    }

    func stream(
        range: Range<UInt64>?,
        consume: @escaping (Data) -> Void
    ) async -> ReadResult<Void> {
        if descriptor.requiresSecurityDecoration {
            return await decoratedData().map { data in
                let length = UInt64(data.count)
                let selected = Self.clamped(range, to: length)
                if !selected.isEmpty {
                    consume(data[Int(selected.lowerBound) ..< Int(selected.upperBound)])
                }
            }
        }

        return await streamRaw(range: range, consume: consume)
    }

    private func decoratedData() async -> ReadResult<Data> {
        var raw = Data()
        let streamed = await streamRaw(range: nil) { raw.append($0) }
        return streamed.flatMap { _ -> ReadResult<Data> in
            do {
                return .success(
                    try securityAdapter.decorate(data: raw, mediaType: descriptor.mediaType)
                )
            } catch {
                return .failure(.decoding("Unsafe or invalid MOBI text resource", cause: error))
            }
        }
    }

    private func streamRaw(
        range: Range<UInt64>?,
        consume: @escaping (Data) -> Void
    ) async -> ReadResult<Void> {
        let selected = Self.clamped(range, to: descriptor.decodedLength)
        var offset = selected.lowerBound
        do {
            while offset < selected.upperBound {
                let requested = Int(
                    min(
                        UInt64(IosMobiBook.maximumReadBytes),
                        selected.upperBound - offset
                    )
                )
                let chunk = try await lifetime.readResource(
                    at: descriptor.index,
                    offset: offset,
                    length: requested
                )
                guard !chunk.isEmpty, chunk.count <= requested else {
                    return .failure(.decoding("Unexpected MOBI resource short read"))
                }
                consume(chunk)
                offset += UInt64(chunk.count)
            }
            return .success(())
        } catch {
            return .failure(.decoding("Unable to read MOBI resource", cause: error))
        }
    }

    private static func clamped(_ range: Range<UInt64>?, to length: UInt64) -> Range<UInt64> {
        guard let range else { return 0 ..< length }
        let lower = min(range.lowerBound, length)
        let upper = min(max(range.upperBound, lower), length)
        return lower ..< upper
    }
}
