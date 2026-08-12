import Foundation
import Security
import XCTest
@testable import ErmaoLibrary

final class PersistenceTests: XCTestCase {
    func testKeychainCookiePayloadRoundTripIsProfileIsolated() throws {
        let service = "com.ermao.library.tests.\(UUID().uuidString)"
        let store = KeychainCookiePayloadStore(service: service)
        let firstProfile = UUID().uuidString
        let secondProfile = UUID().uuidString
        defer {
            try? store.clear(profileID: firstProfile)
            try? store.clear(profileID: secondProfile)
        }

        try store.save(profileID: firstProfile, payload: "{\"cookie\":\"first\"}")
        try store.save(profileID: secondProfile, payload: "{\"cookie\":\"second\"}")

        XCTAssertEqual(try store.load(profileID: firstProfile), "{\"cookie\":\"first\"}")
        XCTAssertEqual(try store.load(profileID: secondProfile), "{\"cookie\":\"second\"}")

        var attributesResult: CFTypeRef?
        let attributesStatus = SecItemCopyMatching(
            [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecAttrAccount as String: secondProfile,
                kSecReturnAttributes as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
            ] as CFDictionary,
            &attributesResult
        )
        XCTAssertEqual(attributesStatus, errSecSuccess)
        let attributes = try XCTUnwrap(attributesResult as? [String: Any])
        XCTAssertEqual(
            attributes[kSecAttrAccessible as String] as? String,
            kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String
        )

        try store.clear(profileID: firstProfile)
        XCTAssertNil(try store.load(profileID: firstProfile))
        XCTAssertEqual(try store.load(profileID: secondProfile), "{\"cookie\":\"second\"}")
    }

    func testServerCredentialsRoundTripInDeviceOnlyKeychain() throws {
        let service = "com.ermao.library.credentials.tests.\(UUID().uuidString)"
        let store = KeychainServerCredentialStore(service: service)
        let profileID = UUID().uuidString
        defer { try? store.clear(profileID: profileID) }
        let credentials = SavedServerCredentials(
            email: "reader@example.com",
            password: "private-password"
        )

        try store.save(profileID: profileID, credentials: credentials)

        XCTAssertEqual(try store.load(profileID: profileID), credentials)
        try store.clear(profileID: profileID)
        XCTAssertNil(try store.load(profileID: profileID))
    }

    func testProfileStoreRoundTripsOpaqueVersionedAggregate() throws {
        let suiteName = "com.ermao.library.tests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = UserDefaultsServerProfileStore(defaults: defaults)
        let payload = #"{"schemaVersion":2,"activeProfileId":"first","profiles":[{"id":"first"}]}"#
        try store.saveProfiles(payload: payload)
        XCTAssertEqual(store.loadProfiles(), payload)
        XCTAssertThrowsError(try store.saveProfiles(payload: "not-json")) { error in
            XCTAssertEqual(error as? UserDefaultsPayloadStoreError, .invalidJSON)
        }
        XCTAssertEqual(store.loadProfiles(), payload)
    }

    func testOfflineEntitlementStoreIsIndependentFromProfiles() throws {
        let suiteName = "com.ermao.library.tests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let profiles = UserDefaultsServerProfileStore(defaults: defaults)
        let entitlements = UserDefaultsOfflineEntitlementStore(defaults: defaults)

        try profiles.saveProfiles(payload: #"{"schemaVersion":2,"profiles":[]}"#)
        let entitlementPayload = #"{"profile-a":{"userId":"user-a","expiresAt":42}}"#
        try entitlements.saveEntitlements(payload: entitlementPayload)

        XCTAssertEqual(entitlements.loadEntitlements(), entitlementPayload)
        entitlements.clear()
        XCTAssertNil(entitlements.loadEntitlements())
        XCTAssertNotNil(profiles.loadProfiles())
    }
}
