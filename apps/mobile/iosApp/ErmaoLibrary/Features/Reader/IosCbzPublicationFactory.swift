import Foundation
import ImageIO
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared

struct IosCbzPage: Equatable, Sendable {
    let pageIndex: Int
    let resourceHref: String
    let mediaType: String
    let width: Int?
    let height: Int?
    let title: String?

    init(
        pageIndex: Int,
        resourceHref: String,
        mediaType: String,
        width: Int?,
        height: Int?,
        title: String? = nil
    ) {
        self.pageIndex = pageIndex
        self.resourceHref = resourceHref
        self.mediaType = mediaType
        self.width = width
        self.height = height
        self.title = title
    }
}

enum IosCbzError: Error, Equatable, Sendable {
    case invalidArchive
    case encrypted
    case unsafeEntry
    case limitExceeded
}

/// A fail-closed ZIP central-directory inspection used before Readium receives a CBZ.
/// ZIP64 and multi-disk archives are deliberately rejected for the bounded P2 reader.
struct IosCbzArchiveIndex: Sendable {
    static let maximumEntries = 10_000
    static let maximumEntryBytes: UInt64 = 256 * 1_024 * 1_024
    static let maximumExpandedBytes: UInt64 = 4 * 1_024 * 1_024 * 1_024
    static let maximumCompressionRatio: UInt64 = 1_000

    let pages: [IosCbzPage]

    init(fileURL: URL) throws {
        let values = try fileURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              let fileSize = values.fileSize, fileSize >= 22
        else { throw IosCbzError.invalidArchive }

        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }
        let tailLength = min(fileSize, 65_557)
        try handle.seek(toOffset: UInt64(fileSize - tailLength))
        let tail = try handle.read(upToCount: tailLength) ?? Data()
        guard let eocd = tail.lastOffset(ofLittleEndian: 0x0605_4B50), eocd + 22 <= tail.count else {
            throw IosCbzError.invalidArchive
        }
        let disk = try tail.u16(at: eocd + 4)
        let directoryDisk = try tail.u16(at: eocd + 6)
        let entriesOnDisk = try tail.u16(at: eocd + 8)
        let entryCount = try tail.u16(at: eocd + 10)
        let directorySize = try tail.u32(at: eocd + 12)
        let directoryOffset = try tail.u32(at: eocd + 16)
        let commentLength = try tail.u16(at: eocd + 20)
        guard disk == 0, directoryDisk == 0, entriesOnDisk == entryCount,
              entryCount > 0, entryCount <= Self.maximumEntries,
              entryCount != Int(UInt16.max), directorySize != UInt32.max, directoryOffset != UInt32.max,
              eocd + 22 + commentLength == tail.count,
              UInt64(directoryOffset) + UInt64(directorySize) <= UInt64(fileSize)
        else { throw IosCbzError.invalidArchive }

        try handle.seek(toOffset: UInt64(directoryOffset))
        let directory = try handle.read(upToCount: Int(directorySize)) ?? Data()
        guard directory.count == Int(directorySize) else { throw IosCbzError.invalidArchive }

