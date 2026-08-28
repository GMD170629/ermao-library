import CryptoKit
import Foundation
@preconcurrency import ErmaoShared

struct IosManagedPublication: Sendable, Equatable {
    let resourceID: String
    let displayTitle: String
    let fileURL: URL
    let byteCount: Int64
    let bookID: String?
    let assetID: String?
    let namespace: String?
    let sourceFormat: ErmaoShared.ReaderSourceFormat
}

actor IosManagedPublicationStore {
    static let parserVersion = "epub-package:1"
    static let normalizationVersion = "shuku-epub-locator-dom-v2"
    static let maximumPublicationBytes = ErmaoShared.ReaderAdmission.shared.maximumPublicationBytes

    private var completedPublication: IosManagedPublication?
    private let root: URL
    private let fileManager: FileManager

    init(root: URL? = nil, fileManager: FileManager = .default) throws {
        self.fileManager = fileManager
        if let root {
            self.root = root
        } else {
            let support = try fileManager.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            self.root = support.appendingPathComponent("Reader/Publications", isDirectory: true)
        }
        try fileManager.createDirectory(
            at: self.root,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
    }

    /// Metadata proves ownership. Ambiguous files and local imports remain untouched.
    func removeAutomaticReplica(resourceID: String, assetID: String, namespace: String) throws {
        let caches = try fileManager.url(for: .cachesDirectory, in: .userDomainMask, appropriateFor: nil, create: false)
        let obsoleteRanges = caches.appendingPathComponent("reader/pdf-range-v1", isDirectory: true)
        if fileManager.fileExists(atPath: obsoleteRanges.path) {
            guard obsoleteRanges.resolvingSymlinksInPath().path.hasPrefix(caches.resolvingSymlinksInPath().path + "/") else {
                throw IosReaderFailure(code: .persistenceFailed)
            }
            try fileManager.removeItem(at: obsoleteRanges)
        }
        let key = opaqueKey(resourceID)
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        try requireContained(metadataURL)
        guard fileManager.fileExists(atPath: metadataURL.path) else { return }
        let metadata = try JSONDecoder().decode(Metadata.self, from: Data(contentsOf: metadataURL))
        guard metadata.resourceID == resourceID, metadata.assetID == assetID,
              metadata.namespace == namespace else { return }
        let candidates = try fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        for candidate in candidates where candidate.lastPathComponent.hasPrefix(".\(key).") && candidate.pathExtension == "partial" {
            try requireContained(candidate)
            try fileManager.removeItem(at: candidate)
        }
        try remove(resourceID: resourceID, namespace: namespace)
    }

    func importEPUB(
        from sourceURL: URL,
        resourceID: String,
        displayTitle: String,
        bookID: String? = nil,
        namespace: String? = nil,
    ) async throws -> IosManagedPublication {
        try await importPublication(
            from: sourceURL,
            resourceID: resourceID,
            displayTitle: displayTitle,
            sourceFormat: .epub,
            bookID: bookID,
            namespace: namespace,
            parserVersion: Self.parserVersion,
            normalizationVersion: Self.normalizationVersion
        )
    }

    func importPublication(
        from sourceURL: URL,
        resourceID: String,
        displayTitle: String,
        sourceFormat: ErmaoShared.ReaderSourceFormat,
        bookID: String? = nil,
        assetID: String? = nil,
        namespace: String? = nil,
        parserVersion: String,
        normalizationVersion: String
    ) async throws -> IosManagedPublication {
        if sourceFormat == .imagedir {
            return try importOriginalPageSet(
                from: sourceURL,
                resourceID: resourceID,
                displayTitle: displayTitle,
                bookID: bookID,
                assetID: assetID,
                namespace: namespace
            )
        }
        guard !resourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !displayTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              Self.acceptsSourceExtension(sourceURL.pathExtension, for: sourceFormat),
              !parserVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !normalizationVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        let sourceValues = try sourceURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard sourceValues.isRegularFile == true, sourceValues.isSymbolicLink != true else {
            throw IosReaderFailure(code: .corruptFile)
        }
        if Int64(sourceValues.fileSize ?? 0) > Self.maximumPublicationBytes {
            throw IosReaderFailure(code: .publicationTooLarge)
        }

        let key = opaqueKey(resourceID)
        let destination = root.appendingPathComponent(key)
            .appendingPathExtension(Self.pathExtension(for: sourceFormat))
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        let staging = root.appendingPathComponent(".\(key).\(UUID().uuidString).partial")
        try requireContained(destination)
        try requireContained(metadataURL)
        try requireContained(staging)
        fileManager.createFile(
            atPath: staging.path,
            contents: nil,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        defer { try? fileManager.removeItem(at: staging) }

        let input = try FileHandle(forReadingFrom: sourceURL)
        let output = try FileHandle(forWritingTo: staging)
        defer {
            try? input.close()
            try? output.close()
        }
        var byteCount: Int64 = 0
        while let chunk = try input.read(upToCount: 1_048_576), !chunk.isEmpty {
            byteCount += Int64(chunk.count)
            guard byteCount <= Self.maximumPublicationBytes else {
                throw IosReaderFailure(code: .publicationTooLarge)
            }
            try output.write(contentsOf: chunk)
        }
        try output.synchronize()
        let metadata = Metadata(
            resourceID: resourceID,
            displayTitle: displayTitle,
            byteCount: byteCount,
            bookID: bookID,
            assetID: assetID,
            namespace: namespace,
            sourceFormat: sourceFormat.wireValue
        )
        try installPublication(
            staging: staging,
            destination: destination,
            metadata: try JSONEncoder().encode(metadata),
            metadataURL: metadataURL
        )
        return IosManagedPublication(
            resourceID: resourceID,
            displayTitle: displayTitle,
            fileURL: destination,
            byteCount: byteCount,
            bookID: bookID,
            assetID: assetID,
            namespace: namespace,
            sourceFormat: sourceFormat
        )
    }

    private func importOriginalPageSet(
        from sourceURL: URL,
        resourceID: String,
        displayTitle: String,
        bookID: String?,
        assetID: String?,
        namespace: String?
    ) throws -> IosManagedPublication {
        guard !resourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !displayTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        let sourceBundle = try IosImageDirectoryBundle(directory: sourceURL, expectedResourceID: resourceID)
        let key = opaqueKey(resourceID)
        let destination = root.appendingPathComponent(key).appendingPathExtension("image_dir")
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        let staging = root.appendingPathComponent(".\(key).\(UUID().uuidString).bundle.partial", isDirectory: true)
        try requireContained(destination)
        try requireContained(metadataURL)
        try requireContained(staging)
        defer { try? fileManager.removeItem(at: staging) }
        try fileManager.copyItem(at: sourceURL, to: staging)
        let stagedBundle = try IosImageDirectoryBundle(directory: staging, expectedResourceID: resourceID)
        guard stagedBundle.totalBytes == sourceBundle.totalBytes,
              stagedBundle.artifactID == sourceBundle.artifactID else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let metadata = Metadata(
            resourceID: resourceID,
            displayTitle: displayTitle,
            byteCount: stagedBundle.totalBytes,
            bookID: bookID,
            assetID: assetID,
            namespace: namespace,
            sourceFormat: ErmaoShared.ReaderSourceFormat.imagedir.wireValue
        )
        try installPublication(
            staging: staging,
            destination: destination,
            metadata: try JSONEncoder().encode(metadata),
            metadataURL: metadataURL
        )
        return IosManagedPublication(
            resourceID: resourceID,
            displayTitle: displayTitle,
            fileURL: destination,
            byteCount: stagedBundle.totalBytes,
            bookID: bookID,
            assetID: assetID,
            namespace: namespace,
            sourceFormat: .imagedir
        )
    }

    /// Binds the verified Downloads file without copying or publishing another original.
    func bindCompleted(_ publication: IosManagedPublication) {
        completedPublication = publication
    }

    func resolve(resourceID: String, namespace: String? = nil) throws -> IosManagedPublication {
        if let completedPublication, completedPublication.resourceID == resourceID,
           namespace == nil || completedPublication.namespace == namespace { return completedPublication }
        let key = opaqueKey(resourceID)
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        try requireContained(metadataURL)
        let metadataValues = try metadataURL.resourceValues(
            forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
        )
        guard metadataValues.isRegularFile == true, metadataValues.isSymbolicLink != true,
              (metadataValues.fileSize ?? 0) <= 16_384
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let metadata = try JSONDecoder().decode(Metadata.self, from: Data(contentsOf: metadataURL))
        guard metadata.resourceID == resourceID else {
            throw IosReaderFailure(code: .corruptFile)
        }
        guard namespace == nil || metadata.namespace == namespace else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        guard let sourceFormat = Self.sourceFormat(metadata.sourceFormat) else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let publicationURL = root.appendingPathComponent(key)
            .appendingPathExtension(Self.pathExtension(for: sourceFormat))
        try requireContained(publicationURL)
        let byteCount: Int64
        if sourceFormat == .imagedir {
            byteCount = try IosImageDirectoryBundle(
                directory: publicationURL,
                expectedResourceID: resourceID
            ).totalBytes
        } else {
            let values = try publicationURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true,
                  Int64(values.fileSize ?? -1) >= 0,
                  Int64(values.fileSize ?? -1) <= Self.maximumPublicationBytes
            else {
                throw IosReaderFailure(code: .corruptFile)
            }
            byteCount = Int64(values.fileSize ?? 0)
        }
        return IosManagedPublication(
            resourceID: metadata.resourceID,
            displayTitle: metadata.displayTitle,
            fileURL: publicationURL,
            byteCount: byteCount,
            bookID: metadata.bookID,
            assetID: metadata.assetID,
            namespace: metadata.namespace,
            sourceFormat: sourceFormat
        )
    }

    func remove(resourceID: String, namespace: String? = nil) throws {
        let key = opaqueKey(resourceID)
        if let namespace {
            let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
            if let data = try? Data(contentsOf: metadataURL),
               let metadata = try? JSONDecoder().decode(Metadata.self, from: data),
               metadata.namespace != namespace {
                return
            }
        }
        for url in [
            root.appendingPathComponent(key).appendingPathExtension("epub"),
            root.appendingPathComponent(key).appendingPathExtension("mobi"),
            root.appendingPathComponent(key).appendingPathExtension("azw"),
            root.appendingPathComponent(key).appendingPathExtension("azw3"),
            root.appendingPathComponent(key).appendingPathExtension("prc"),
            root.appendingPathComponent(key).appendingPathExtension("cbz"),
            root.appendingPathComponent(key).appendingPathExtension("zip"),
            root.appendingPathComponent(key).appendingPathExtension("cbr"),
            root.appendingPathComponent(key).appendingPathExtension("rar"),
            root.appendingPathComponent(key).appendingPathExtension("image_dir"),
            root.appendingPathComponent(key).appendingPathExtension("pdf"),
            root.appendingPathComponent(key).appendingPathExtension("json"),
        ] where fileManager.fileExists(atPath: url.path) {
            try requireContained(url)
            try fileManager.removeItem(at: url)
        }
    }

    /// Remove only publications attributed to one authenticated namespace.
    /// Metadata without a namespace is deliberately retained because it cannot
    /// be assigned safely to the account being logged out.
    func removeNamespace(_ namespace: String) throws {
        guard !namespace.isEmpty,
              fileManager.fileExists(atPath: root.path) else { return }
        let metadataFiles = try fileManager.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ).filter { $0.pathExtension == "json" }
        for metadataURL in metadataFiles {
            guard let data = try? Data(contentsOf: metadataURL),
                  let metadata = try? JSONDecoder().decode(Metadata.self, from: data),
                  metadata.namespace == namespace else { continue }
            try remove(resourceID: metadata.resourceID, namespace: namespace)
        }
    }

    private func install(staging: URL, destination: URL) throws {
        if fileManager.fileExists(atPath: destination.path) {
            _ = try fileManager.replaceItemAt(destination, withItemAt: staging)
        } else {
            try fileManager.moveItem(at: staging, to: destination)
        }
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: destination.path
        )
    }

    private func installPublication(
        staging: URL,
        destination: URL,
        metadata: Data,
        metadataURL: URL
    ) throws {
        let transactionID = UUID().uuidString
        let metadataStaging = root.appendingPathComponent(".\(transactionID).metadata.partial")
        let contentBackup = root.appendingPathComponent(".\(transactionID).content.backup")
        let metadataBackup = root.appendingPathComponent(".\(transactionID).metadata.backup")
        for url in [metadataStaging, contentBackup, metadataBackup] { try requireContained(url) }
        try metadata.write(
            to: metadataStaging,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
        let hadContent = fileManager.fileExists(atPath: destination.path)
        let hadMetadata = fileManager.fileExists(atPath: metadataURL.path)
        if hadContent { try fileManager.copyItem(at: destination, to: contentBackup) }
        if hadMetadata { try fileManager.copyItem(at: metadataURL, to: metadataBackup) }
        defer {
            try? fileManager.removeItem(at: metadataStaging)
            try? fileManager.removeItem(at: contentBackup)
            try? fileManager.removeItem(at: metadataBackup)
        }
        do {
            try install(staging: staging, destination: destination)
            try install(staging: metadataStaging, destination: metadataURL)
        } catch {
            try? fileManager.removeItem(at: destination)
            try? fileManager.removeItem(at: metadataURL)
            if hadContent { try? fileManager.moveItem(at: contentBackup, to: destination) }
            if hadMetadata { try? fileManager.moveItem(at: metadataBackup, to: metadataURL) }
            throw IosReaderFailure(code: .persistenceFailed)
        }
    }

    private func opaqueKey(_ resourceID: String) -> String {
        SHA256.hash(data: Data(resourceID.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func requireContained(_ url: URL) throws {
        let resolvedRoot = root.standardizedFileURL.resolvingSymlinksInPath()
        let rootPath = resolvedRoot.path + "/"
        let standardizedURL = url.standardizedFileURL
        let resolvedParent = standardizedURL.deletingLastPathComponent().resolvingSymlinksInPath()
        let path = resolvedParent.appendingPathComponent(standardizedURL.lastPathComponent).path
        guard path.hasPrefix(rootPath) else { throw IosReaderFailure(code: .corruptFile) }
    }

    private struct Metadata: Codable {
        let resourceID: String
        let displayTitle: String
        let byteCount: Int64
        let bookID: String?
        let assetID: String?
        let namespace: String?
        let sourceFormat: String
    }

    private static func pathExtension(for sourceFormat: ErmaoShared.ReaderSourceFormat) -> String {
        sourceFormat.wireValue
    }

    private static func acceptsSourceExtension(
        _ pathExtension: String,
        for sourceFormat: ErmaoShared.ReaderSourceFormat
    ) -> Bool {
        pathExtension.lowercased() == Self.pathExtension(for: sourceFormat)
    }

    static func sourceFormat(_ wireValue: String) -> ErmaoShared.ReaderSourceFormat? {
        switch wireValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "epub": .epub
        case "mobi": .mobi
        case "azw": .azw
        case "azw3": .azw3
        case "prc": .prc
        case "txt": .txt
        case "fb2": .fb2
        case "cbz": .cbz
        case "zip": .zip
        case "cbr": .cbr
        case "rar": .rar
        case "image_dir": .imagedir
        case "pdf": .pdf
        default: nil
        }
    }

}
