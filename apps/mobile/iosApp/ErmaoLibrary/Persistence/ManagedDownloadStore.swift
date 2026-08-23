import Foundation

actor ManagedDownloadStore {
    private struct Manifest: Codable {
        let contractVersion: Int
        var records: [ManagedDownloadRecord]
    }

    private static let currentContractVersion = 3
    private let rootDirectory: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(rootDirectory: URL? = nil) {
        if let rootDirectory {
            self.rootDirectory = rootDirectory
        } else {
            let applicationSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
            self.rootDirectory = applicationSupport.appendingPathComponent("com.ermao.library/managed-downloads-v3", isDirectory: true)
        }
        // The old manifest cannot be mapped from Work/Version/Volume/File to
        // Book/Resource/Asset. Destructive reset is intentional at contract 3.
        if self.rootDirectory.lastPathComponent == "managed-downloads-v3" {
            let parent = self.rootDirectory.deletingLastPathComponent()
            try? FileManager.default.removeItem(at: parent.appendingPathComponent("managed-downloads-v1", isDirectory: true))
            try? FileManager.default.removeItem(at: parent.appendingPathComponent("managed-downloads-v2", isDirectory: true))
        }
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
                  let size = fileSize(at: fileURL),
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

    func enqueue(
        namespace: String,
        book: BookCard,
        resource: BookResource,
        assetID: String,
        readerType: ManagedDownloadReaderType,
        expectedBytes: Int64?,
        now: Date = Date()
    ) throws -> ManagedDownloadRecord {
        precondition(!book.id.isEmpty && !resource.id.isEmpty && !assetID.isEmpty)
        var manifest = try loadManifest(namespace: namespace)
        if let existingIndex = manifest.records.firstIndex(where: { $0.resourceID == resource.id && $0.assetID == assetID }) {
            let existing = manifest.records[existingIndex]
            if existing.readerType == readerType && existing.expectedBytes == expectedBytes { return existing }
            try removeFiles(for: existing, namespace: namespace)
            manifest.records.remove(at: existingIndex)
        }
        let record = ManagedDownloadRecord(
            id: UUID().uuidString,
            namespace: namespace,
            bookID: book.id,
            bookTitle: book.title,
            bookAuthor: book.author,
            resourceID: resource.id,
            resourceTitle: resource.title,
            assetID: assetID,
            format: resource.format,
            readerType: readerType,
            state: .queued,
            verification: .pending,
            expectedBytes: expectedBytes,
            receivedBytes: 0,
            localRelativePath: nil,
            stableErrorCode: nil,
            createdAt: now,
            updatedAt: now,
            completedAt: nil,
            lastOpenedAt: nil
        )
        manifest.records.append(record)
        try saveManifest(manifest, namespace: namespace)
        return record
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
        let contentDirectory = namespaceURL.appendingPathComponent("content", isDirectory: true).appendingPathComponent(stableFileName(record.assetID), isDirectory: true)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: contentDirectory, withIntermediateDirectories: true)
        let ext = safeExtension(record.format)
        let fileName = "asset.\(ext)"
        let finalURL = contentDirectory.appendingPathComponent(fileName, isDirectory: false)
        return ManagedDownloadDestination(
            partialFileURL: staging.appendingPathComponent(record.id + ".part"),
            finalFileURL: finalURL,
            finalRelativePath: "content/\(stableFileName(record.assetID))/\(fileName)"
        )
    }

    func publish(record: ManagedDownloadRecord, destination: ManagedDownloadDestination, receipt: ManagedDownloadReceipt, now: Date = Date()) throws -> ManagedDownloadRecord {
        guard receipt.receivedBytes > 0, fileSize(at: destination.partialFileURL) == receipt.receivedBytes,
              receipt.expectedBytes.map({ $0 == receipt.receivedBytes }) ?? true else {
            try? FileManager.default.removeItem(at: destination.partialFileURL)
            throw ManagedDownloadTransferError.invalidResponse
        }
        if FileManager.default.fileExists(atPath: destination.finalFileURL.path) {
            _ = try FileManager.default.replaceItemAt(destination.finalFileURL, withItemAt: destination.partialFileURL, backupItemName: nil, options: [])
        } else { try FileManager.default.moveItem(at: destination.partialFileURL, to: destination.finalFileURL) }
        var completed = record
        completed.state = .completed
        completed.verification = .verified
        completed.expectedBytes = receipt.expectedBytes ?? receipt.receivedBytes
        completed.receivedBytes = receipt.receivedBytes
        completed.localRelativePath = destination.finalRelativePath
        completed.stableErrorCode = nil
        completed.updatedAt = now
        completed.completedAt = now
        try update(completed)
        return completed
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
              let url = resolvedContentURL(relativePath, namespace: record.namespace), fileSize(at: url) ?? 0 > 0 else { return nil }
        return url
    }

    func verifiedReaderArtifact(recordID: String, namespace: String) throws -> IosReaderDownloadArtifact? {
        let manifest = try loadManifest(namespace: namespace)
        guard let record = manifest.records.first(where: { $0.id == recordID }),
              record.namespace == namespace,
              ManagedReaderAccessPolicy.supportsNativeReader(readerType: record.readerType, format: record.format),
              let fileURL = fileURL(for: record) else { return nil }
        return IosReaderDownloadArtifact(
            fileURL: fileURL,
            assetID: record.assetID,
            displayTitle: record.resourceTitle,
            bookID: record.bookID,
            resourceID: record.resourceID,
            sourceFormat: record.format
        )
    }

    private func loadManifest(namespace: String) throws -> Manifest {
        let url = manifestURL(namespace)
        guard FileManager.default.fileExists(atPath: url.path) else { return Manifest(contractVersion: Self.currentContractVersion, records: []) }
        do {
            let manifest = try decoder.decode(Manifest.self, from: Data(contentsOf: url))
            guard manifest.contractVersion == Self.currentContractVersion else { throw CocoaError(.fileReadCorruptFile) }
            return manifest
        } catch {
            let directory = namespaceDirectory(namespace)
            if FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
            return Manifest(contractVersion: Self.currentContractVersion, records: [])
        }
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
        let partial = namespaceDirectory(namespace).appendingPathComponent("staging", isDirectory: true).appendingPathComponent(record.id + ".part")
        try? FileManager.default.removeItem(at: partial)
    }

    private func fileSize(at url: URL) -> Int64? {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path), let size = attributes[.size] as? NSNumber else { return nil }
        return size.int64Value
    }

    private func stableFileName(_ value: String) -> String {
        value.data(using: .utf8)?.base64EncodedString().replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "+", with: "-") ?? UUID().uuidString
    }

    private func safeExtension(_ value: String) -> String {
        let normalized = value.lowercased().filter { $0.isLetter || $0.isNumber }
        return normalized.isEmpty ? "bin" : String(normalized.prefix(8))
    }
}
