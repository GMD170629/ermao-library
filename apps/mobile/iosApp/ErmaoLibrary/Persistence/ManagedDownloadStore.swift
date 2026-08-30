import Foundation
@preconcurrency import ErmaoShared

actor ManagedDownloadStore: CompletedDownloadProviding {
    private struct Manifest: Codable {
        let contractVersion: Int
        var records: [ManagedDownloadRecord]
    }

    private static let currentContractVersion = 4
    private let rootDirectory: URL
    private let encoder: JSONEncoder
    private let initializationError: Error?
    private let decoder: JSONDecoder

    init(rootDirectory: URL? = nil) {
        var initializationError: Error?
        if let rootDirectory {
            self.rootDirectory = rootDirectory
        } else {
            let applicationSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
            let parent = applicationSupport.appendingPathComponent("com.ermao.library", isDirectory: true)
            let current = parent.appendingPathComponent("managed-downloads-v4", isDirectory: true)
            let legacy = parent.appendingPathComponent("managed-downloads-v3", isDirectory: true)
            if !FileManager.default.fileExists(atPath: current.path),
               FileManager.default.fileExists(atPath: legacy.path) {
                do { try FileManager.default.moveItem(at: legacy, to: current) }
                catch { initializationError = error }
            }
            self.rootDirectory = current
        }
        self.initializationError = initializationError
        encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func records(namespace: String) throws -> [ManagedDownloadRecord] {
        var manifest = try loadManifest(namespace: namespace)
        var changed = false
        for index in manifest.records.indices where manifest.records[index].isVerifiedOfflineCopy {
            guard let relativePath = manifest.records[index].localRelativePath,
                  let fileURL = resolvedContentURL(relativePath, namespace: namespace),
                  let size = verifiedArtifactBytes(at: fileURL, record: manifest.records[index]),
                  size == manifest.records[index].receivedBytes else {
                manifest.records[index].state = .failedTerminal
                manifest.records[index].verification = .invalid
                manifest.records[index].stableErrorCode = "DOWNLOAD_LOCAL_FILE_INVALID"
                manifest.records[index].updatedAt = Date()
                changed = true
                continue
            }
        }
        if changed { try saveManifest(manifest, namespace: namespace) }
        return manifest.records.sorted { $0.updatedAt > $1.updatedAt }
    }

    func update(_ record: ManagedDownloadRecord) throws {
        var manifest = try loadManifest(namespace: record.namespace)
        if let index = manifest.records.firstIndex(where: { $0.id == record.id }) { manifest.records[index] = record }
        else { manifest.records.append(record) }
        try saveManifest(manifest, namespace: record.namespace)
    }

    func destination(for record: ManagedDownloadRecord) throws -> ManagedDownloadDestination {
        let namespaceURL = namespaceDirectory(record.namespace)
        let staging = namespaceURL.appendingPathComponent("staging", isDirectory: true)
        let contentDirectory = namespaceURL.appendingPathComponent("content", isDirectory: true).appendingPathComponent(stableFileName(record.assetID) + "-" + stableFileName(record.id), isDirectory: true)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: contentDirectory, withIntermediateDirectories: true)
        let isBundle = record.effectiveArtifactKind == .originalPageSet
        let fileName = isBundle ? "bundle" : "asset.\(safeExtension(record.format))"
        let finalURL = contentDirectory.appendingPathComponent(fileName, isDirectory: isBundle)
        return ManagedDownloadDestination(
            partialFileURL: staging.appendingPathComponent(record.id + (isBundle ? ".bundle.part" : ".part"), isDirectory: isBundle),
            finalFileURL: finalURL,
            finalRelativePath: "content/\(stableFileName(record.assetID))-\(stableFileName(record.id))/\(fileName)"
        )
    }

    func storedBytes(for record: ManagedDownloadRecord) throws -> ErmaoShared.DownloadStoredBytes {
        let destination = try destination(for: record)
        if verifiedArtifactBytes(at: destination.finalFileURL, record: record) == record.expectedBytes {
            return ErmaoShared.DownloadStoredBytes(partialBytes: 0, completedReference: destination.finalRelativePath)
        }
        let bytes = record.effectiveArtifactKind == .singleOriginalAsset
            ? fileSize(at: destination.partialFileURL) ?? 0 : 0
        guard let expectedBytes = record.expectedBytes else { throw ManagedDownloadTransferError.invalidResponse }
        return ErmaoShared.DownloadStoredBytes(partialBytes: bytes < expectedBytes ? bytes : 0, completedReference: nil)
    }

    func discardStoredBytes(for record: ManagedDownloadRecord) throws {
        let destination = try destination(for: record)
        for candidate in [destination.partialFileURL, destination.finalFileURL]
            where FileManager.default.fileExists(atPath: candidate.path) {
            try FileManager.default.removeItem(at: candidate)
        }
        if let relativePath = record.localRelativePath,
           let published = resolvedContentURL(relativePath, namespace: record.namespace),
           published != destination.finalFileURL,
           FileManager.default.fileExists(atPath: published.path) {
            try FileManager.default.removeItem(at: published)
        }
    }

    /// Filesystem port: validate and atomically publish; task registration belongs to shared Downloads.
    func publishFile(record: ManagedDownloadRecord, destination: ManagedDownloadDestination, verifiedBytes: Int64) throws -> String {
        guard verifiedBytes > 0,
              verifiedArtifactBytes(at: destination.partialFileURL, record: record) == verifiedBytes,
              record.expectedBytes == verifiedBytes else {
            if FileManager.default.fileExists(atPath: destination.partialFileURL.path) { try FileManager.default.removeItem(at: destination.partialFileURL) }
            throw ManagedDownloadTransferError.invalidResponse
        }
        if FileManager.default.fileExists(atPath: destination.finalFileURL.path) {
            _ = try FileManager.default.replaceItemAt(destination.finalFileURL, withItemAt: destination.partialFileURL, backupItemName: nil, options: [])
        } else { try FileManager.default.moveItem(at: destination.partialFileURL, to: destination.finalFileURL) }
        return destination.finalRelativePath
    }

    func remove(_ record: ManagedDownloadRecord) throws {
        var manifest = try loadManifest(namespace: record.namespace)
        manifest.records.removeAll { $0.id == record.id }
        try removeFiles(for: record, namespace: record.namespace)
        try saveManifest(manifest, namespace: record.namespace)
    }

    func removeNamespace(_ namespace: String) throws {
        let directory = namespaceDirectory(namespace)
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    func fileURL(for record: ManagedDownloadRecord) -> URL? {
        guard record.isVerifiedOfflineCopy, let relativePath = record.localRelativePath,
              let url = resolvedContentURL(relativePath, namespace: record.namespace),
              verifiedArtifactBytes(at: url, record: record) == record.receivedBytes else { return nil }
        return url
    }

    func completedFile(recordID: String, namespace: String) throws -> CompletedDownloadFile? {
        let manifest = try loadManifest(namespace: namespace)
        guard let record = manifest.records.first(where: { $0.id == recordID }),
              record.namespace == namespace,
              record.verifiedSharedArtifact != nil,
              ReaderFormatSupport.shared.canReadOriginal(readerType: record.readerType.rawValue, format: record.format),
              let fileURL = fileURL(for: record) else { return nil }
        return CompletedDownloadFile(
            fileURL: fileURL,
            assetID: record.assetID,
            displayTitle: record.resourceTitle,
            bookID: record.bookID,
            resourceID: record.resourceID,
            sourceFormat: record.format,
            byteCount: record.receivedBytes
        )
    }

    private func loadManifest(namespace: String) throws -> Manifest {
        if let initializationError { throw initializationError }
        let url = manifestURL(namespace)
        guard FileManager.default.fileExists(atPath: url.path) else { return Manifest(contractVersion: Self.currentContractVersion, records: []) }
        let decoded = try decoder.decode(Manifest.self, from: Data(contentsOf: url))
        guard decoded.contractVersion == 3 || decoded.contractVersion == Self.currentContractVersion,
              decoded.records.allSatisfy({ $0.namespace == namespace }) else {
            // Invalid metadata must not erase user-initiated downloads.
            throw CocoaError(.fileReadCorruptFile)
        }
        let migrated = Manifest(contractVersion: Self.currentContractVersion, records: decoded.records)
        if decoded.contractVersion != Self.currentContractVersion { try saveManifest(migrated, namespace: namespace) }
        return migrated
    }

    private func saveManifest(_ manifest: Manifest, namespace: String) throws {
        let directory = namespaceDirectory(namespace)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let output = Manifest(contractVersion: Self.currentContractVersion, records: manifest.records)
        try encoder.encode(output).write(to: manifestURL(namespace), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    private func namespaceDirectory(_ namespace: String) -> URL { rootDirectory.appendingPathComponent(stableFileName(namespace), isDirectory: true) }
    private func manifestURL(_ namespace: String) -> URL { namespaceDirectory(namespace).appendingPathComponent("manifest.json") }

    private func resolvedContentURL(_ relativePath: String, namespace: String) -> URL? {
        guard !relativePath.isEmpty, !relativePath.hasPrefix("/"), !relativePath.contains("..") else { return nil }
        let root = namespaceDirectory(namespace).standardizedFileURL
        let candidate = root.appendingPathComponent(relativePath).standardizedFileURL
        return candidate.path.hasPrefix(root.path + "/") ? candidate : nil
    }

    private func removeFiles(for record: ManagedDownloadRecord, namespace: String) throws {
        if let path = record.localRelativePath, let fileURL = resolvedContentURL(path, namespace: namespace) { try? FileManager.default.removeItem(at: fileURL) }
        let staging = namespaceDirectory(namespace).appendingPathComponent("staging", isDirectory: true)
        try? FileManager.default.removeItem(at: staging.appendingPathComponent(record.id + ".part"))
        try? FileManager.default.removeItem(at: staging.appendingPathComponent(record.id + ".bundle.part", isDirectory: true))
    }

    private func fileSize(at url: URL) -> Int64? {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path), let size = attributes[.size] as? NSNumber else { return nil }
        return size.int64Value
    }

    private func verifiedArtifactBytes(at url: URL, record: ManagedDownloadRecord) -> Int64? {
        switch record.effectiveArtifactKind {
        case .singleOriginalAsset:
            return fileSize(at: url)
        case .originalPageSet:
            return verifiedPageSetBytes(at: url, expectedResourceID: record.resourceID)
        }
    }

    private func verifiedPageSetBytes(at directory: URL, expectedResourceID: String) -> Int64? {
        var isDirectory: ObjCBool = false
        let maximumPageCount = ErmaoShared.PublicKt.readerSafetyComicPageMaxCount()
        let maximumPageBytes = ErmaoShared.PublicKt.readerSafetyComicPageMaxBytes()
        let maximumExpandedBytes = ErmaoShared.PublicKt.readerSafetyComicExpandedMaxBytes()
        let allowedMimeTypes = Set(ErmaoShared.PublicKt.readerSafetyAllowedComicPageMimeTypes())
        guard FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory), isDirectory.boolValue,
              let data = try? Data(contentsOf: directory.appendingPathComponent("bundle.json")),
              Int64(data.count) <= ErmaoShared.PublicKt.readerSafetyComicManifestMaxBytes(),
              let manifest = try? decoder.decode(SharedManagedPageSetManifest.self, from: data),
              manifest.contractVersion == 4,
              manifest.artifactKind == "OriginalPageSet",
              manifest.resourceId == expectedResourceID,
              !manifest.members.isEmpty,
              Int64(manifest.members.count) <= maximumPageCount,
              manifest.totalBytes > 0,
              manifest.totalBytes <= maximumExpandedBytes,
              manifest.members.map(\.sequenceIndex) == Array(manifest.members.indices),
              Set(manifest.members.map(\.assetId)).count == manifest.members.count else { return nil }
        var verifiedTotalBytes: Int64 = 0
        for member in manifest.members {
            guard member.sizeBytes > 0, member.sizeBytes <= maximumPageBytes,
                  member.sizeBytes <= maximumExpandedBytes - verifiedTotalBytes,
                  !member.fileName.isEmpty, !member.fileName.hasPrefix("."),
                  !member.fileName.contains("/"), !member.fileName.contains("\\"),
                  allowedMimeTypes.contains(member.mimeType) else { return nil }
            let file = directory.appendingPathComponent(member.fileName).standardizedFileURL
            guard file.deletingLastPathComponent() == directory.standardizedFileURL,
                  fileSize(at: file) == member.sizeBytes,
                  managedDownloadImageMime(at: file) == member.mimeType else { return nil }
            verifiedTotalBytes += member.sizeBytes
        }
        return verifiedTotalBytes == manifest.totalBytes ? manifest.totalBytes : nil
    }

    private func stableFileName(_ value: String) -> String {
        value.data(using: .utf8)?.base64EncodedString().replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "+", with: "-") ?? UUID().uuidString
    }

    private func safeExtension(_ value: String) -> String {
        let normalized = value.lowercased().filter { $0.isLetter || $0.isNumber }
        return normalized.isEmpty ? "bin" : String(normalized.prefix(8))
    }
}

