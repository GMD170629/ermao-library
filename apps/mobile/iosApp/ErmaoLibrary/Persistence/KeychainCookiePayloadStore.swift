import Foundation
import Security

enum KeychainCookieStoreError: Error, Equatable {
    case unexpectedStatus(OSStatus)
    case invalidPayload
}

struct SavedServerCredentials: Codable, Equatable, Sendable {
    let email: String
    let password: String
}

protocol ServerCredentialStore: AnyObject {
    func load(profileID: String) throws -> SavedServerCredentials?
    func loadEmail(profileID: String) throws -> String?
    func save(profileID: String, credentials: SavedServerCredentials) throws
    func clear(profileID: String) throws
}

extension ServerCredentialStore {
    func loadEmail(profileID: String) throws -> String? {
        try load(profileID: profileID)?.email
    }
}

/// Keeps the explicitly remembered login form isolated per server profile. The
/// password is device-only Keychain data and never enters UserDefaults or logs.
final class KeychainServerCredentialStore: ServerCredentialStore {
    private let service: String

    init(service: String = "com.ermao.library.server-credentials.v1") {
        self.service = service
    }

    func load(profileID: String) throws -> SavedServerCredentials? {
        var result: CFTypeRef?
        let status = SecItemCopyMatching(
            query(profileID: profileID)
                .merging([
                    kSecReturnData as String: true,
                    kSecMatchLimit as String: kSecMatchLimitOne,
                ]) { _, newValue in newValue } as CFDictionary,
            &result
        )
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else {
            throw KeychainCookieStoreError.unexpectedStatus(status)
        }
        guard let data = result as? Data else {
            throw KeychainCookieStoreError.invalidPayload
        }
        do {
            return try JSONDecoder().decode(SavedServerCredentials.self, from: data)
        } catch {
            throw KeychainCookieStoreError.invalidPayload
        }
    }

    func save(profileID: String, credentials: SavedServerCredentials) throws {
        let data = try JSONEncoder().encode(credentials)
        let updateStatus = SecItemUpdate(
            query(profileID: profileID) as CFDictionary,
            [kSecValueData as String: data] as CFDictionary
        )
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw KeychainCookieStoreError.unexpectedStatus(updateStatus)
        }
        let addStatus = SecItemAdd(
            query(profileID: profileID)
                .merging([
                    kSecValueData as String: data,
                    kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                ]) { _, newValue in newValue } as CFDictionary,
            nil
        )
        guard addStatus == errSecSuccess else {
            throw KeychainCookieStoreError.unexpectedStatus(addStatus)
        }
    }

    func clear(profileID: String) throws {
        let status = SecItemDelete(query(profileID: profileID) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainCookieStoreError.unexpectedStatus(status)
        }
    }

    private func query(profileID: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: profileID,
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any,
        ]
    }
}

/// Stores the KMP cookie jar's opaque serialized payload. Cookie values are never
/// decoded, copied into app session state, UserDefaults, analytics, or logs here.
final class KeychainCookiePayloadStore {
    private let service: String

    init(service: String = "com.ermao.library.session-cookies.v1") {
        self.service = service
    }

    func load(profileID: String) throws -> String? {
        var result: CFTypeRef?
        let status = SecItemCopyMatching(
            baseQuery(profileID: profileID)
                .merging([
                    kSecReturnData as String: true,
                    kSecMatchLimit as String: kSecMatchLimitOne,
                ]) { _, newValue in newValue } as CFDictionary,
            &result
        )
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess else {
            throw KeychainCookieStoreError.unexpectedStatus(status)
        }
        guard
            let data = result as? Data,
            let payload = String(data: data, encoding: .utf8)
        else {
            throw KeychainCookieStoreError.invalidPayload
        }
        return payload
    }

    func save(profileID: String, payload: String) throws {
        let data = Data(payload.utf8)
        let updateStatus = SecItemUpdate(
            baseQuery(profileID: profileID) as CFDictionary,
            [kSecValueData as String: data] as CFDictionary
        )
        if updateStatus == errSecSuccess {
            return
        }
        guard updateStatus == errSecItemNotFound else {
            throw KeychainCookieStoreError.unexpectedStatus(updateStatus)
        }
        let addStatus = SecItemAdd(
            baseQuery(profileID: profileID)
                .merging([
                    kSecValueData as String: data,
                    kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                ]) { _, newValue in newValue } as CFDictionary,
            nil
        )
        guard addStatus == errSecSuccess else {
            throw KeychainCookieStoreError.unexpectedStatus(addStatus)
        }
    }

    func clear(profileID: String) throws {
        let status = SecItemDelete(baseQuery(profileID: profileID) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainCookieStoreError.unexpectedStatus(status)
        }
    }

    private func baseQuery(profileID: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: profileID,
            kSecAttrSynchronizable as String: kCFBooleanFalse as Any,
        ]
    }
}
