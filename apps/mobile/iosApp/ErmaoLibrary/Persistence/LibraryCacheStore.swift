import Foundation
@preconcurrency import ErmaoShared

actor LibraryCacheStore {
    static let freshnessInterval: TimeInterval = 5 * 60
    private static let maximumQueryIdentities = 20
    private static let maximumPagesPerQuery = 3
    private static let maximumCoverEntries = 200
    private static let maximumCoverBytes: Int64 = 100 * 1_024 * 1_024

    private struct CacheRecord: Codable {
        let key: String
        var createdAt: Date
        var lastAccessedAt: Date
        var byteCount: Int64
    }

    private struct CacheIndex: Codable {
        var records: [String: CacheRecord] = [:]
    }

    private let rootDirectory: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(rootDirectory: URL? = nil) {
        if let rootDirectory {
            self.rootDirectory = rootDirectory
        } else {
            let applicationSupport = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
            self.rootDirectory = applicationSupport.appendingPathComponent(
                "com.ermao.library/content-cache-v1",
                isDirectory: true
            )
        }
    }

    func load<Value: Decodable & Sendable>(
        _ type: Value.Type,
        namespace: String,
        key: String
    ) throws -> Value? {
        let url = cacheURL(namespace: namespace, key: key)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let value = try decoder.decode(Value.self, from: Data(contentsOf: url))
        var index = try loadIndex(namespace: namespace)
        let now = Date()
        if var record = index.records[key] {
            record.lastAccessedAt = now
            index.records[key] = record
        } else {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            index.records[key] = CacheRecord(
                key: key,
                createdAt: attributes[.creationDate] as? Date ?? now,
                lastAccessedAt: now,
                byteCount: (attributes[.size] as? NSNumber)?.int64Value ?? 0
            )
        }
        try saveIndex(index, namespace: namespace)
        return value
    }

    func save<Value: Encodable & Sendable>(
        _ value: Value,
        namespace: String,
        key: String
    ) throws {
        let namespaceDirectory = cacheURL(namespace: namespace, key: nil)
        try FileManager.default.createDirectory(
            at: namespaceDirectory,
            withIntermediateDirectories: true
        )
        let encoded = try encoder.encode(value)
        try encoded.write(to: cacheURL(namespace: namespace, key: key), options: .atomic)
        let now = Date()
        var index = try loadIndex(namespace: namespace)
        index.records[key] = CacheRecord(
            key: key,
            createdAt: now,
            lastAccessedAt: now,
            byteCount: Int64(encoded.count)
        )
        try prune(&index, namespace: namespace)
        try saveIndex(index, namespace: namespace)
    }

    func isFresh(namespace: String, key: String, now: Date = Date()) throws -> Bool {
        let record = try loadIndex(namespace: namespace).records[key]
        return record.map { now.timeIntervalSince($0.createdAt) <= Self.freshnessInterval } ?? false
    }

    func removeNamespace(_ namespace: String) throws {
        let url = cacheURL(namespace: namespace, key: nil)
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try FileManager.default.removeItem(at: url)
    }

    private func cacheURL(namespace: String, key: String?) -> URL {
        let namespaceURL = rootDirectory.appendingPathComponent(stableFileName(namespace), isDirectory: true)
        guard let key else { return namespaceURL }
        return namespaceURL.appendingPathComponent(stableFileName(key) + ".json", isDirectory: false)
    }

    private func indexURL(namespace: String) -> URL {
        cacheURL(namespace: namespace, key: nil).appendingPathComponent("_index.json")
    }

    private func loadIndex(namespace: String) throws -> CacheIndex {
        let url = indexURL(namespace: namespace)
        guard FileManager.default.fileExists(atPath: url.path) else { return CacheIndex() }
        return try decoder.decode(CacheIndex.self, from: Data(contentsOf: url))
    }

    private func saveIndex(_ index: CacheIndex, namespace: String) throws {
        try encoder.encode(index).write(to: indexURL(namespace: namespace), options: .atomic)
    }

    private func prune(_ index: inout CacheIndex, namespace: String) throws {
        try pruneQueryPages(&index, namespace: namespace)
        try pruneCovers(&index, namespace: namespace)
    }

    private func pruneQueryPages(_ index: inout CacheIndex, namespace: String) throws {
        let queryRecords = index.records.values.filter { queryIdentity(for: $0.key) != nil }
        let grouped = Dictionary(grouping: queryRecords) { queryIdentity(for: $0.key) ?? $0.key }
        for records in grouped.values {
            for record in records.sorted(by: { $0.lastAccessedAt > $1.lastAccessedAt }).dropFirst(Self.maximumPagesPerQuery) {
                try remove(record, from: &index, namespace: namespace)
            }
        }
        let retained = index.records.values.filter { queryIdentity(for: $0.key) != nil }
        let identities = Dictionary(grouping: retained) { queryIdentity(for: $0.key) ?? $0.key }
            .map { identity, records in
                (identity, records.map(\.lastAccessedAt).max() ?? .distantPast)
            }
            .sorted { $0.1 > $1.1 }
        for (identity, _) in identities.dropFirst(Self.maximumQueryIdentities) {
            for record in Array(index.records.values) where queryIdentity(for: record.key) == identity {
                try remove(record, from: &index, namespace: namespace)
            }
        }
    }

    private func pruneCovers(_ index: inout CacheIndex, namespace: String) throws {
        let covers = index.records.values
            .filter { $0.key.hasPrefix("cover|") }
            .sorted { $0.lastAccessedAt > $1.lastAccessedAt }
        var retainedBytes: Int64 = 0
        var retainedCount = 0
        for record in covers {
            retainedCount += 1
            retainedBytes += record.byteCount
            if retainedCount > Self.maximumCoverEntries || retainedBytes > Self.maximumCoverBytes {
                try remove(record, from: &index, namespace: namespace)
            }
        }
    }

    private func queryIdentity(for key: String) -> String? {
        guard key.hasPrefix("library|") || key.hasPrefix("facet|") else { return nil }
        guard let separator = key.lastIndex(of: "|") else { return nil }
        return String(key[..<separator])
    }

    private func remove(_ record: CacheRecord, from index: inout CacheIndex, namespace: String) throws {
        let url = cacheURL(namespace: namespace, key: record.key)
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
        index.records.removeValue(forKey: record.key)
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

extension LibraryCacheStore: PrivateContentCacheClearing {}

final class LibrarySnapshotFilePayloadStore: LibrarySnapshotPayloadStore, @unchecked Sendable {
    private let rootDirectory: URL
    private let lock = NSLock()

    init(rootDirectory: URL? = nil) {
        if let rootDirectory {
            self.rootDirectory = rootDirectory
        } else {
            let applicationSupport = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
            self.rootDirectory = applicationSupport.appendingPathComponent(
                "com.ermao.library/content-cache-v1",
                isDirectory: true
            )
        }
    }

    func loadLibrarySnapshotPayload(namespaceKey: String, payloadKey: String) throws -> PlatformStoragePayload {
        try locked {
            let source = payloadURL(namespaceKey: namespaceKey, payloadKey: payloadKey)
            guard FileManager.default.fileExists(atPath: source.path) else {
                return PlatformStoragePayload(value: nil)
            }
            return PlatformStoragePayload(value: try String(contentsOf: source, encoding: .utf8))
        }
    }

    func saveLibrarySnapshotPayload(namespaceKey: String, payloadKey: String, payload: String) throws {
        try locked {
            let destination = payloadURL(namespaceKey: namespaceKey, payloadKey: payloadKey)
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data(payload.utf8).write(to: destination, options: .atomic)
        }
    }

    func removeLibrarySnapshotPayload(namespaceKey: String, payloadKey: String) throws {
        try locked {
            let target = payloadURL(namespaceKey: namespaceKey, payloadKey: payloadKey)
            if FileManager.default.fileExists(atPath: target.path) {
                try FileManager.default.removeItem(at: target)
            }
        }
    }

    func clearLibrarySnapshotPayloads(namespaceKey: String) throws {
        try locked {
            let target = namespaceURL(namespaceKey)
            if FileManager.default.fileExists(atPath: target.path) {
                try FileManager.default.removeItem(at: target)
            }
        }
    }

    private func payloadURL(namespaceKey: String, payloadKey: String) -> URL {
        namespaceURL(namespaceKey).appendingPathComponent(
            "kmp-\(stableFileName(payloadKey)).json",
            isDirectory: false
        )
    }

    private func namespaceURL(_ namespaceKey: String) -> URL {
        rootDirectory.appendingPathComponent(stableFileName(namespaceKey), isDirectory: true)
    }

    private func stableFileName(_ value: String) -> String {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 1_099_511_628_211
        }
        return String(hash, radix: 16)
    }

    private func locked<Value>(_ operation: () throws -> Value) rethrows -> Value {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}
