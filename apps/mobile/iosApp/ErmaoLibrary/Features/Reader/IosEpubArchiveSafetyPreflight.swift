import CoreFoundation
import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumZIPFoundation

/// Detects ZIP facts before Readium builds an EPUB Publication. The original file is read-only;
/// policy limits and outcomes are supplied by the generated Reader safety contract.
struct IosEpubArchiveSafetyPreflight {
    static func verify(fileURL: URL) async throws {
        let entryLimit = UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryMaxCount())
        let parsed: ParsedArchive
        do {
            parsed = try await Task.detached(priority: .userInitiated) {
                try CentralDirectoryReader.read(fileURL: fileURL, maximumEntries: entryLimit)
            }.value
        } catch ArchiveReadFailure.entryCountLimit {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryCountFailure()
            )
        } catch {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyEpubArchiveStructureFailure(),
                underlyingError: error as NSError
            )
        }

        try verifyMetadata(parsed.entries, archiveLength: parsed.archiveLength)
        try await verifyContents(fileURL: fileURL, entries: parsed.entries)
    }

    static func verifyMetadata(_ entries: [EntryFacts], archiveLength: UInt64) throws {
        let fatalFindings = Set(ErmaoShared.PublicKt.readerSafetyEpubArchiveFatalFindings())
        let supportedFindings: Set<String> = [
            "PATH_ESCAPE", "ABSOLUTE_PATH", "BACKSLASH_PATH", "NUL_PATH", "DOT_SEGMENT",
            "DUPLICATE_CANONICAL_ENTRY", "SYMLINK", "ENCRYPTED_ENTRY", "OVERLAPPING_ENTRY",
            "CRC_MISMATCH",
        ]
        if !fatalFindings.isSubset(of: supportedFindings) {
            let ruleId = ErmaoShared.PublicKt.readerSafetyEpubArchiveStructureFailure().ruleId
            throw implementationFailure(
                ErmaoShared.PublicKt.readerSafetyPlatformAlgorithmUnsupported(ruleId: ruleId)
            )
        }

        if UInt64(entries.count) > UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryMaxCount()) {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryCountFailure()
            )
        }

        var canonicalPaths = Set<String>()
        var expandedBytes: UInt64 = 0
        let maximumEntryBytes = UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryMaxBytes())
        let maximumExpandedBytes = UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveExpandedMaxBytes())
        let maximumRatio = UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveCompressionRatioMax())

        for entry in entries {
            let path = entry.path.hasSuffix("/") ? String(entry.path.dropLast()) : entry.path
            try rejectFinding(
                fatalFindings, "ABSOLUTE_PATH",
                path.hasPrefix("/") || isWindowsAbsolutePath(path)
            )
            try rejectFinding(fatalFindings, "BACKSLASH_PATH", path.contains("\\"))
            try rejectFinding(fatalFindings, "NUL_PATH", path.utf8.contains(0))
            let segments = path.split(separator: "/", omittingEmptySubsequences: false)
            try rejectFinding(
                fatalFindings, "DOT_SEGMENT",
                path.isEmpty || segments.contains { $0.isEmpty || $0 == "." || $0 == ".." }
            )
            try rejectFinding(
                fatalFindings, "PATH_ESCAPE",
                path == ".." || path.hasPrefix("../")
            )
            try rejectFinding(
                fatalFindings, "DUPLICATE_CANONICAL_ENTRY",
                !canonicalPaths.insert(path).inserted
            )
            try rejectFinding(fatalFindings, "SYMLINK", entry.isSymbolicLink)
            try rejectFinding(fatalFindings, "ENCRYPTED_ENTRY", entry.isEncrypted)

            if entry.uncompressedSize > maximumEntryBytes {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryBytesFailure()
                )
            }
            if exceedsCompressionRatio(
                uncompressedSize: entry.uncompressedSize,
                compressedSize: entry.compressedSize,
                maximumRatio: maximumRatio
            ) {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyEpubArchiveCompressionRatioFailure()
                )
            }
            let (nextExpandedBytes, expandedOverflow) = expandedBytes.addingReportingOverflow(
                entry.uncompressedSize
            )
            if expandedOverflow || nextExpandedBytes > maximumExpandedBytes {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyEpubArchiveExpandedBytesFailure()
                )
            }
            expandedBytes = nextExpandedBytes

            if entry.localHeaderOffset > entry.dataOffset || entry.physicalEndOffset > archiveLength {
                try rejectFinding(fatalFindings, "OVERLAPPING_ENTRY", true)
            }
        }

        let physicalEntries = entries.sorted { $0.localHeaderOffset < $1.localHeaderOffset }
        if physicalEntries.count > 1 {
            for index in 1 ..< physicalEntries.count {
                if physicalEntries[index].localHeaderOffset < physicalEntries[index - 1].physicalEndOffset {
                    try rejectFinding(fatalFindings, "OVERLAPPING_ENTRY", true)
                }
            }
        }
    }

    private static func verifyContents(fileURL: URL, entries expectedEntries: [EntryFacts]) async throws {
        let structureFailure = ErmaoShared.PublicKt.readerSafetyEpubArchiveStructureFailure()
        do {
            let archive = try await ReadiumZIPFoundation.Archive(url: fileURL, accessMode: .read)
            let archiveEntries = try await archive.entries()
            var entriesByPath: [String: ReadiumZIPFoundation.Entry] = [:]
            for entry in archiveEntries {
                if entriesByPath.updateValue(entry, forKey: entry.path) != nil {
                    throw IosReaderFailure.safety(structureFailure)
                }
            }

            let counter = ExpandedByteCounter(
                maximumEntryBytes: UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryMaxBytes()),
                maximumExpandedBytes: UInt64(ErmaoShared.PublicKt.readerSafetyEpubArchiveExpandedMaxBytes()),
                entryFailure: IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyEpubArchiveEntryBytesFailure()
                ),
                expandedFailure: IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyEpubArchiveExpandedBytesFailure()
                )
            )

            for expected in expectedEntries where !expected.isDirectory {
                guard let entry = entriesByPath[expected.path], entry.type == .file,
                      entry.uncompressedSize == expected.uncompressedSize,
                      entry.compressedSize == expected.compressedSize
                else {
                    throw IosReaderFailure.safety(structureFailure)
                }
                await counter.beginEntry()
                let checksum = try await archive.extract(entry, skipCRC32: false) { chunk in
                    try await counter.consume(UInt64(chunk.count))
                }
                let actualBytes = await counter.currentEntryBytes()
                if actualBytes != expected.uncompressedSize || checksum != expected.crc32 {
                    throw IosReaderFailure.safety(structureFailure)
                }
            }
        } catch let failure as IosReaderFailure {
            throw failure
        } catch {
            if let archiveError = error as? ReadiumZIPFoundation.Archive.ArchiveError,
               case .invalidCompressionMethod = archiveError
            {
                throw implementationFailure(
                    ErmaoShared.PublicKt.readerSafetyEngineAlgorithmUnsupported(
                        ruleId: structureFailure.ruleId
                    ),
                    underlyingError: error as NSError
                )
            }
            throw IosReaderFailure.safety(structureFailure, underlyingError: error as NSError)
        }
    }

    private static func rejectFinding(
        _ fatalFindings: Set<String>,
        _ finding: String,
        _ condition: Bool
    ) throws {
        if condition && fatalFindings.contains(finding) {
            throw IosReaderFailure.safety(
                ErmaoShared.PublicKt.readerSafetyEpubArchiveStructureFailure()
            )
        }
    }

    private static func implementationFailure(
        _ failure: ErmaoShared.ReaderSafetyImplementationFailure,
        underlyingError: NSError? = nil
    ) -> IosReaderFailure {
        let code = ErmaoShared.PublicKt.readerErrorCodeForFailure(
            failureCode: failure.errorCode,
            recoverable: false
        )
        return IosReaderFailure(
            code: IosReaderFailureCode(sharedCode: code),
            safeContext: ["ruleId": failure.ruleId, "errorCode": failure.errorCode],
            underlyingError: underlyingError
        )
    }

    private static func exceedsCompressionRatio(
        uncompressedSize: UInt64,
        compressedSize: UInt64,
        maximumRatio: UInt64
    ) -> Bool {
        guard uncompressedSize > 0 else { return false }
        guard compressedSize > 0 else { return true }
        let quotient = uncompressedSize / compressedSize
        return quotient > maximumRatio ||
            (quotient == maximumRatio && uncompressedSize % compressedSize != 0)
    }

    private static func isWindowsAbsolutePath(_ path: String) -> Bool {
        let bytes = Array(path.utf8)
        guard bytes.count >= 2, bytes[1] == 0x3A else { return false }
        return (0x41 ... 0x5A).contains(bytes[0]) || (0x61 ... 0x7A).contains(bytes[0])
    }

    struct EntryFacts: Sendable {
        let path: String
        let isDirectory: Bool
        let isSymbolicLink: Bool
        let isEncrypted: Bool
        let uncompressedSize: UInt64
        let compressedSize: UInt64
        let crc32: UInt32
        let localHeaderOffset: UInt64
        let dataOffset: UInt64
        let physicalEndOffset: UInt64
    }

    private struct ParsedArchive: Sendable {
        let archiveLength: UInt64
        let entries: [EntryFacts]
    }

    private enum ArchiveReadFailure: Error, Sendable {
        case invalidArchive
        case entryCountLimit
    }

    private actor ExpandedByteCounter {
        let maximumEntryBytes: UInt64
        let maximumExpandedBytes: UInt64
        let entryFailure: IosReaderFailure
        let expandedFailure: IosReaderFailure
        var entryBytes: UInt64 = 0
        var expandedBytes: UInt64 = 0

        init(
            maximumEntryBytes: UInt64,
            maximumExpandedBytes: UInt64,
            entryFailure: IosReaderFailure,
            expandedFailure: IosReaderFailure
        ) {
            self.maximumEntryBytes = maximumEntryBytes
            self.maximumExpandedBytes = maximumExpandedBytes
            self.entryFailure = entryFailure
            self.expandedFailure = expandedFailure
        }

        func beginEntry() {
            entryBytes = 0
        }

        func consume(_ count: UInt64) throws {
            let (nextEntryBytes, entryOverflow) = entryBytes.addingReportingOverflow(count)
            if entryOverflow || nextEntryBytes > maximumEntryBytes { throw entryFailure }
            let (nextExpandedBytes, expandedOverflow) = expandedBytes.addingReportingOverflow(count)
            if expandedOverflow || nextExpandedBytes > maximumExpandedBytes { throw expandedFailure }
            entryBytes = nextEntryBytes
            expandedBytes = nextExpandedBytes
        }

        func currentEntryBytes() -> UInt64 { entryBytes }
    }

    private enum CentralDirectoryReader {
        static func read(fileURL: URL, maximumEntries: UInt64) throws -> ParsedArchive {
            let handle = try FileHandle(forReadingFrom: fileURL)
            defer { try? handle.close() }
            let archiveLength = try handle.seekToEnd()
            guard archiveLength >= UInt64(endOfCentralDirectorySize) else {
                throw ArchiveReadFailure.invalidArchive
            }

            let tailLength = Int(min(archiveLength, UInt64(maximumEndSearchBytes)))
            let tail = try readBytes(
                handle: handle,
                offset: archiveLength - UInt64(tailLength),
                count: tailLength
            )
            guard let endIndex = findEndRecord(in: tail) else {
                throw ArchiveReadFailure.invalidArchive
            }
            let endOffset = archiveLength - UInt64(tailLength) + UInt64(endIndex)
            let end = Array(tail[endIndex ..< endIndex + endOfCentralDirectorySize])

            let directory: DirectoryLocation
            if u16(end, 10) == UInt16.max || u32(end, 12) == UInt32.max || u32(end, 16) == UInt32.max {
                directory = try readZip64Directory(handle: handle, endOffset: endOffset)
            } else {
                guard u16(end, 4) == 0, u16(end, 6) == 0, u16(end, 8) == u16(end, 10) else {
                    throw ArchiveReadFailure.invalidArchive
                }
                directory = DirectoryLocation(
                    entryCount: UInt64(u16(end, 10)),
                    size: UInt64(u32(end, 12)),
                    offset: UInt64(u32(end, 16))
                )
            }
            if directory.entryCount > maximumEntries { throw ArchiveReadFailure.entryCountLimit }
            let (directoryEnd, directoryOverflow) = directory.offset.addingReportingOverflow(directory.size)
            guard !directoryOverflow, directoryEnd <= endOffset else {
                throw ArchiveReadFailure.invalidArchive
            }

            var entries: [EntryFacts] = []
            entries.reserveCapacity(Int(directory.entryCount))
            var cursor = directory.offset
            for _ in 0 ..< directory.entryCount {
                let header = try readBytes(handle: handle, offset: cursor, count: centralHeaderSize)
                guard u32(header, 0) == centralHeaderSignature else {
                    throw ArchiveReadFailure.invalidArchive
                }
                let nameLength = Int(u16(header, 28))
                let extraLength = Int(u16(header, 30))
                let commentLength = Int(u16(header, 32))
                let variableLength = nameLength + extraLength + commentLength
                let variable = try readBytes(
                    handle: handle,
                    offset: cursor + UInt64(centralHeaderSize),
                    count: variableLength
                )
                let rawName = Array(variable[0 ..< nameLength])
                let extra = Array(variable[nameLength ..< nameLength + extraLength])
                let flags = u16(header, 8)
                guard let path = decodePath(rawName, utf8: flags & utf8NameFlag != 0) else {
                    throw ArchiveReadFailure.invalidArchive
                }
                let rawUncompressed = u32(header, 24)
                let rawCompressed = u32(header, 20)
                let rawLocalOffset = u32(header, 42)
                let rawDiskStart = u16(header, 34)
                let zip64 = try zip64Values(
                    extra: extra,
                    uncompressed: rawUncompressed == UInt32.max,
                    compressed: rawCompressed == UInt32.max,
                    localOffset: rawLocalOffset == UInt32.max,
                    diskStart: rawDiskStart == UInt16.max
                )
                let uncompressedSize = zip64.uncompressed ?? UInt64(rawUncompressed)
                let compressedSize = zip64.compressed ?? UInt64(rawCompressed)
                let localOffset = zip64.localOffset ?? UInt64(rawLocalOffset)
                let diskStart = zip64.diskStart ?? UInt32(rawDiskStart)
                guard diskStart == 0 else { throw ArchiveReadFailure.invalidArchive }

                let local = try readBytes(handle: handle, offset: localOffset, count: localHeaderSize)
                guard u32(local, 0) == localHeaderSignature,
                      u16(local, 8) == u16(header, 10)
                else {
                    throw ArchiveReadFailure.invalidArchive
                }
                let localNameLength = Int(u16(local, 26))
                let localExtraLength = Int(u16(local, 28))
                let localName = try readBytes(
                    handle: handle,
                    offset: localOffset + UInt64(localHeaderSize),
                    count: localNameLength
                )
                guard localName == rawName else { throw ArchiveReadFailure.invalidArchive }
                let (dataOffset, dataOffsetOverflow) = localOffset.addingReportingOverflow(
                    UInt64(localHeaderSize + localNameLength + localExtraLength)
                )
                guard !dataOffsetOverflow else { throw ArchiveReadFailure.invalidArchive }
                let (compressedEnd, compressedEndOverflow) = dataOffset.addingReportingOverflow(compressedSize)
                guard !compressedEndOverflow else { throw ArchiveReadFailure.invalidArchive }

                let usesZip64 = rawUncompressed == UInt32.max || rawCompressed == UInt32.max
                let physicalEnd = try dataDescriptorEnd(
                    handle: handle,
                    compressedEnd: compressedEnd,
                    usesDescriptor: flags & dataDescriptorFlag != 0,
                    usesZip64: usesZip64,
                    crc32: u32(header, 16),
                    compressedSize: compressedSize,
                    uncompressedSize: uncompressedSize
                )
                guard physicalEnd <= directory.offset else {
                    throw ArchiveReadFailure.invalidArchive
                }

                let versionMadeBy = u16(header, 4)
                let host = versionMadeBy >> 8
                let unixMode = u32(header, 38) >> 16
                let fileType = unixMode & unixFileTypeMask
                let isUnix = host == unixHost || host == osxHost
                let isSymbolicLink = isUnix && fileType == unixSymbolicLink
                let isDirectory = path.hasSuffix("/") || (isUnix && fileType == unixDirectory)
                entries.append(
                    EntryFacts(
                        path: path,
                        isDirectory: isDirectory,
                        isSymbolicLink: isSymbolicLink,
                        isEncrypted: flags & encryptionFlag != 0 || u16(local, 6) & encryptionFlag != 0,
                        uncompressedSize: uncompressedSize,
                        compressedSize: compressedSize,
                        crc32: u32(header, 16),
                        localHeaderOffset: localOffset,
                        dataOffset: dataOffset,
                        physicalEndOffset: physicalEnd
                    )
                )
                cursor += UInt64(centralHeaderSize + variableLength)
            }

            if cursor != directoryEnd {
                let signature = try readBytes(handle: handle, offset: cursor, count: 6)
                let signatureLength = Int(u16(signature, 4))
                guard u32(signature, 0) == centralDigitalSignature,
                      cursor + UInt64(6 + signatureLength) == directoryEnd
                else {
                    throw ArchiveReadFailure.invalidArchive
                }
            }
            return ParsedArchive(archiveLength: archiveLength, entries: entries)
        }

        private static func findEndRecord(in bytes: [UInt8]) -> Int? {
            guard bytes.count >= endOfCentralDirectorySize else { return nil }
            for index in stride(from: bytes.count - endOfCentralDirectorySize, through: 0, by: -1) {
                guard u32(bytes, index) == endOfCentralDirectorySignature else { continue }
                let commentLength = Int(u16(bytes, index + 20))
                if index + endOfCentralDirectorySize + commentLength == bytes.count { return index }
            }
            return nil
        }

        private static func readZip64Directory(
            handle: FileHandle,
            endOffset: UInt64
        ) throws -> DirectoryLocation {
            guard endOffset >= UInt64(zip64LocatorSize) else { throw ArchiveReadFailure.invalidArchive }
            let locator = try readBytes(
                handle: handle,
                offset: endOffset - UInt64(zip64LocatorSize),
                count: zip64LocatorSize
            )
            guard u32(locator, 0) == zip64LocatorSignature, u32(locator, 4) == 0, u32(locator, 16) == 1 else {
                throw ArchiveReadFailure.invalidArchive
            }
            let recordOffset = u64(locator, 8)
            let record = try readBytes(handle: handle, offset: recordOffset, count: zip64RecordMinimumSize)
            guard u32(record, 0) == zip64RecordSignature,
                  u32(record, 16) == 0,
                  u32(record, 20) == 0,
                  u64(record, 24) == u64(record, 32)
            else {
                throw ArchiveReadFailure.invalidArchive
            }
            return DirectoryLocation(entryCount: u64(record, 32), size: u64(record, 40), offset: u64(record, 48))
        }

        private static func zip64Values(
            extra: [UInt8],
            uncompressed needsUncompressed: Bool,
            compressed needsCompressed: Bool,
            localOffset needsLocalOffset: Bool,
            diskStart needsDiskStart: Bool
        ) throws -> Zip64Values {
            guard needsUncompressed || needsCompressed || needsLocalOffset || needsDiskStart else {
                return Zip64Values()
            }
            var fieldIndex = 0
            while fieldIndex + 4 <= extra.count {
                let identifier = u16(extra, fieldIndex)
                let length = Int(u16(extra, fieldIndex + 2))
                let valueStart = fieldIndex + 4
                guard valueStart + length <= extra.count else { throw ArchiveReadFailure.invalidArchive }
                if identifier == zip64ExtraIdentifier {
                    let value = Array(extra[valueStart ..< valueStart + length])
                    var cursor = 0
                    func next64() throws -> UInt64 {
                        guard cursor + 8 <= value.count else { throw ArchiveReadFailure.invalidArchive }
                        defer { cursor += 8 }
                        return u64(value, cursor)
                    }
                    func next32() throws -> UInt32 {
                        guard cursor + 4 <= value.count else { throw ArchiveReadFailure.invalidArchive }
                        defer { cursor += 4 }
                        return u32(value, cursor)
                    }
                    let uncompressed = needsUncompressed ? try next64() : nil
                    let compressed = needsCompressed ? try next64() : nil
                    let localOffset = needsLocalOffset ? try next64() : nil
                    let diskStart = needsDiskStart ? try next32() : nil
                    return Zip64Values(
                        uncompressed: uncompressed,
                        compressed: compressed,
                        localOffset: localOffset,
                        diskStart: diskStart
                    )
                }
                fieldIndex = valueStart + length
            }
            throw ArchiveReadFailure.invalidArchive
        }

        private static func dataDescriptorEnd(
            handle: FileHandle,
            compressedEnd: UInt64,
            usesDescriptor: Bool,
            usesZip64: Bool,
            crc32: UInt32,
            compressedSize: UInt64,
            uncompressedSize: UInt64
        ) throws -> UInt64 {
            guard usesDescriptor else { return compressedEnd }
            let prefix = try readBytes(handle: handle, offset: compressedEnd, count: 4)
            let hasSignature = u32(prefix, 0) == dataDescriptorSignature
            let descriptorOffset = compressedEnd + (hasSignature ? 4 : 0)
            let descriptorLength = usesZip64 ? 20 : 12
            let descriptor = try readBytes(
                handle: handle,
                offset: descriptorOffset,
                count: descriptorLength
            )
            let descriptorCompressed = usesZip64 ? u64(descriptor, 4) : UInt64(u32(descriptor, 4))
            let descriptorUncompressed = usesZip64 ? u64(descriptor, 12) : UInt64(u32(descriptor, 8))
            guard u32(descriptor, 0) == crc32,
                  descriptorCompressed == compressedSize,
                  descriptorUncompressed == uncompressedSize
            else {
                throw ArchiveReadFailure.invalidArchive
            }
            return descriptorOffset + UInt64(descriptorLength)
        }

        private static func decodePath(_ bytes: [UInt8], utf8: Bool) -> String? {
            let data = Data(bytes)
            if utf8 { return String(data: data, encoding: .utf8) }
            let codePage437 = String.Encoding(
                rawValue: CFStringConvertEncodingToNSStringEncoding(CFStringEncoding(0x0400))
            )
            return String(data: data, encoding: codePage437)
        }

        private static func readBytes(
            handle: FileHandle,
            offset: UInt64,
            count: Int
        ) throws -> [UInt8] {
            try handle.seek(toOffset: offset)
            guard let data = try handle.read(upToCount: count), data.count == count else {
                throw ArchiveReadFailure.invalidArchive
            }
            return Array(data)
        }

        private static func u16(_ bytes: [UInt8], _ offset: Int) -> UInt16 {
            UInt16(bytes[offset]) | UInt16(bytes[offset + 1]) << 8
        }

        private static func u32(_ bytes: [UInt8], _ offset: Int) -> UInt32 {
            UInt32(bytes[offset]) |
                UInt32(bytes[offset + 1]) << 8 |
                UInt32(bytes[offset + 2]) << 16 |
                UInt32(bytes[offset + 3]) << 24
        }

        private static func u64(_ bytes: [UInt8], _ offset: Int) -> UInt64 {
            UInt64(u32(bytes, offset)) | UInt64(u32(bytes, offset + 4)) << 32
        }

        private struct DirectoryLocation {
            let entryCount: UInt64
            let size: UInt64
            let offset: UInt64
        }

        private struct Zip64Values {
            var uncompressed: UInt64? = nil
            var compressed: UInt64? = nil
            var localOffset: UInt64? = nil
            var diskStart: UInt32? = nil
        }

        private static let endOfCentralDirectorySignature: UInt32 = 0x0605_4B50
        private static let centralHeaderSignature: UInt32 = 0x0201_4B50
        private static let localHeaderSignature: UInt32 = 0x0403_4B50
        private static let dataDescriptorSignature: UInt32 = 0x0807_4B50
        private static let zip64LocatorSignature: UInt32 = 0x0706_4B50
        private static let zip64RecordSignature: UInt32 = 0x0606_4B50
        private static let centralDigitalSignature: UInt32 = 0x0505_4B50
        private static let zip64ExtraIdentifier: UInt16 = 0x0001
        private static let encryptionFlag: UInt16 = 1 << 0
        private static let dataDescriptorFlag: UInt16 = 1 << 3
        private static let utf8NameFlag: UInt16 = 1 << 11
        private static let unixFileTypeMask: UInt32 = 0xF000
        private static let unixSymbolicLink: UInt32 = 0xA000
        private static let unixDirectory: UInt32 = 0x4000
        private static let unixHost: UInt16 = 3
        private static let osxHost: UInt16 = 19
        private static let endOfCentralDirectorySize = 22
        private static let centralHeaderSize = 46
        private static let localHeaderSize = 30
        private static let zip64LocatorSize = 20
        private static let zip64RecordMinimumSize = 56
        private static let maximumEndSearchBytes = 65_557
    }
}
