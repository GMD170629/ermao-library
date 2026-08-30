import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared

struct IosImageDirectoryBundle: Sendable {
    struct Member: Sendable {
        let assetID: String
        let sequenceIndex: Int
        let mimeType: String
        let sizeBytes: Int64
        let fileURL: URL
    }

    let resourceID: String
    let artifactID: String
    let totalBytes: Int64
    let members: [Member]

    init(directory: URL, expectedResourceID: String) throws {
        let values = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isDirectory == true, values.isSymbolicLink != true else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let manifestURL = directory.appendingPathComponent("bundle.json")
        let manifestValues = try manifestURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        let maximumManifestBytes = ErmaoShared.PublicKt.readerSafetyComicManifestMaxBytes()
        guard manifestValues.isRegularFile == true, manifestValues.isSymbolicLink != true,
              let manifestSize = manifestValues.fileSize, manifestSize > 0,
              Int64(manifestSize) <= maximumManifestBytes else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: manifestURL))
        let maximumPageCount = ErmaoShared.PublicKt.readerSafetyComicPageMaxCount()
        let maximumExpandedBytes = ErmaoShared.PublicKt.readerSafetyComicExpandedMaxBytes()
        var declaredTotalBytes: Int64 = 0
        for member in manifest.members {
            let (nextTotal, overflow) = declaredTotalBytes.addingReportingOverflow(member.sizeBytes)
            guard !overflow else { throw IosReaderFailure(code: .corruptFile) }
            declaredTotalBytes = nextTotal
        }
        guard manifest.contractVersion == 4,
              manifest.artifactKind == "OriginalPageSet",
              manifest.resourceId == expectedResourceID,
              !manifest.artifactId.isEmpty,
              !manifest.members.isEmpty,
              Int64(manifest.members.count) <= maximumPageCount,
              manifest.members.map(\.sequenceIndex) == Array(manifest.members.indices),
              Set(manifest.members.map(\.assetId)).count == manifest.members.count,
              declaredTotalBytes == manifest.totalBytes,
              manifest.totalBytes > 0, manifest.totalBytes <= maximumExpandedBytes else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let root = directory.standardizedFileURL.resolvingSymlinksInPath()
        let unresolvedRoot = directory.standardizedFileURL
        let maximumPageBytes = ErmaoShared.PublicKt.readerSafetyComicPageMaxBytes()
        let allowedMimeTypes = Set(ErmaoShared.PublicKt.readerSafetyAllowedComicPageMimeTypes())
        var mapped: [Member] = []
        for member in manifest.members {
            guard !member.assetId.isEmpty,
                  !member.fileName.isEmpty, !member.fileName.hasPrefix("."),
                  !member.fileName.contains("/"), !member.fileName.contains("\\") else {
                throw IosReaderFailure(code: .corruptFile)
            }
            let unresolvedFileURL = unresolvedRoot.appendingPathComponent(member.fileName).standardizedFileURL
            guard unresolvedFileURL.deletingLastPathComponent() == unresolvedRoot else {
                throw IosReaderFailure(code: .corruptFile)
            }
            guard member.sizeBytes > 0 else { throw IosReaderFailure(code: .corruptFile) }
            guard member.sizeBytes <= maximumPageBytes,
                  allowedMimeTypes.contains(member.mimeType) else {
                // Page byte and MIME findings are BLOCK_RESOURCE decisions.
                continue
            }
            let fileValues = try unresolvedFileURL.resourceValues(
                forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
            )
            guard fileValues.isRegularFile == true,
                  fileValues.isSymbolicLink != true,
                  Int64(fileValues.fileSize ?? -1) == member.sizeBytes else {
                throw IosReaderFailure(code: .corruptFile)
            }
            let fileURL = unresolvedFileURL.resolvingSymlinksInPath()
            guard fileURL.deletingLastPathComponent() == root else {
                throw IosReaderFailure(code: .corruptFile)
            }
            guard Self.detectImageMime(fileURL) == member.mimeType else { continue }
            mapped.append(Member(
                assetID: member.assetId,
                sequenceIndex: mapped.count,
                mimeType: member.mimeType,
                sizeBytes: member.sizeBytes,
                fileURL: fileURL
            ))
        }
        guard !mapped.isEmpty else { throw IosReaderFailure(code: .corruptFile) }
        resourceID = manifest.resourceId
        artifactID = manifest.artifactId
        totalBytes = manifest.totalBytes
        members = mapped
    }

    var pages: [IosCbzPage] {
        members.map { member in
            IosCbzPage(
                pageIndex: member.sequenceIndex,
                resourceHref: "pages/\(member.sequenceIndex)",
                mediaType: member.mimeType,
                width: nil,
                height: nil,
                title: String(member.sequenceIndex + 1)
            )
        }
    }

    private static func detectImageMime(_ url: URL) -> String? {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }
        guard let data = try? handle.read(upToCount: 16) else { return nil }
        let fileExtension: String?
        if data.count >= 3, data[0] == 0xFF, data[1] == 0xD8, data[2] == 0xFF {
            fileExtension = ".jpg"
        } else if data.starts(with: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) {
            fileExtension = ".png"
        } else if data.count >= 6,
                  String(data: data.prefix(6), encoding: .ascii).map({ ["GIF87a", "GIF89a"].contains($0) }) == true {
            fileExtension = ".gif"
        } else if data.count >= 12, String(data: data.prefix(4), encoding: .ascii) == "RIFF",
                  String(data: data[8 ..< 12], encoding: .ascii) == "WEBP" {
            fileExtension = ".webp"
        } else {
            fileExtension = nil
        }
        return fileExtension.flatMap {
            ErmaoShared.PublicKt.readerSafetyComicPageMimeType(extension: $0)
        }
    }

    private struct Manifest: Codable {
        let contractVersion: Int
        let artifactKind: String
        let resourceId: String
        let artifactId: String
        let totalBytes: Int64
        let members: [ManifestMember]
    }

    private struct ManifestMember: Codable {
        let assetId: String
        let sequenceIndex: Int
        let mimeType: String
        let sizeBytes: Int64
        let fileName: String
    }
}