        var cursor = 0
        var expandedBytes: UInt64 = 0
        var seen = Set<String>()
        var images: [(String, String)] = []
        for _ in 0 ..< entryCount {
            guard try directory.u32(at: cursor) == 0x0201_4B50, cursor + 46 <= directory.count else {
                throw IosCbzError.invalidArchive
            }
            let madeBy = try directory.u16(at: cursor + 4)
            let flags = try directory.u16(at: cursor + 8)
            let method = try directory.u16(at: cursor + 10)
            let compressed = UInt64(try directory.u32(at: cursor + 20))
            let expanded = UInt64(try directory.u32(at: cursor + 24))
            let nameLength = try directory.u16(at: cursor + 28)
            let extraLength = try directory.u16(at: cursor + 30)
            let entryCommentLength = try directory.u16(at: cursor + 32)
            let diskStart = try directory.u16(at: cursor + 34)
            let externalAttributes = try directory.u32(at: cursor + 38)
            let localOffset = try directory.u32(at: cursor + 42)
            let end = cursor + 46 + nameLength + extraLength + entryCommentLength
            guard end <= directory.count, nameLength > 0, nameLength <= 8_192,
                  diskStart == 0, method == 0 || method == 8,
                  compressed != UInt64(UInt32.max), expanded != UInt64(UInt32.max),
                  localOffset != UInt32.max
            else { throw IosCbzError.invalidArchive }
            guard flags & 0x0001 == 0 else { throw IosCbzError.encrypted }

            let nameData = directory.subdata(in: cursor + 46 ..< cursor + 46 + nameLength)
            let name: String?
            if flags & 0x0800 != 0 {
                name = String(data: nameData, encoding: .utf8)
            } else if nameData.allSatisfy({ $0 < 0x80 }) {
                name = String(data: nameData, encoding: .ascii)
            } else {
                name = nil
            }
            guard let name, Self.isSafePath(name), seen.insert(name.lowercased()).inserted else {
                throw IosCbzError.unsafeEntry
            }
            let unixMode = (externalAttributes >> 16) & 0xFFFF
            guard (madeBy >> 8) != 3 || (unixMode & 0xF000) != 0xA000 else {
                throw IosCbzError.unsafeEntry
            }
            let isDirectory = name.hasSuffix("/") || externalAttributes & 0x10 != 0
            if !isDirectory {
                guard expanded <= Self.maximumEntryBytes else { throw IosCbzError.limitExceeded }
                expandedBytes += expanded
                guard expandedBytes <= Self.maximumExpandedBytes,
                      expanded == 0 || (compressed > 0 && expanded / compressed <= Self.maximumCompressionRatio)
                else { throw IosCbzError.limitExceeded }
                if let mediaType = Self.imageMediaType(name) { images.append((name, mediaType)) }
            }
            guard try Self.localHeaderMatches(
                handle: handle,
                fileSize: UInt64(fileSize),
                offset: UInt64(localOffset),
                expectedFlags: flags,
                expectedMethod: method,
                expectedName: nameData,
                compressedSize: compressed
            ) else { throw IosCbzError.invalidArchive }
            cursor = end
        }
        guard cursor == directory.count, !images.isEmpty else { throw IosCbzError.invalidArchive }
        images.sort { $0.0.localizedStandardCompare($1.0) == .orderedAscending }
        pages = images.enumerated().map {
            IosCbzPage(pageIndex: $0.offset, resourceHref: $0.element.0, mediaType: $0.element.1, width: nil, height: nil)
        }
    }

    private static func isSafePath(_ value: String) -> Bool {
        guard !value.isEmpty, !value.hasPrefix("/"), !value.contains("\\"), !value.contains("\0"),
              value.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) })
        else { return false }
        let components = value.split(separator: "/", omittingEmptySubsequences: false)
        return components.enumerated().allSatisfy { index, part in
            if index == components.count - 1, part.isEmpty, value.hasSuffix("/") { return true }
            return !part.isEmpty && part != "." && part != ".." && !part.contains(":")
        }
    }

    private static func imageMediaType(_ name: String) -> String? {
        switch name.split(separator: ".").last?.lowercased() {
        case "jpg", "jpeg": "image/jpeg"
        case "png": "image/png"
        case "gif": "image/gif"
        case "webp": "image/webp"
        default: nil
        }
    }

    private static func localHeaderMatches(
        handle: FileHandle,
        fileSize: UInt64,
        offset: UInt64,
        expectedFlags: Int,
        expectedMethod: Int,
        expectedName: Data,
        compressedSize: UInt64
    ) throws -> Bool {
        guard offset + 30 <= fileSize else { return false }
        try handle.seek(toOffset: offset)
        let header = try handle.read(upToCount: 30) ?? Data()
        guard header.count == 30, try header.u32(at: 0) == 0x0403_4B50,
              try header.u16(at: 6) == expectedFlags,
              try header.u16(at: 8) == expectedMethod
        else { return false }
        let nameLength = try header.u16(at: 26)
        let extraLength = try header.u16(at: 28)
        guard nameLength == expectedName.count,
              offset + UInt64(30 + nameLength + extraLength) + compressedSize <= fileSize
        else { return false }
        let localName = try handle.read(upToCount: nameLength) ?? Data()
        return localName == expectedName
    }
}

