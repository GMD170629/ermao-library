import Foundation

actor ManagedDownloadStore {
    private struct Manifest: Codable {
        var records: [ManagedDownloadRecord]
    }

    private let rootDirectory: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(rootDirectory: URL? = nil) {
        if let rootDirectory {
            self.rootDirectory = rootDirectory
        } else {
            let applicationSupport = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
            self.rootDirectory = applicationSupport.appendingPathComponent(
                "com.ermao.library/managed-downloads-v1",
                isDirectory: true
            )
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
            guard let relativePath = manifest.records[index].localRelativePath else { continue }
            guard let fileURL = resolvedContentURL(relativePath, namespace: namespace) else {
                manifest.records[index].state = .failedTerminal
                manifest.records[index].verification = .invalid
                manifest.records[index].stableErrorCode = "DOWNLOAD_LOCAL_FILE_INVALID"
                manifest.records[index].updatedAt = Date()
                changed = true
                continue
            }
            let fileSize = fileSize(at: fileURL)
            if fileSize == nil || fileSize != manifest.records[index].receivedBytes {
                manifest.records[index].state = .failedTerminal
                manifest.records[index].verification = .invalid
                manifest.records[index].stableErrorCode = "DOWNLOAD_LOCAL_FILE_INVALID"
                manifest.records[index].updatedAt = Date()
                changed = true
            }
        }
        if changed { try saveManifest(manifest, namespace: namespace) }
        return manifest.records.sorted { $0.updatedAt > $1.updatedAt }
    }

    func enqueue(
        namespace: String,
        work: WorkCard,
        volume: WorkVolume,
        mediaVersionID: String,
        mediaKind: LibraryMediaKind,
        readerType: ManagedDownloadReaderType,
        contentFingerprint: String,
        expectedBytes: Int64?,
        now: Date = Date()
    ) throws -> ManagedDownloadRecord {
        var manifest = try loadManifest(namespace: namespace)
        if let existingIndex = manifest.records.firstIndex(where: { $0.volumeID == volume.id }) {
            let existing = manifest.records[existingIndex]
            if existing.contentFingerprint == contentFingerprint,
               existing.effectiveMediaVersionID == mediaVersionID,
               existing.mediaKind == mediaKind,
               existing.readerType == readerType {
                return existing
            }
            if let path = existing.localRelativePath,
               let fileURL = resolvedContentURL(path, namespace: namespace),
               FileManager.default.fileExists(atPath: fileURL.path) {
                try FileManager.default.removeItem(at: fileURL)
            }
            let partialURL = namespaceDirectory(namespace)
                .appendingPathComponent("staging", isDirectory: true)
                .appendingPathComponent(existing.id + ".part", isDirectory: false)
            if FileManager.default.fileExists(atPath: partialURL.path) {
                try FileManager.default.removeItem(at: partialURL)
            }
            manifest.records.remove(at: existingIndex)
        }
        let record = ManagedDownloadRecord(
            id: UUID().uuidString,
            namespace: namespace,
            workID: work.id,
            workTitle: work.title,
            workAuthor: work.author,
            mediaVersionID: mediaVersionID,
            volumeID: volume.id,
            volumeTitle: volume.title,
            format: volume.formatLabel,
            mediaKind: mediaKind,
            readerType: readerType,
            state: .queued,
            verification: .pending,
            contentFingerprint: contentFingerprint,
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
        if let index = manifest.records.firstIndex(where: { $0.id == record.id }) {
            manifest.records[index] = record
        } else {
            manifest.records.append(record)
        }
        try saveManifest(manifest, namespace: record.namespace)
    }

    func destination(for record: ManagedDownloadRecord) throws -> ManagedDownloadDestination {
        let namespaceURL = namespaceDirectory(record.namespace)
        let staging = namespaceURL.appendingPathComponent("staging", isDirectory: true)
        let contentDirectory = namespaceURL
            .appendingPathComponent("content", isDirectory: true)
            .appendingPathComponent(stableFileName(record.volumeID), isDirectory: true)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: contentDirectory, withIntermediateDirectories: true)
        let ext = safeExtension(record.format)
        let fileName = "publication.\(ext)"
        let finalURL = contentDirectory.appendingPathComponent(fileName, isDirectory: false)
        let relativePath = "content/\(stableFileName(record.volumeID))/\(fileName)"
        return ManagedDownloadDestination(
            partialFileURL: staging.appendingPathComponent(record.id + ".part", isDirectory: false),
            finalFileURL: finalURL,
            finalRelativePath: relativePath
        )
    }

    func publish(
        record: ManagedDownloadRecord,
        destination: ManagedDownloadDestination,
        receipt: ManagedDownloadReceipt,
        now: Date = Date()
    ) throws -> ManagedDownloadRecord {
        guard receipt.receivedBytes > 0,
              fileSize(at: destination.partialFileURL) == receipt.receivedBytes,
              receipt.expectedBytes.map({ $0 == receipt.receivedBytes }) ?? true,
              !receipt.contentFingerprint.isEmpty else {
            if FileManager.default.fileExists(atPath: destination.partialFileURL.path) {
                try? FileManager.default.removeItem(at: destination.partialFileURL)
            }
            throw ManagedDownloadTransferError.invalidResponse
        }
        if FileManager.default.fileExists(atPath: destination.finalFileURL.path) {
            _ = try FileManager.default.replaceItemAt(
                destination.finalFileURL,
                withItemAt: destination.partialFileURL,
                backupItemName: nil,
                options: []
            )
        } else {
            try FileManager.default.moveItem(at: destination.partialFileURL, to: destination.finalFileURL)
        }
        var completed = record
        completed.state = .completed
        completed.verification = .verified
        completed.contentFingerprint = receipt.contentFingerprint
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
        if let path = record.localRelativePath {
            if let fileURL = resolvedContentURL(path, namespace: record.namespace),
               FileManager.default.fileExists(atPath: fileURL.path) {
                try FileManager.default.removeItem(at: fileURL)
            }
        }
        let partialURL = namespaceDirectory(record.namespace)
            .appendingPathComponent("staging", isDirectory: true)
            .appendingPathComponent(record.id + ".part", isDirectory: false)
        if FileManager.default.fileExists(atPath: partialURL.path) {
            try FileManager.default.removeItem(at: partialURL)
        }
        try saveManifest(manifest, namespace: record.namespace)
    }

    func removeNamespace(_ namespace: String) throws {
        let directory = namespaceDirectory(namespace)
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    func fileURL(for record: ManagedDownloadRecord) -> URL? {
        guard record.isVerifiedOfflineCopy, let relativePath = record.localRelativePath else { return nil }
        guard let url = resolvedContentURL(relativePath, namespace: record.namespace) else { return nil }
        return fileSize(at: url) == record.receivedBytes ? url : nil
    }

    func verifiedReaderArtifact(recordID: String, namespace: String) throws -> IosReaderDownloadArtifact? {
        let manifest = try loadManifest(namespace: namespace)
        guard let record = manifest.records.first(where: { $0.id == recordID }),
              record.namespace == namespace,
              ManagedReaderAccessPolicy.supportsNativeReader(
                  readerType: record.readerType,
                  format: record.format
              ),
              let serverContentFingerprint = record.contentFingerprint,
              !serverContentFingerprint.isEmpty,
              let fileURL = fileURL(for: record)
        else { return nil }
        return IosReaderDownloadArtifact(
            fileURL: fileURL,
            sourceID: record.volumeID,
            displayTitle: record.workTitle,
            workID: record.workID,
            volumeID: record.volumeID,
            sourceFormat: record.format,
            serverContentFingerprint: serverContentFingerprint
        )
    }

    private func loadManifest(namespace: String) throws -> Manifest {
        let url = manifestURL(namespace)
        guard FileManager.default.fileExists(atPath: url.path) else { return Manifest(records: []) }
        return try decoder.decode(Manifest.self, from: Data(contentsOf: url))
    }

    private func saveManifest(_ manifest: Manifest, namespace: String) throws {
        let directory = namespaceDirectory(namespace)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try encoder.encode(manifest).write(to: manifestURL(namespace), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    private func namespaceDirectory(_ namespace: String) -> URL {
        rootDirectory.appendingPathComponent(stableFileName(namespace), isDirectory: true)
    }

    private func manifestURL(_ namespace: String) -> URL {
        namespaceDirectory(namespace).appendingPathComponent("manifest.json", isDirectory: false)
    }

    private func resolvedContentURL(_ relativePath: String, namespace: String) -> URL? {
        guard !relativePath.hasPrefix("/"), !relativePath.contains("\\") else { return nil }
        let namespaceRoot = namespaceDirectory(namespace).standardizedFileURL
        let candidate = namespaceRoot.appendingPathComponent(relativePath).standardizedFileURL
        let rootPrefix = namespaceRoot.path.hasSuffix("/") ? namespaceRoot.path : namespaceRoot.path + "/"
        guard candidate.path.hasPrefix(rootPrefix), candidate.path != namespaceRoot.path else { return nil }
        let resolvedCandidate = candidate.resolvingSymlinksInPath()
        let resolvedRoot = namespaceRoot.resolvingSymlinksInPath()
        let resolvedPrefix = resolvedRoot.path.hasSuffix("/") ? resolvedRoot.path : resolvedRoot.path + "/"
        guard resolvedCandidate.path.hasPrefix(resolvedPrefix),
              resolvedCandidate.path != resolvedRoot.path else { return nil }
        return resolvedCandidate
    }

    private func fileSize(at url: URL) -> Int64? {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path) else { return nil }
        return (attributes[.size] as? NSNumber)?.int64Value
    }

    private func safeExtension(_ value: String) -> String {
        let normalized = value.lowercased().filter { $0.isLetter || $0.isNumber }
        return normalized.isEmpty ? "bin" : String(normalized.prefix(12))
    }

    private func stableFileName(_ value: String) -> String {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 1_099_511_628_211
        }
        return String(hash, radix: 16)
    }
}
