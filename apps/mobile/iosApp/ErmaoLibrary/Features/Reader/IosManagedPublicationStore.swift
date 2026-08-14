import CryptoKit
import Foundation
@preconcurrency import ErmaoShared

struct IosManagedPublication: Sendable, Equatable {
    let sourceID: String
    let displayTitle: String
    let fileURL: URL
    let byteCount: Int64
    let artifactContentHash: String
    let fingerprint: IosContentFingerprint
    let workID: String?
    let volumeID: String?
    let serverContentFingerprint: String?
    let sourceFormat: ErmaoShared.ReaderSourceFormat
}

actor IosManagedPublicationStore {
    static let parserVersion = "epub-package:1"
    static let normalizationVersion = "shuku-epub-locator-dom-v2"
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
    ) async throws -> IosManagedPublication {
        try await importPublication(
            from: sourceURL,
            sourceID: sourceID,
            displayTitle: displayTitle,
            sourceFormat: .epub,
            workID: workID,
            volumeID: volumeID,
            expectedOriginalFileHash: expectedOriginalFileHash,
            parserVersion: Self.parserVersion,
            normalizationVersion: Self.normalizationVersion
        )
    }

    func importPublication(
        from sourceURL: URL,
        sourceID: String,
        displayTitle: String,
        sourceFormat: ErmaoShared.ReaderSourceFormat,
        workID: String? = nil,
        volumeID: String? = nil,
        expectedOriginalFileHash: String? = nil,
        parserVersion: String,
        normalizationVersion: String
    ) async throws -> IosManagedPublication {
        guard !sourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !displayTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              Self.pathExtension(for: sourceFormat) == sourceURL.pathExtension.lowercased(),
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
            throw IosReaderFailure(code: .outOfMemoryRisk)
        }

        let key = opaqueKey(sourceID)
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
        guard expectedOriginalFileHash == nil || expectedOriginalFileHash?.caseInsensitiveCompare(
            originalFileHash
        ) == .orderedSame else {
            throw IosReaderFailure(code: .corruptFile)
        }
        try await validatePublication(
            at: staging,
            sourceFormat: sourceFormat,
            parserVersion: parserVersion,
            normalizationVersion: normalizationVersion
        )
        let fingerprint = try IosContentFingerprint(
            originalFileHash: originalFileHash,
            parserVersion: parserVersion,
            normalizationVersion: normalizationVersion
        )
        let metadata = Metadata(
            sourceID: sourceID,
            displayTitle: displayTitle,
            byteCount: byteCount,
            artifactContentHash: originalFileHash,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil,
            sourceFormat: sourceFormat.wireValue
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
            artifactContentHash: originalFileHash,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil,
            sourceFormat: sourceFormat
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
        artifactContentHash: String,
        expectedSize: Int64,
        expectedContentHash: String?,
        originalFileHash: String,
        parserVersion: String,
        normalizationVersion: String,
        sourceFormat: ErmaoShared.ReaderSourceFormat,
        workID: String,
        volumeID: String
    ) async throws -> IosManagedPublication {
        try requireContained(staging)
        guard byteCount == expectedSize,
              byteCount <= Self.maximumPublicationBytes,
              expectedContentHash == nil || expectedContentHash?.caseInsensitiveCompare(
                  artifactContentHash
              ) == .orderedSame
        else { throw IosReaderFailure(code: .corruptFile) }
        let stagingValues = try staging.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard stagingValues.isRegularFile == true,
              stagingValues.isSymbolicLink != true,
              Int64(stagingValues.fileSize ?? -1) == byteCount
        else { throw IosReaderFailure(code: .corruptFile) }
        guard try hash(of: staging).caseInsensitiveCompare(artifactContentHash) == .orderedSame else {
            throw IosReaderFailure(code: .corruptFile)
        }
        try await validatePublication(
            at: staging,
            sourceFormat: sourceFormat,
            parserVersion: parserVersion,
            normalizationVersion: normalizationVersion
        )

        let fingerprint = try IosContentFingerprint(
            originalFileHash: originalFileHash,
            parserVersion: parserVersion,
            normalizationVersion: normalizationVersion
        )
        let key = opaqueKey(sourceID)
        let destination = root.appendingPathComponent(key)
            .appendingPathExtension(Self.pathExtension(for: sourceFormat))
        let metadataURL = root.appendingPathComponent(key).appendingPathExtension("json")
        try requireContained(destination)
        try requireContained(metadataURL)
        let metadata = Metadata(
            sourceID: sourceID,
            displayTitle: displayTitle,
            byteCount: byteCount,
            artifactContentHash: artifactContentHash,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil,
            sourceFormat: sourceFormat.wireValue
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
            artifactContentHash: artifactContentHash,
            fingerprint: fingerprint,
            workID: workID,
            volumeID: volumeID,
            serverContentFingerprint: nil,
            sourceFormat: sourceFormat
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
            artifactContentHash: existing.artifactContentHash,
            fingerprint: existing.fingerprint,
            workID: existing.workID,
            volumeID: existing.volumeID,
            serverContentFingerprint: value,
            sourceFormat: existing.sourceFormat
        )
        try JSONEncoder().encode(updated).write(
            to: metadataURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    func resolve(sourceID: String) throws -> IosManagedPublication {
        let key = opaqueKey(sourceID)
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
        guard metadata.sourceID == sourceID else {
            throw IosReaderFailure(code: .corruptFile)
        }
        guard let sourceFormat = Self.sourceFormat(metadata.sourceFormat) else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let publicationURL = root.appendingPathComponent(key)
            .appendingPathExtension(Self.pathExtension(for: sourceFormat))
        try requireContained(publicationURL)
        let values = try publicationURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              Int64(values.fileSize ?? -1) == metadata.byteCount,
              metadata.byteCount <= Self.maximumPublicationBytes
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let artifactContentHash = metadata.artifactContentHash ?? metadata.fingerprint.originalFileHash
        guard try hash(of: publicationURL).caseInsensitiveCompare(artifactContentHash) == .orderedSame else {
            throw IosReaderFailure(code: .corruptFile)
        }
        return IosManagedPublication(
            sourceID: metadata.sourceID,
            displayTitle: metadata.displayTitle,
            fileURL: publicationURL,
            byteCount: metadata.byteCount,
            artifactContentHash: artifactContentHash,
            fingerprint: metadata.fingerprint,
            workID: metadata.workID,
            volumeID: metadata.volumeID,
            serverContentFingerprint: metadata.serverContentFingerprint,
            sourceFormat: sourceFormat
        )
    }

    func remove(sourceID: String) throws {
        let key = opaqueKey(sourceID)
        for url in [
            root.appendingPathComponent(key).appendingPathExtension("epub"),
            root.appendingPathComponent(key).appendingPathExtension("mobi"),
            root.appendingPathComponent(key).appendingPathExtension("azw"),
            root.appendingPathComponent(key).appendingPathExtension("azw3"),
            root.appendingPathComponent(key).appendingPathExtension("prc"),
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

    private func validatePublication(
        at url: URL,
        sourceFormat: ErmaoShared.ReaderSourceFormat,
        parserVersion: String,
        normalizationVersion: String
    ) async throws {
        switch sourceFormat {
        case .epub:
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            let header = try handle.read(upToCount: 58) ?? Data()
            guard Self.hasValidEpubMimetypeEntry(header)
            else {
                throw IosReaderFailure(code: .corruptFile)
            }
        case .mobi, .azw, .azw3, .prc:
            guard parserVersion == IosMobiBook.parserIdentifier,
                  normalizationVersion == IosMobiPublicationIdentity.normalizationIdentifier
            else {
                throw IosReaderFailure(code: .corruptFile)
            }
            do {
                let book = try IosMobiBook.open(fileURL: url)
                do {
                    let info = try await book.info()
                    await book.close()
                    guard info.resourceCount > 0, info.readingOrderCount > 0 else {
                        throw IosReaderFailure(code: .corruptFile)
                    }
                } catch {
                    await book.close()
                    throw error
                }
            } catch let error as IosMobiCoreError {
                switch error.status {
                case .drmProtected:
                    throw IosReaderFailure(code: .drmProtected)
                case .unsupported, .noContent:
                    throw IosReaderFailure(code: .unsupportedFormat)
                case .limitExceeded, .outOfMemory:
                    throw IosReaderFailure(code: .outOfMemoryRisk)
                case .fileNotFound, .notFound:
                    throw IosReaderFailure(code: .resourceMissing)
                case .io:
                    throw IosReaderFailure(code: .engineError)
                default:
                    throw IosReaderFailure(code: .corruptFile)
                }
            }
        case .txt:
            let data = try Data(contentsOf: url, options: [.mappedIfSafe])
            guard data.count <= 64 * 1_024 * 1_024,
                  !data.contains(0),
                  Self.decodeText(data) != nil
            else {
                throw IosReaderFailure(code: .corruptFile)
            }
        case .pdf:
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            guard try handle.read(upToCount: 5) == Data("%PDF-".utf8) else {
                throw IosReaderFailure(code: .corruptFile)
            }
        case .cbz:
            do {
                _ = try IosCbzArchiveIndex(fileURL: url)
            } catch IosCbzError.limitExceeded {
                throw IosReaderFailure(code: .outOfMemoryRisk)
            } catch IosCbzError.encrypted {
                throw IosReaderFailure(code: .drmProtected)
            } catch {
                throw IosReaderFailure(code: .corruptFile)
            }
        default:
            throw IosReaderFailure(code: .unsupportedFormat)
        }
    }

    private struct Metadata: Codable {
        let sourceID: String
        let displayTitle: String
        let byteCount: Int64
        let artifactContentHash: String?
        let fingerprint: IosContentFingerprint
        let workID: String?
        let volumeID: String?
        let serverContentFingerprint: String?
        let sourceFormat: String
    }

    private static func hasValidEpubMimetypeEntry(_ header: Data) -> Bool {
        guard header.count >= 58,
              Array(header[0 ..< 4]) == [0x50, 0x4B, 0x03, 0x04]
        else { return false }
        let compression = UInt16(header[8]) | UInt16(header[9]) << 8
        let nameLength = UInt16(header[26]) | UInt16(header[27]) << 8
        let extraLength = UInt16(header[28]) | UInt16(header[29]) << 8
        guard compression == 0, nameLength == 8, extraLength == 0,
              String(data: header[30 ..< 38], encoding: .ascii) == "mimetype",
              String(data: header[38 ..< 58], encoding: .ascii) == "application/epub+zip"
        else { return false }
        return true
    }

    private static func pathExtension(for sourceFormat: ErmaoShared.ReaderSourceFormat) -> String {
        sourceFormat.wireValue
    }

    static func sourceFormat(_ wireValue: String) -> ErmaoShared.ReaderSourceFormat? {
        switch wireValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "epub": .epub
        case "mobi": .mobi
        case "azw": .azw
        case "azw3": .azw3
        case "prc": .prc
        case "txt": .txt
        case "cbz": .cbz
        case "pdf": .pdf
        default: nil
        }
    }

    private static func decodeText(_ data: Data) -> String? {
        if data.starts(with: [0xEF, 0xBB, 0xBF]) {
            return String(data: data.dropFirst(3), encoding: .utf8)
        }
        if data.starts(with: [0xFF, 0xFE]) {
            return String(data: data.dropFirst(2), encoding: .utf16LittleEndian)
        }
        if data.starts(with: [0xFE, 0xFF]) {
            return String(data: data.dropFirst(2), encoding: .utf16BigEndian)
        }
        return String(data: data, encoding: .utf8)
            ?? String(data: data, encoding: String.Encoding(rawValue: 0x8000_0632))
    }
}