@MainActor
struct IosCbzPublicationFactory {
    private let assetRetriever = AssetRetriever(httpClient: DefaultHTTPClient(ephemeral: true))

    func open(_ managed: IosManagedPublication, pageTitleHints: [IosCbzPage]) async throws -> IosOpenedReadiumPublication {
        guard (managed.sourceFormat == .cbz || managed.sourceFormat == .zip),
              let fileURL = FileURL(url: managed.fileURL)
        else { throw IosReaderFailure(code: .corruptFile) }
        let localIndex: IosCbzArchiveIndex
        do {
            localIndex = try IosCbzArchiveIndex(fileURL: managed.fileURL)
        } catch IosCbzError.limitExceeded {
            throw IosReaderFailure(code: .comicOutOfMemoryRisk)
        } catch IosCbzError.encrypted {
            throw IosReaderFailure(code: .comicArchiveEncrypted)
        } catch {
            throw IosReaderFailure(code: .comicArchiveCorrupt)
        }
        let localPages = localIndex.pages.enumerated().map { index, page in
            IosCbzPage(
                pageIndex: page.pageIndex,
                resourceHref: page.resourceHref,
                mediaType: page.mediaType,
                width: page.width,
                height: page.height,
                title: pageTitleHints.indices.contains(index) ? pageTitleHints[index].title : nil
            )
        }
        let asset: Asset
        switch await assetRetriever.retrieve(url: fileURL, mediaType: .cbz) {
        case let .success(value): asset = value
        case .failure: throw IosReaderFailure(code: .corruptFile)
        }
        guard case let .container(containerAsset) = asset else {
            asset.close()
            throw IosReaderFailure(code: .corruptFile)
        }
        for page in localPages {
            guard let href = AnyURL(string: page.resourceHref),
                  let resource = containerAsset.container[href]
            else {
                asset.close()
                throw IosReaderFailure(code: .corruptFile)
            }
            let header: Data
            switch await resource.read(range: 0 ..< 65_536) {
            case let .success(value): header = value
            case .failure:
                asset.close()
                throw IosReaderFailure(code: .corruptFile)
            }
            guard Self.detectMediaType(header) == page.mediaType else {
                asset.close()
                throw IosReaderFailure(code: .corruptFile)
            }
            if page.width != nil || page.height != nil {
                guard let source = CGImageSourceCreateWithData(header as CFData, nil),
                      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                      let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
                      let height = properties[kCGImagePropertyPixelHeight] as? NSNumber,
                      page.width == nil || page.width == width.intValue,
                      page.height == nil || page.height == height.intValue
                else {
                    asset.close()
                    throw IosReaderFailure(code: .corruptFile)
                }
            }
        }
        let links = localPages.compactMap { page -> Link? in
            guard let mediaType = MediaType(page.mediaType) else { return nil }
            return Link(
                href: page.resourceHref,
                mediaType: mediaType,
                title: page.title ?? String(page.pageIndex + 1)
            )
        }
        guard links.count == localPages.count else {
            asset.close()
            throw IosReaderFailure(code: .corruptFile)
        }
        let publication = Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:cbz:\(managed.sourceID)",
                    conformsTo: [.divina],
                    title: managed.displayTitle,
                    layout: .fixed,
                    readingProgression: .ltr,
                    numberOfPages: links.count
                ),
                readingOrder: links,
                tableOfContents: links
            ),
            container: containerAsset.container,
            servicesBuilder: PublicationServicesBuilder(
                positions: PerResourcePositionsService.makeFactory(fallbackMediaType: MediaType("image/*")!)
            )
        )
        return IosOpenedReadiumPublication(publication: publication) { publication.close() }
    }

    private static func detectMediaType(_ data: Data) -> String? {
        if data.count >= 3, data[0] == 0xFF, data[1] == 0xD8, data[2] == 0xFF { return "image/jpeg" }
        if data.starts(with: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) { return "image/png" }
        if data.count >= 6, String(data: data.prefix(6), encoding: .ascii).map({ ["GIF87a", "GIF89a"].contains($0) }) == true {
            return "image/gif"
        }
        if data.count >= 12,
           String(data: data.prefix(4), encoding: .ascii) == "RIFF",
           String(data: data[8 ..< 12], encoding: .ascii) == "WEBP" { return "image/webp" }
        return nil
    }
}

