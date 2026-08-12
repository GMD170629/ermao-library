import CryptoKit
import Foundation

struct IosManagedPublication: Sendable, Equatable {
    let sourceID: String
    let displayTitle: String
    let fileURL: URL
    let byteCount: Int64
    let fingerprint: IosContentFingerprint
    let workID: String?
    let volumeID: String?
    let serverContentFingerprint: String?
}

actor IosManagedPublicationStore {
    static let parserVersion = "readium-swift:3.8.0"
    static let normalizationVersion = "epub-native-sanitized-v1"
    static let maximumPublicationBytes: Int64 = 512 * 1_024 * 1_024

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

    func importEPUB(
        from sourceURL: URL,
        sourceID: String,
        displayTitle: String,
        workID: String? = nil,
        volumeID: String? = nil,
        expectedOriginalFileHash: String? = nil
    ) throws -> IosManagedPublication {
        guard !sourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !displayTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              sourceURL.pathExtension.lowercased() == "epub"
        else {
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        let sourceValues = try sourceURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard sourceValues.isRegularFile == true, sourceValues.isSymbolicLink != true else {
            throw IosReaderFailure(code: .corruptFile)
        }
        if Int64(sourceValues.fileSize ?? 0) > Self.maximumPublicationBytes {
            throw IosReaderFailure(code: .outOfMemoryRisk)
        }

        let key = opaqueKey(sourceID)
        let destination = root.appendingPathComponent(key).appendingPathExtension("epub")
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
        var hasher = SHA256()
        var byteCount: Int64 = 0
        while let chunk = try input.read(upToCount: 1_048_576), !chunk.isEmpty {
            byteCount += Int64(chunk.count)
            guard byteCount <= Self.maximumPublicationBytes else {
                throw IosReaderFailure(code: .outOfMemoryRisk)
            }
            hasher.update(data: chunk)
            try output.write(contentsOf: chunk)
        }
        try output.synchronize()
        let originalFileHash = "sha256:" + hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard expectedOriginalFileHash == nil || expectedOriginalFileHash == originalFileHash else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let fingerprint = try IosContentFingerprint(
            originalFileHash: originalFileHash,
            parserVersion: Self.parserVersion,
            normalizationVersion: Self.normalizationVersion
        )
        let metadata = Metadata(
            sourceID: sourceID,
            displayTitle: displayTitle,
            byteCount: byteCount,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil
        )
        try install(staging: staging, destination: destination)
        do {
            let encoded = try JSONEncoder().encode(metadata)
            try encoded.write(to: metadataURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } catch {
            try? fileManager.removeItem(at: destination)
            throw IosReaderFailure(code: .persistenceFailed)
        }
        return IosManagedPublication(
            sourceID: sourceID,
            displayTitle: displayTitle,
            fileURL: destination,
            byteCount: byteCount,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil
        )
    }

    func prepareDownload(sourceID: String, expectedSize: Int64) throws -> URL {
        guard !sourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              expectedSize > 0,
              expectedSize <= Self.maximumPublicationBytes
        else { throw IosReaderFailure(code: .outOfMemoryRisk) }
        let key = opaqueKey(sourceID)
        let staging = root.appendingPathComponent(".\(key).\(UUID().uuidString).partial")
        try requireContained(staging)
        guard fileManager.createFile(
            atPath: staging.path,
            contents: nil,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        ) else { throw IosReaderFailure(code: .persistenceFailed) }
        return staging
    }

    func commitDownload(
        staging: URL,
        sourceID: String,
        displayTitle: String,
        byteCount: Int64,
        originalFileHash: String,
        expectedSize: Int64,
        expectedOriginalFileHash: String?,
        workID: String,
        volumeID: String
    ) throws -> IosManagedPublication {
        try requireContained(staging)
        guard byteCount == expectedSize,
              byteCount <= Self.maximumPublicationBytes,
              expectedOriginalFileHash == nil || expectedOriginalFileHash == originalFileHash
        else { throw IosReaderFailure(code: .corruptFile) }
        let stagingValues = try staging.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard stagingValues.isRegularFile == true,
              stagingValues.isSymbolicLink != true,
              Int64(stagingValues.fileSize ?? -1) == byteCount
        else { throw IosReaderFailure(code: .corruptFile) }

        let fingerprint = try IosContentFingerprint(
            originalFileHash: originalFileHash,
            parserVersion: Self.parserVersion,
            normalizationVersion: Self.normalizationVersion
        )
        let key = opaqueKey(sourceID)
        let destination = root.appendingPathComponent(key).appendingPathExtension("epub")
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        try requireContained(destination)
        try requireContained(metadataURL)
        let metadata = Metadata(
            sourceID: sourceID,
            displayTitle: displayTitle,
            byteCount: byteCount,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil
        )
        try install(staging: staging, destination: destination)
        do {
            let encoded = try JSONEncoder().encode(metadata)
            try encoded.write(to: metadataURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } catch {
            try? fileManager.removeItem(at: destination)
            throw IosReaderFailure(code: .persistenceFailed)
        }
        return IosManagedPublication(
            sourceID: sourceID,
            displayTitle: displayTitle,
            fileURL: destination,
            byteCount: byteCount,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil
        )
    }

    func abortDownload(staging: URL) throws {
        try requireContained(staging)
        if fileManager.fileExists(atPath: staging.path) {
            try fileManager.removeItem(at: staging)
        }
    }

    func bindServerContentFingerprint(sourceID: String, value: String) throws {
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        let key = opaqueKey(sourceID)
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        try requireContained(metadataURL)
        let values = try metadataURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              (values.fileSize ?? 0) <= 16_384
        else { throw IosReaderFailure(code: .persistenceFailed) }
        let existing = try JSONDecoder().decode(Metadata.self, from: Data(contentsOf: metadataURL))
        guard existing.sourceID == sourceID else { throw IosReaderFailure(code: .persistenceFailed) }
        let updated = Metadata(
            sourceID: existing.sourceID,
            displayTitle: existing.displayTitle,
            byteCount: existing.byteCount,
            fingerprint: existing.fingerprint,
            workID: existing.workID,
            volumeID: existing.volumeID,
            serverContentFingerprint: value
        )
        try JSONEncoder().encode(updated).write(
            to: metadataURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    func resolve(sourceID: String) throws -> IosManagedPublication {
        let key = opaqueKey(sourceID)
        let publicationURL = root.appendingPathComponent(key).appendingPathExtension("epub")
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        try requireContained(publicationURL)
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
        guard metadata.sourceID == sourceID,
              metadata.fingerprint.parserVersion == Self.parserVersion,
              metadata.fingerprint.normalizationVersion == Self.normalizationVersion
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let values = try publicationURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              Int64(values.fileSize ?? -1) == metadata.byteCount,
              metadata.byteCount <= Self.maximumPublicationBytes
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        guard try hash(of: publicationURL) == metadata.fingerprint.originalFileHash else {
            throw IosReaderFailure(code: .corruptFile)
        }
        return IosManagedPublication(
            sourceID: metadata.sourceID,
            displayTitle: metadata.displayTitle,
            fileURL: publicationURL,
            byteCount: metadata.byteCount,
            fingerprint: metadata.fingerprint,
            workID: metadata.workID,
            volumeID: metadata.volumeID,
            serverContentFingerprint: metadata.serverContentFingerprint
        )
    }

    func remove(sourceID: String) throws {
        let key = opaqueKey(sourceID)
        for url in [
            root.appendingPathComponent(key).appendingPathExtension("epub"),
            root.appendingPathComponent(key).appendingPathExtension("json"),
        ] where fileManager.fileExists(atPath: url.path) {
            try requireContained(url)
            try fileManager.removeItem(at: url)
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

    private func opaqueKey(_ sourceID: String) -> String {
        SHA256.hash(data: Data(sourceID.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func requireContained(_ url: URL) throws {
        let rootPath = root.standardizedFileURL.resolvingSymlinksInPath().path + "/"
        let path = url.standardizedFileURL.resolvingSymlinksInPath().path
        guard path.hasPrefix(rootPath) else { throw IosReaderFailure(code: .corruptFile) }
    }

    private func hash(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty {
            hasher.update(data: data)
        }
        return "sha256:" + hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private struct Metadata: Codable {
        let sourceID: String
        let displayTitle: String
        let byteCount: Int64
        let fingerprint: IosContentFingerprint
        let workID: String?
        let volumeID: String?
        let serverContentFingerprint: String?
    }
}
