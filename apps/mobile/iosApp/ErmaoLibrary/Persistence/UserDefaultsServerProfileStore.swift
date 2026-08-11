import Foundation

final class UserDefaultsServerProfileStore {
    private let defaults: UserDefaults
    private let storageKey: String
    private let lock = NSLock()

    init(
        defaults: UserDefaults = .standard,
        storageKey: String = "com.ermao.library.server-profiles.v1"
    ) {
        self.defaults = defaults
        self.storageKey = storageKey
    }

    func loadProfiles() throws -> String? {
        lock.lock()
        defer { lock.unlock() }
        return defaults.string(forKey: storageKey)
    }

    func saveProfiles(payload: String) throws {
        try validateJSONPayload(payload)
        lock.lock()
        defer { lock.unlock() }
        defaults.set(payload, forKey: storageKey)
        guard defaults.string(forKey: storageKey) == payload else {
            throw UserDefaultsPayloadStoreError.persistenceFailed
        }
    }

    func clear() {
        lock.lock()
        defer { lock.unlock() }
        defaults.removeObject(forKey: storageKey)
    }
}

final class UserDefaultsOfflineEntitlementStore {
    private let defaults: UserDefaults
    private let storageKey: String
    private let lock = NSLock()

    init(
        defaults: UserDefaults = .standard,
        storageKey: String = "com.ermao.library.offline-entitlements.v1"
    ) {
        self.defaults = defaults
        self.storageKey = storageKey
    }

    func loadEntitlements() throws -> String? {
        lock.lock()
        defer { lock.unlock() }
        return defaults.string(forKey: storageKey)
    }

    func saveEntitlements(payload: String) throws {
        try validateJSONPayload(payload)
        lock.lock()
        defer { lock.unlock() }
        defaults.set(payload, forKey: storageKey)
        guard defaults.string(forKey: storageKey) == payload else {
            throw UserDefaultsPayloadStoreError.persistenceFailed
        }
    }

    func clear() {
        lock.lock()
        defer { lock.unlock() }
        defaults.removeObject(forKey: storageKey)
    }
}

enum UserDefaultsPayloadStoreError: Error, Equatable {
    case invalidJSON
    case persistenceFailed
}

private func validateJSONPayload(_ payload: String) throws {
    guard
        let data = payload.data(using: .utf8),
        (try? JSONSerialization.jsonObject(with: data)) != nil
    else {
        throw UserDefaultsPayloadStoreError.invalidJSON
    }
}