private final class IosRemoteComicContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>

    private let source: ErmaoShared.RemoteComicReaderSource
    private let server: any ErmaoShared.ComicPageServerPort
    private let imageVariant: ErmaoShared.ReaderComicImageVariant
    private let pageByHref: [String: Int]

    init(
        source: ErmaoShared.RemoteComicReaderSource,
        pages: [IosCbzPage],
        server: any ErmaoShared.ComicPageServerPort,
        imageVariant: ErmaoShared.ReaderComicImageVariant
    ) throws {
        self.source = source
        self.server = server
        self.imageVariant = imageVariant
        pageByHref = Dictionary(uniqueKeysWithValues: pages.map { ($0.resourceHref, $0.pageIndex) })
        entries = try Set(pages.map {
            guard let url = AnyURL(string: $0.resourceHref) else {
                throw IosReaderFailure(code: .corruptFile)
            }
            return url
        })
    }

    subscript(url: any URLConvertible) -> (any Resource)? {
        let href = url.anyURL.string
        guard let pageIndex = pageByHref[href] else { return nil }
        return DataResource { [source, server, imageVariant] in
            do {
                let result = try await server.read(
                    source: source,
                    pageIndex: Int32(pageIndex),
                    variant: imageVariant
                )
                guard let content = result as? ErmaoShared.ComicPageReadResultContent else {
                    let failure = result as? ErmaoShared.ComicPageReadResultFailure
                    return .failure(.decoding(failure?.code ?? "COMIC_PAGE_LOAD_FAILED"))
                }
                return .success(Data((0 ..< Int(content.bytes.size)).map {
                    UInt8(bitPattern: content.bytes.get(index: Int32($0)))
                }))
            } catch {
                return .failure(.decoding(error))
            }
        }
    }
}

@MainActor
struct IosRemoteComicPublicationFactory {
    func open(
        source: ErmaoShared.RemoteComicReaderSource,
        pages: [IosCbzPage],
        server: any ErmaoShared.ComicPageServerPort,
        imageVariant: ErmaoShared.ReaderComicImageVariant = .original
    ) throws -> IosOpenedReadiumPublication {
        let container = try IosRemoteComicContainer(
            source: source,
            pages: pages,
            server: server,
            imageVariant: imageVariant
        )
        let links = pages.compactMap { page -> Link? in
            guard let mediaType = MediaType(page.mediaType) else { return nil }
            return Link(href: page.resourceHref, mediaType: mediaType, title: String(page.pageIndex + 1))
        }
        guard links.count == pages.count else { throw IosReaderFailure(code: .corruptFile) }
        let publication = Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:comic:\(source.volumeId):\(source.protocolFingerprint)",
                    conformsTo: [.divina],
                    title: source.displayTitle,
                    layout: .fixed,
                    readingProgression: .ltr,
                    numberOfPages: links.count
                ),
                readingOrder: links,
                tableOfContents: links
            ),
            container: container,
            servicesBuilder: PublicationServicesBuilder(
                positions: PerResourcePositionsService.makeFactory(fallbackMediaType: MediaType("image/*")!)
            )
        )
        return IosOpenedReadiumPublication(publication: publication) { publication.close() }
    }
}

private extension Data {
    func u16(at offset: Int) throws -> Int {
        guard offset >= 0, offset + 2 <= count else { throw IosCbzError.invalidArchive }
        return Int(self[offset]) | Int(self[offset + 1]) << 8
    }

    func u32(at offset: Int) throws -> UInt32 {
        guard offset >= 0, offset + 4 <= count else { throw IosCbzError.invalidArchive }
        return UInt32(self[offset]) | UInt32(self[offset + 1]) << 8 |
            UInt32(self[offset + 2]) << 16 | UInt32(self[offset + 3]) << 24
    }

    func lastOffset(ofLittleEndian signature: UInt32) -> Int? {
        guard count >= 4 else { return nil }
        for offset in stride(from: count - 4, through: 0, by: -1) {
            if (try? u32(at: offset)) == signature { return offset }
        }
        return nil
    }
}
