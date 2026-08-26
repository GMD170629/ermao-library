import Foundation

actor AuthenticatedCoverCache {
    private static let maximumEntries = 200
    private static let maximumBytes: Int64 = 100 * 1_024 * 1_024

    private struct CacheRecord: Codable {
        let key: String
        var lastAccessedAt: Date
        var byteCount: Int64
    }

    private struct CacheIndex: Codable {
        var records: [String: CacheRecord] = [:]
    }

    private let rootDirectory: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(rootDirectory: URL? = nil, legacyRootDirectory: URL? = nil) {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        self.rootDirectory = rootDirectory ?? applicationSupport.appendingPathComponent(
            "com.ermao.library/authenticated-cover-cache-v1",
            isDirectory: true
        )
        let legacy = legacyRootDirectory ?? (rootDirectory == nil
            ? applicationSupport.appendingPathComponent("com.ermao.library/content-cache-v1", isDirectory: true)
            : nil)
        if let legacy, legacy != self.rootDirectory {
            try? FileManager.default.removeItem(at: legacy)
        }
    }

    func load(namespace: String, key: String) throws -> Data? {
        try validateCoverKey(key)
        let url = cacheURL(namespace: namespace, key: key)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let data = try Data(contentsOf: url)
        var index = try loadIndex(namespace: namespace)
        index.records[key] = CacheRecord(
            key: key,
            lastAccessedAt: Date(),
            byteCount: Int64(data.count)
        )
        try saveIndex(index, namespace: namespace)
        return data
    }

    func save(_ data: Data, namespace: String, key: String) throws {
        try validateCoverKey(key)
        let namespaceDirectory = cacheURL(namespace: namespace, key: nil)
        try FileManager.default.createDirectory(at: namespaceDirectory, withIntermediateDirectories: true)
        try data.write(to: cacheURL(namespace: namespace, key: key), options: .atomic)
        var index = try loadIndex(namespace: namespace)
        index.records[key] = CacheRecord(
            key: key,
            lastAccessedAt: Date(),
            byteCount: Int64(data.count)
        )
        try prune(&index, namespace: namespace)
        try saveIndex(index, namespace: namespace)
    }

    func removeNamespace(_ namespace: String) throws {
        let url = cacheURL(namespace: namespace, key: nil)
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try FileManager.default.removeItem(at: url)
    }

    func remove(namespace: String, key: String) throws {
        try validateCoverKey(key)
        var index = try loadIndex(namespace: namespace)
        if let record = index.records[key] {
            try remove(record, from: &index, namespace: namespace)
            try saveIndex(index, namespace: namespace)
            return
        }
        let url = cacheURL(namespace: namespace, key: key)
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }

    private func validateCoverKey(_ key: String) throws {
        guard key.hasPrefix("cover|") else { throw AuthenticatedCoverCacheError.invalidKey }
    }

    private func cacheURL(namespace: String, key: String?) -> URL {
        let namespaceURL = rootDirectory.appendingPathComponent(stableFileName(namespace), isDirectory: true)
        guard let key else { return namespaceURL }
        return namespaceURL.appendingPathComponent(stableFileName(key) + ".bin", isDirectory: false)
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
        let records = index.records.values.sorted { $0.lastAccessedAt > $1.lastAccessedAt }
        var retainedBytes: Int64 = 0
        var retainedCount = 0
        for record in records {
            retainedCount += 1
            retainedBytes += record.byteCount
            if retainedCount > Self.maximumEntries || retainedBytes > Self.maximumBytes {
                try remove(record, from: &index, namespace: namespace)
            }
        }
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

enum AuthenticatedCoverCacheError: Error {
    case invalidKey
}

extension AuthenticatedCoverCache: PrivateContentCacheClearing {}
