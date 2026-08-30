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
            throw iosArchiveReaderFailure(failure)
        }
        defer { core.close() }
        let mappedPages = core.pages.compactMap { page in
            guard let mediaType = Self.imageMediaType(page.path) else { return nil }
            return IosCbzPage(
                pageIndex: page.index,
                resourceHref: "pages/\(page.index)",
                mediaType: mediaType,
                width: nil,
                height: nil,
                title: page.path.split(separator: "/").last.map(String.init)
            )
        }
        guard !mappedPages.isEmpty else { throw IosCbzError.invalidArchive }
        pages = mappedPages
    }

    func requireCanonicalPages(_ candidate: [IosCbzPage]) throws {
        guard candidate == pages,
              candidate.enumerated().allSatisfy({ offset, page in page.pageIndex == offset })
        else { throw IosCbzError.invalidArchive }
    }

    static func imageMediaType(_ name: String) -> String? {
        guard let fileExtension = name.split(separator: ".").last?.lowercased() else { return nil }
        return ErmaoShared.PublicKt.readerSafetyComicPageMimeType(extension: ".\(fileExtension)")
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
            throw iosArchiveReaderFailure(failure)
        } catch {
            throw IosReaderFailure(code: .comicArchiveOpenFailed, underlyingError: error as NSError)
        }
        let localPages = core.pages.compactMap { page in
            guard let mediaType = IosCbzArchiveIndex.imageMediaType(page.path) else { return nil }
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
        guard !localPages.isEmpty else {
            core.close()
            throw IosReaderFailure(code: .comicArchiveCorrupt)
        }
        let container: IosArchiveComicContainer
        do {
            container = try IosArchiveComicContainer(core: core, pages: localPages)
        } catch {
            core.close()
            throw IosReaderFailure(code: .comicArchiveOpenFailed, underlyingError: error as NSError)
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
        guard let fallbackMediaType = localPages.first.flatMap({ MediaType($0.mediaType) }) else {
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
                positions: PerResourcePositionsService.makeFactory(fallbackMediaType: fallbackMediaType)
            )
        )
        return IosOpenedReadiumPublication(publication: publication) {
            publication.close()
            container.close()
        }
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
                throw IosReaderFailure(code: .invalidResponse)
            }
            return url
        })
    }

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
        guard let page = pageByHref[url.anyURL.string] else { return nil }
        return DataResource { [core] in
            do {
                let bytes = try core.readPage(at: page.pageIndex)
                return .success(bytes)
            } catch {
                return .failure(.decoding(error))
            }
        }
    }

    func close() { core.close() }
}

private final class IosRemoteComicContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>

    private let onFailure: @MainActor @Sendable (IosReaderFailure) -> Void
    private let source: ErmaoShared.RemoteComicReaderSource
    private let server: any ErmaoShared.ComicPageServerPort
    private let imageVariant: ErmaoShared.ReaderComicImageVariant
    private let pageByHref: [String: Int]

    init(
        source: ErmaoShared.RemoteComicReaderSource,
        pages: [IosCbzPage],
        server: any ErmaoShared.ComicPageServerPort,
        imageVariant: ErmaoShared.ReaderComicImageVariant,
        onFailure: @escaping @MainActor @Sendable (IosReaderFailure) -> Void
    ) throws {
        self.onFailure = onFailure
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
        return DataResource { [source, server, imageVariant, onFailure] in
            do {
                let result = try await server.read(
                    source: source,
                    pageIndex: Int32(pageIndex),
                    variant: imageVariant
                )
                guard let content = result as? ErmaoShared.ComicPageReadResultContent else {
                    let failure = result as? ErmaoShared.ComicPageReadResultFailure
                    let native = IosReaderFailure(
                        code: failure.map { IosReaderFailureCode(sharedCode: $0.readerError.code) } ?? .engineError
                    )
                    await onFailure(native)
                    return .failure(.decoding(native))
                }
                return .success(Data((0 ..< Int(content.bytes.size)).map {
                    UInt8(bitPattern: content.bytes.get(index: Int32($0)))
                }))
            } catch {
                await onFailure(IosReaderFailure(code: .engineError, underlyingError: error as NSError))
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
        imageVariant: ErmaoShared.ReaderComicImageVariant = .original,
        onFailure: @escaping @MainActor @Sendable (IosReaderFailure) -> Void
    ) throws -> IosOpenedReadiumPublication {
        let container = try IosRemoteComicContainer(
            source: source,
            pages: pages,
            server: server,
            imageVariant: imageVariant,
            onFailure: onFailure
        )
        let links = pages.compactMap { page -> Link? in
            guard let mediaType = MediaType(page.mediaType) else { return nil }
            return Link(href: page.resourceHref, mediaType: mediaType, title: String(page.pageIndex + 1))
        }
        guard links.count == pages.count,
              let fallbackMediaType = pages.first.flatMap({ MediaType($0.mediaType) })
        else {
            container.close()
            throw IosReaderFailure(code: .corruptFile)
        }
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
                positions: PerResourcePositionsService.makeFactory(fallbackMediaType: fallbackMediaType)
            )
        )
        return IosOpenedReadiumPublication(publication: publication) { publication.close() }
    }
}

private func iosArchiveReaderFailure(_ failure: IosArchiveCoreFailure) -> IosReaderFailure {
    if let safetyFailure = ErmaoShared.PublicKt.readerSafetyComicArchiveDetectorFailure(
        stableCode: failure.stableCode
    ) {
        return IosReaderFailure.safety(safetyFailure, underlyingError: failure as NSError)
    }
    let code = ErmaoShared.PublicKt.readerErrorCodeForFailure(failureCode: failure.stableCode, recoverable: false)
    return IosReaderFailure(code: IosReaderFailureCode(sharedCode: code), underlyingError: failure as NSError)
}
