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
        guard manifestValues.isRegularFile == true, manifestValues.isSymbolicLink != true,
              let manifestSize = manifestValues.fileSize, manifestSize > 0, manifestSize <= 2 * 1_024 * 1_024 else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: manifestURL))
        guard manifest.contractVersion == 4,
              manifest.artifactKind == "OriginalPageSet",
              manifest.resourceId == expectedResourceID,
              !manifest.artifactId.isEmpty,
              !manifest.members.isEmpty,
              manifest.members.count <= 20_000,
              manifest.members.map(\.sequenceIndex) == Array(manifest.members.indices),
              Set(manifest.members.map(\.assetId)).count == manifest.members.count,
              manifest.members.reduce(Int64(0), { $0 + $1.sizeBytes }) == manifest.totalBytes,
              manifest.totalBytes > 0, manifest.totalBytes <= 4 * 1_024 * 1_024 * 1_024 else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let root = directory.standardizedFileURL.resolvingSymlinksInPath()
        let mapped = try manifest.members.map { member -> Member in
            guard !member.assetId.isEmpty,
                  member.sizeBytes > 0, member.sizeBytes <= 64 * 1_024 * 1_024,
                  ["image/jpeg", "image/png", "image/gif", "image/webp"].contains(member.mimeType),
                  !member.fileName.isEmpty, !member.fileName.hasPrefix("."),
                  !member.fileName.contains("/"), !member.fileName.contains("\\") else {
                throw IosReaderFailure(code: .corruptFile)
            }
            let fileURL = root.appendingPathComponent(member.fileName).standardizedFileURL.resolvingSymlinksInPath()
            guard fileURL.deletingLastPathComponent() == root else { throw IosReaderFailure(code: .corruptFile) }
            let fileValues = try fileURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard fileValues.isRegularFile == true, fileValues.isSymbolicLink != true,
                  Int64(fileValues.fileSize ?? -1) == member.sizeBytes,
                  Self.detectImageMime(fileURL) == member.mimeType else {
                throw IosReaderFailure(code: .corruptFile)
            }
            return Member(
                assetID: member.assetId,
                sequenceIndex: member.sequenceIndex,
                mimeType: member.mimeType,
                sizeBytes: member.sizeBytes,
                fileURL: fileURL
            )
        }
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
        if data.count >= 3, data[0] == 0xFF, data[1] == 0xD8, data[2] == 0xFF { return "image/jpeg" }
        if data.starts(with: [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) { return "image/png" }
        if data.count >= 6, String(data: data.prefix(6), encoding: .ascii).map({ ["GIF87a", "GIF89a"].contains($0) }) == true { return "image/gif" }
        if data.count >= 12, String(data: data.prefix(4), encoding: .ascii) == "RIFF",
           String(data: data[8 ..< 12], encoding: .ascii) == "WEBP" { return "image/webp" }
        return nil
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
        guard links.count == pages.count else { throw IosReaderFailure(code: .corruptFile) }
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
                positions: PerResourcePositionsService.makeFactory(fallbackMediaType: MediaType("image/*")!)
            )
        )
        return IosOpenedReadiumPublication(publication: publication) { publication.close() }
    }
}