private final class IosImageDirectoryContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let memberByHref: [String: IosImageDirectoryBundle.Member]

    init(bundle: IosImageDirectoryBundle) throws {
        memberByHref = Dictionary(uniqueKeysWithValues: bundle.members.map { ("pages/\($0.sequenceIndex)", $0) })
        entries = try Set(memberByHref.keys.map { href in
            guard let url = AnyURL(string: href) else { throw IosReaderFailure(code: .corruptFile) }
            return url
        })
    }

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
        guard let member = memberByHref[url.anyURL.string] else { return nil }
        return DataResource {
            do {
                return .success(try Data(contentsOf: member.fileURL, options: [.mappedIfSafe]))
            } catch {
                return .failure(.decoding(error))
            }
        }
    }
}

@MainActor
struct IosImageDirectoryPublicationFactory {
    func open(_ managed: IosManagedPublication, pageTitleHints: [IosCbzPage]) throws -> IosOpenedReadiumPublication {
        guard managed.sourceFormat == ErmaoShared.ReaderSourceFormat.imagedir else {
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        let bundle = try IosImageDirectoryBundle(directory: managed.fileURL, expectedResourceID: managed.resourceID)
        let pages = bundle.pages.enumerated().map { index, page in
            IosCbzPage(
                pageIndex: page.pageIndex,
                resourceHref: page.resourceHref,
                mediaType: page.mediaType,
                width: page.width,
                height: page.height,
                title: pageTitleHints.indices.contains(index) ? pageTitleHints[index].title : page.title
            )
        }
        let container = try IosImageDirectoryContainer(bundle: bundle)
        let links = pages.compactMap { page -> Link? in
            guard let mediaType = MediaType(page.mediaType) else { return nil }
            return Link(href: page.resourceHref, mediaType: mediaType, title: page.title)
        }
        guard links.count == pages.count,
              let fallbackMediaType = pages.first.flatMap({ MediaType($0.mediaType) })
        else { throw IosReaderFailure(code: .corruptFile) }
        let publication = Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:image-dir:\(managed.resourceID)",
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
        return IosOpenedReadiumPublication(publication: publication) { publication.close() }
    }
}