private struct SharedManagedPageSetManifest: Codable {
    let contractVersion: Int
    let artifactKind: String
    let resourceId: String
    let artifactId: String
    let totalBytes: Int64
    let members: [SharedManagedPageSetMember]
}

private struct SharedManagedPageSetMember: Codable {
    let assetId: String
    let sequenceIndex: Int
    let mimeType: String
    let sizeBytes: Int64
    let fileName: String
}

private func managedDownloadImageMime(at url: URL) -> String? {
    guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
    defer { try? handle.close() }
    guard let data = try? handle.read(upToCount: 16) else { return nil }
    let bytes = [UInt8](data)
    if bytes.count >= 3, bytes[0...2].elementsEqual([0xFF, 0xD8, 0xFF]) {
        return ErmaoShared.PublicKt.readerSafetyComicPageMimeType(extension: ".jpg")
    }
    if bytes.count >= 8, bytes[0..<8].elementsEqual([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) {
        return ErmaoShared.PublicKt.readerSafetyComicPageMimeType(extension: ".png")
    }
    if bytes.count >= 6,
       String(bytes: bytes[0..<6], encoding: .ascii).map({ ["GIF87a", "GIF89a"].contains($0) }) == true {
        return ErmaoShared.PublicKt.readerSafetyComicPageMimeType(extension: ".gif")
    }
    if bytes.count >= 12, String(bytes: bytes[0..<4], encoding: .ascii) == "RIFF",
       String(bytes: bytes[8..<12], encoding: .ascii) == "WEBP" {
        return ErmaoShared.PublicKt.readerSafetyComicPageMimeType(extension: ".webp")
    }
    return nil
}
