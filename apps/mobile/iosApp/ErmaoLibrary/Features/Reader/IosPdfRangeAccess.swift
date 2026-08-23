import CryptoKit
import Foundation
@preconcurrency import ErmaoShared

enum IosPdfRangePolicy {
    static let chunkBytes: Int64 = 256 * 1_024
    static let maximumRequestBytes: Int64 = 1_024 * 1_024
    static let maximumConcurrentRequests = 2
    static let maximumDocumentCacheBytes: Int64 = 64 * 1_024 * 1_024
    static let maximumNamespaceCacheBytes: Int64 = 512 * 1_024 * 1_024
    static let maximumMemoryCacheBytes: Int64 = 8 * 1_024 * 1_024

    static func alignedRanges(
        offset: Int64,
        length: Int64,
        resourceLength: Int64,
        isChunkCached: (Int64) -> Bool
    ) throws -> [Range<Int64>] {
        guard offset >= 0, length > 0, offset <= resourceLength,
              length <= resourceLength - offset else {
            throw IosReaderFailure(code: .pdfRangeInvalid)
        }
        let firstChunk = offset / chunkBytes
        let lastChunk = (offset + length - 1) / chunkBytes
        var result: [Range<Int64>] = []
        var pendingStart: Int64?
        var pendingEnd: Int64 = 0
        for chunk in firstChunk ... lastChunk {
            let begin = chunk * chunkBytes
            let end = min(resourceLength, begin + chunkBytes)
            if isChunkCached(chunk) {
                if let start = pendingStart {
                    result.append(start ..< pendingEnd)
                    pendingStart = nil
                }
                continue
            }
            if let start = pendingStart,
               begin == pendingEnd,
               end - start <= maximumRequestBytes {
                pendingEnd = end
            } else {
                if let start = pendingStart { result.append(start ..< pendingEnd) }
                pendingStart = begin
                pendingEnd = end
            }
        }
        if let start = pendingStart { result.append(start ..< pendingEnd) }
        return result
    }
}

struct IosPdfRangeCacheIdentity: Sendable {
    let namespaceKey: String
    let documentKey: String

    init(source: ErmaoShared.RemoteByteRangeReaderSource) {
        namespaceKey = Self.digest(
            "\(source.namespace.serverIdentity)|\(source.namespace.userId)|\(source.namespace.authorizationVersion)"
        )
        documentKey = Self.digest(source.resourceId)
    }

