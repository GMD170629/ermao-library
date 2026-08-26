import Foundation
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

/// Fail-closed metadata from the shared ZIP/RAR/RAR5 native archive core.
struct IosCbzArchiveIndex: Sendable {
    let pages: [IosCbzPage]

    init(fileURL: URL) throws {
        let core: IosArchiveCore
        do {
            core = try IosArchiveCore(fileURL: fileURL)
        } catch let failure as IosArchiveCoreFailure {
            throw Self.map(failure)
        }
        defer { core.close() }
        pages = try core.pages.map { page in
            guard let mediaType = Self.imageMediaType(page.path) else { throw IosCbzError.invalidArchive }
            return IosCbzPage(
                pageIndex: page.index,
                resourceHref: "pages/\(page.index)",
                mediaType: mediaType,
                width: nil,
                height: nil,
                title: page.path.split(separator: "/").last.map(String.init)
            )
        }
    }

    func requireCanonicalPages(_ candidate: [IosCbzPage]) throws {
        guard candidate == pages,
              candidate.enumerated().allSatisfy({ offset, page in page.pageIndex == offset })
        else { throw IosCbzError.invalidArchive }
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

    private static func map(_ failure: IosArchiveCoreFailure) -> IosCbzError {
        if failure.stableCode.contains("ENCRYPTED") { return .encrypted }
        if failure.stableCode.contains("LIMIT") || failure.stableCode.contains("MEMORY") { return .limitExceeded }
        if failure.stableCode.contains("PATH") || failure.stableCode.contains("ENTRY_TYPE") { return .unsafeEntry }
        return .invalidArchive
    }
}

@MainActor
struct IosCbzPublicationFactory {
    func open(_ managed: IosManagedPublication, pageTitleHints: [IosCbzPage]) async throws -> IosOpenedReadiumPublication {
        guard [.cbz, .zip, .cbr, .rar].contains(managed.sourceFormat) else {
            throw IosReaderFailure(code: .comicArchiveFormatUnsupported)
        }
        let core: IosArchiveCore
        do {
            core = try IosArchiveCore(fileURL: managed.fileURL)
        } catch let failure as IosArchiveCoreFailure {
            throw Self.map(failure)
        } catch {
            throw IosReaderFailure(code: .comicArchiveCorrupt)
        }
        let localPages = core.pages.map { page in
            let mediaType = Self.mediaType(for: page.path) ?? "application/octet-stream"
            return IosCbzPage(
                pageIndex: page.index,
                resourceHref: "pages/\(page.index)",
                mediaType: mediaType,
                width: nil,
                height: nil,
                title: pageTitleHints.indices.contains(page.index)
                    ? pageTitleHints[page.index].title
                    : page.path.split(separator: "/").last.map(String.init)
            )
        }
        guard !localPages.contains(where: { $0.mediaType == "application/octet-stream" }) else {
            core.close()
            throw IosReaderFailure(code: .comicArchiveCorrupt)
        }
        let container: IosArchiveComicContainer
        do {
            container = try IosArchiveComicContainer(core: core, pages: localPages)
        } catch {
            core.close()
            throw IosReaderFailure(code: .comicArchiveCorrupt)
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
            container.close()
            throw IosReaderFailure(code: .corruptFile)
        }
        let publication = Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:cbz:\(managed.resourceID)",
                    conformsTo: [.divina],
                    title: managed.displayTitle,
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
        return IosOpenedReadiumPublication(publication: publication) {
            publication.close()
            container.close()
        }
    }

    private static func mediaType(for path: String) -> String? {
        switch path.split(separator: ".").last?.lowercased() {
        case "jpg", "jpeg": "image/jpeg"
        case "png": "image/png"
        case "gif": "image/gif"
        case "webp": "image/webp"
        default: nil
        }
    }

    private static func map(_ failure: IosArchiveCoreFailure) -> IosReaderFailure {
        if failure.stableCode.contains("ENCRYPTED") {
            return IosReaderFailure(code: .comicArchiveEncrypted)
        }
        if failure.stableCode.contains("LIMIT") || failure.stableCode.contains("MEMORY") {
            return IosReaderFailure(code: .comicOutOfMemoryRisk)
        }
        return IosReaderFailure(code: .comicArchiveCorrupt)
    }
}

private final class IosArchiveComicContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let core: IosArchiveCore
    private let pageByHref: [String: IosCbzPage]

    init(core: IosArchiveCore, pages: [IosCbzPage]) throws {
        self.core = core
        pageByHref = Dictionary(uniqueKeysWithValues: pages.map { ($0.resourceHref, $0) })
        entries = try Set(pages.map { page in
            guard let url = AnyURL(string: page.resourceHref) else {
                throw IosReaderFailure(code: .comicArchiveCorrupt)
            }
            return url
        })
    }

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
        guard let page = pageByHref[url.anyURL.string] else { return nil }
        return DataResource { [core] in
            do {
                let bytes = try core.readPage(at: page.pageIndex)
                guard detectComicMediaType(bytes) == page.mediaType else {
                    return .failure(.decoding("COMIC_PAGE_MIME_MISMATCH"))
                }
                return .success(bytes)
            } catch {
                return .failure(.decoding(error))
            }
        }
    }

    func close() { core.close() }
}

private func detectComicMediaType(_ data: Data) -> String? {
    if data.count >= 3, data[0] == 0xFF, data[1] == 0xD8, data[2] == 0xFF { return "image/jpeg" }
    if data.starts(with: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) { return "image/png" }
    if data.count >= 6,
       String(data: data.prefix(6), encoding: .ascii).map({ ["GIF87a", "GIF89a"].contains($0) }) == true {
        return "image/gif"
    }
    if data.count >= 12,
       String(data: data.prefix(4), encoding: .ascii) == "RIFF",
       String(data: data[8 ..< 12], encoding: .ascii) == "WEBP" { return "image/webp" }
    return nil
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

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
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
                    identifier: "urn:shuku:comic:\(source.resourceId)",
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