    private static func digest(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

final class IosPdfRangeCache: @unchecked Sendable {
    private struct MemoryEntry {
        let data: Data
        var lastAccess: UInt64
    }

    private let root: URL
    private let files: FileManager
    private let lock = NSLock()
    private var memory: [String: MemoryEntry] = [:]
    private var memoryBytes: Int64 = 0
    private var accessClock: UInt64 = 0

    init(root: URL? = nil, files: FileManager = .default) throws {
        self.files = files
        if let root {
            self.root = root
        } else {
            let caches = try files.url(
                for: .cachesDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            self.root = caches.appendingPathComponent("reader/pdf-range-v1", isDirectory: true)
        }
        try files.createDirectory(at: self.root, withIntermediateDirectories: true)
    }

    func isChunkCached(_ chunkIndex: Int64, identity: IosPdfRangeCacheIdentity) -> Bool {
        lock.withLock {
            let key = memoryKey(identity: identity, chunkIndex: chunkIndex)
            if memory[key] != nil { return true }
            return files.fileExists(atPath: chunkURL(identity: identity, chunkIndex: chunkIndex).path)
        }
    }

    func readCached(
        identity: IosPdfRangeCacheIdentity,
        offset: Int64,
        length: Int
    ) -> Data? {
        guard offset >= 0, length > 0 else { return nil }
        return lock.withLock {
            var result = Data(capacity: length)
            var cursor = offset
            let end = offset + Int64(length)
            while cursor < end {
                let chunkIndex = cursor / IosPdfRangePolicy.chunkBytes
                guard let chunk = readChunkLocked(identity: identity, chunkIndex: chunkIndex) else { return nil }
                let localOffset = Int(cursor % IosPdfRangePolicy.chunkBytes)
                let count = min(chunk.count - localOffset, Int(end - cursor))
                guard count > 0 else { return nil }
                result.append(chunk.subdata(in: localOffset ..< localOffset + count))
                cursor += Int64(count)
            }
            return result
        }
    }

    func writeAlignedRange(
        identity: IosPdfRangeCacheIdentity,
        offset: Int64,
        bytes: Data
    ) throws {
        guard offset >= 0,
              offset % IosPdfRangePolicy.chunkBytes == 0,
              !bytes.isEmpty,
              Int64(bytes.count) <= IosPdfRangePolicy.maximumRequestBytes else {
            throw IosReaderFailure(code: .pdfRangeInvalid)
        }
        try lock.withLock {
            let document = documentURL(identity: identity)
            try files.createDirectory(at: document, withIntermediateDirectories: true)
            var consumed = 0
            while consumed < bytes.count {
                let chunkOffset = offset + Int64(consumed)
                let chunkIndex = chunkOffset / IosPdfRangePolicy.chunkBytes
                let count = min(Int(IosPdfRangePolicy.chunkBytes), bytes.count - consumed)
                let chunk = bytes.subdata(in: consumed ..< consumed + count)
                let target = chunkURL(identity: identity, chunkIndex: chunkIndex)
                let temporary = document.appendingPathComponent(".\(UUID().uuidString).tmp")
                do {
                    try chunk.write(to: temporary, options: .atomic)
                    if files.fileExists(atPath: target.path) { try files.removeItem(at: target) }
                    try files.moveItem(at: temporary, to: target)
                    storeMemoryLocked(chunk, key: memoryKey(identity: identity, chunkIndex: chunkIndex))
                } catch {
                    try? files.removeItem(at: temporary)
                    throw IosReaderFailure(code: .pdfCacheIO)
                }
                consumed += count
            }
            try evictLocked(directory: document, limit: IosPdfRangePolicy.maximumDocumentCacheBytes)
            try evictLocked(
                directory: namespaceURL(identity: identity),
                limit: IosPdfRangePolicy.maximumNamespaceCacheBytes
            )
        }
    }

    func clearNamespace(_ namespaceKey: String) throws {
        try lock.withLock {
            memory = memory.filter { !$0.key.hasPrefix(namespaceKey + "/") }
            memoryBytes = memory.values.reduce(0) { $0 + Int64($1.data.count) }
            let target = root.appendingPathComponent(namespaceKey, isDirectory: true)
            if files.fileExists(atPath: target.path) { try files.removeItem(at: target) }
        }
    }

    func activateNamespace(_ identity: IosPdfRangeCacheIdentity) throws {
        try lock.withLock {
            for candidate in try files.contentsOfDirectory(
                at: root,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            ) where candidate.lastPathComponent != identity.namespaceKey {
                if try candidate.resourceValues(forKeys: [.isDirectoryKey]).isDirectory == true {
                    try files.removeItem(at: candidate)
                }
            }
            memory = memory.filter { $0.key.hasPrefix(identity.namespaceKey + "/") }
            memoryBytes = memory.values.reduce(0) { $0 + Int64($1.data.count) }
        }
    }

    /// Remove the range cache for exactly one Reader namespace. The previous
    /// logout path used `clearAll`, which could delete another account's PDF
    /// ranges on a shared installation.
    static func clearNamespace(_ namespace: String, files: FileManager = .default) throws {
        let caches = try files.url(
            for: .cachesDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let root = caches.appendingPathComponent("reader/pdf-range-v1", isDirectory: true)
        let namespaceKey = SHA256.hash(data: Data(namespace.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        let target = root.appendingPathComponent(namespaceKey, isDirectory: true)
        if files.fileExists(atPath: target.path) { try files.removeItem(at: target) }
    }

    private func readChunkLocked(identity: IosPdfRangeCacheIdentity, chunkIndex: Int64) -> Data? {
        let key = memoryKey(identity: identity, chunkIndex: chunkIndex)
        if var entry = memory[key] {
            accessClock &+= 1
            entry.lastAccess = accessClock
            memory[key] = entry
            return entry.data
        }
        let url = chunkURL(identity: identity, chunkIndex: chunkIndex)
        guard let data = try? Data(contentsOf: url, options: .mappedIfSafe) else { return nil }
        try? files.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
        storeMemoryLocked(data, key: key)
        return data
    }

    private func storeMemoryLocked(_ data: Data, key: String) {
        if let previous = memory.removeValue(forKey: key) { memoryBytes -= Int64(previous.data.count) }
        accessClock &+= 1
        memory[key] = MemoryEntry(data: data, lastAccess: accessClock)
        memoryBytes += Int64(data.count)
        while memoryBytes > IosPdfRangePolicy.maximumMemoryCacheBytes,
              let oldest = memory.min(by: { $0.value.lastAccess < $1.value.lastAccess }) {
            memory.removeValue(forKey: oldest.key)
            memoryBytes -= Int64(oldest.value.data.count)
        }
    }

    private func evictLocked(directory: URL, limit: Int64) throws {
        guard files.fileExists(atPath: directory.path) else { return }
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]
        var entries = try files.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ).flatMap { child -> [(URL, URLResourceValues)] in
            let values = try child.resourceValues(forKeys: keys)
            if values.isRegularFile == true { return [(child, values)] }
            return try files.contentsOfDirectory(
                at: child,
                includingPropertiesForKeys: Array(keys),
                options: [.skipsHiddenFiles]
            ).compactMap { url in
                let nested = try url.resourceValues(forKeys: keys)
                return nested.isRegularFile == true ? (url, nested) : nil
            }
        }
        var total = entries.reduce(Int64(0)) { $0 + Int64($1.1.fileSize ?? 0) }
        entries.sort { ($0.1.contentModificationDate ?? .distantPast) < ($1.1.contentModificationDate ?? .distantPast) }
        for (url, values) in entries where total > limit {
            try files.removeItem(at: url)
            total -= Int64(values.fileSize ?? 0)
        }
    }

    private func namespaceURL(identity: IosPdfRangeCacheIdentity) -> URL {
        root.appendingPathComponent(identity.namespaceKey, isDirectory: true)
    }

    private func documentURL(identity: IosPdfRangeCacheIdentity) -> URL {
        namespaceURL(identity: identity).appendingPathComponent(identity.documentKey, isDirectory: true)
    }

    private func chunkURL(identity: IosPdfRangeCacheIdentity, chunkIndex: Int64) -> URL {
        documentURL(identity: identity).appendingPathComponent(String(format: "%016llx.chunk", chunkIndex))
    }

    private func memoryKey(identity: IosPdfRangeCacheIdentity, chunkIndex: Int64) -> String {
        "\(identity.namespaceKey)/\(identity.documentKey)/\(chunkIndex)"
    }
}

final class IosPdfRangeHintQueue: @unchecked Sendable {
    private let lock = NSLock()
    private var ranges: [Range<Int64>] = []

    func append(offset: Int64, length: Int64) {
        guard offset >= 0, length > 0 else { return }
        lock.withLock { ranges.append(offset ..< offset + length) }
    }

    func takeAll() -> [Range<Int64>] {
        lock.withLock {
            defer { ranges.removeAll(keepingCapacity: true) }
            return ranges
        }
    }
}

actor IosPdfRangeLoader {
    let source: ErmaoShared.RemoteByteRangeReaderSource
    let identity: IosPdfRangeCacheIdentity
    let cache: IosPdfRangeCache
    private let server: any ErmaoShared.PdfRangeServerPort
    private var probed = false

    init(
        source: ErmaoShared.RemoteByteRangeReaderSource,
        cache: IosPdfRangeCache,
        server: any ErmaoShared.PdfRangeServerPort
    ) {
        self.source = source
        identity = IosPdfRangeCacheIdentity(source: source)
        self.cache = cache
        self.server = server
    }

    func ensureAvailable() async throws {
        guard !probed else { return }
        try cache.activateNamespace(identity)
        let result = try await server.probe(source: source)
        if result is ErmaoShared.PdfRangeProbeResultAvailable {
            probed = true
            return
        }
        guard let failure = result as? ErmaoShared.PdfRangeProbeResultFailure else {
            throw IosReaderFailure(code: .networkUnavailable)
        }
        throw IosReaderFailure(code: IosReaderFailureCode(pdfCode: failure.code))
    }

    func load(_ requested: [Range<Int64>]) async throws {
        try await ensureAvailable()
        var missing: [Range<Int64>] = []
        for range in requested {
            missing += try IosPdfRangePolicy.alignedRanges(
                offset: range.lowerBound,
                length: Int64(range.count),
                resourceLength: source.expectedSizeBytes,
                isChunkCached: { cache.isChunkCached($0, identity: identity) }
            )
        }
        var cursor = 0
        while cursor < missing.count {
            let end = min(missing.count, cursor + IosPdfRangePolicy.maximumConcurrentRequests)
            let batch = Array(missing[cursor ..< end])
            try await withThrowingTaskGroup(of: Void.self) { group in
                for range in batch {
                    group.addTask { [source, server, cache, identity] in
                        let wireRange = ErmaoShared.PdfByteRange(
                            begin: range.lowerBound,
                            endExclusive: range.upperBound
                        )
                        let result = try await server.read(source: source, range: wireRange)
                        guard let content = result as? ErmaoShared.PdfRangeReadResultContent else {
                            let failure = result as? ErmaoShared.PdfRangeReadResultFailure
                            throw IosReaderFailure(
                                code: failure.map { IosReaderFailureCode(pdfCode: $0.code) }
                                    ?? .networkUnavailable
                            )
                        }
                        let bytes = Data((0 ..< Int(content.bytes.size)).map {
                            UInt8(bitPattern: content.bytes.get(index: Int32($0)))
                        })
                        guard bytes.count == range.count else {
                            throw IosReaderFailure(code: .pdfRangeInvalid)
                        }
                        try cache.writeAlignedRange(identity: identity, offset: range.lowerBound, bytes: bytes)
                    }
                }
                try await group.waitForAll()
            }
            cursor = end
        }
    }
}

extension IosReaderFailureCode {
    init(pdfCode: ErmaoShared.ReaderErrorCode) {
        self = IosReaderFailureCode(rawValue: pdfCode.wireValue) ?? .engineError
    }
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
