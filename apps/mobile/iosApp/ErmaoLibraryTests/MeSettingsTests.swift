import Foundation
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import ErmaoLibrary

final class AvatarImageProcessorTests: XCTestCase {
    func testJPEGIsReencodedWithoutSourceMetadataAndWithinLimit() throws {
        let source = try makeImageData(
            type: .jpeg,
            width: 80,
            height: 80,
            properties: [
                kCGImagePropertyExifDictionary: [
                    kCGImagePropertyExifUserComment: "private-location-adjacent-metadata",
                ],
                kCGImagePropertyTIFFDictionary: [
                    kCGImagePropertyTIFFMake: "Sensitive Camera",
                ],
            ]
        )

        let result = try AvatarImageProcessor().process(
            data: source,
            declaredContentTypeIdentifier: UTType.jpeg.identifier
        )

        XCTAssertEqual(result.mimeType, .jpeg)
        XCTAssertLessThanOrEqual(result.data.count, AvatarImageProcessor.defaultMaximumBytes)
        XCTAssertNotEqual(result.data, source)
        let properties = try imageProperties(result.data)
        let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any]
        XCTAssertNil(exif?[kCGImagePropertyExifUserComment])
        let tiff = properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any]
        XCTAssertNil(tiff?[kCGImagePropertyTIFFMake])
    }

    func testPNGIsReencodedAndRemainsPNGWhenWithinLimit() throws {
        let source = try makeImageData(
            type: .png,
            width: 32,
            height: 32,
            properties: [
                kCGImagePropertyPNGDictionary: [
                    kCGImagePropertyPNGDescription: "private-description",
                ],
            ]
        )
        let result = try AvatarImageProcessor().process(
            data: source,
            declaredContentTypeIdentifier: UTType.png.identifier
        )

        XCTAssertEqual(result.mimeType, .png)
        XCTAssertLessThanOrEqual(result.data.count, AvatarImageProcessor.defaultMaximumBytes)
        let properties = try imageProperties(result.data)
        let png = properties[kCGImagePropertyPNGDictionary] as? [CFString: Any]
        XCTAssertNil(png?[kCGImagePropertyPNGDescription])
    }

    func testNonDirectFormatIsConvertedToJPEG() throws {
        let source = try makeImageData(type: .tiff, width: 48, height: 48)
        let result = try AvatarImageProcessor().process(
            data: source,
            declaredContentTypeIdentifier: UTType.tiff.identifier
        )

        XCTAssertEqual(result.mimeType, .jpeg)
        let imageSource = try XCTUnwrap(CGImageSourceCreateWithData(result.data as CFData, nil))
        XCTAssertEqual(CGImageSourceGetType(imageSource) as String?, UTType.jpeg.identifier)
    }

    func testInvalidDataIsRejected() {
        XCTAssertThrowsError(
            try AvatarImageProcessor().process(
                data: Data("not an image".utf8),
                declaredContentTypeIdentifier: UTType.jpeg.identifier
            )
        ) { error in
            XCTAssertEqual(error as? AvatarImageProcessingError, .invalidImage)
        }
    }

    func testOutputOverConfiguredLimitFails() throws {
        let source = try makeImageData(type: .jpeg, width: 128, height: 128)
        let processor = AvatarImageProcessor(
            maximumBytes: 8,
            maximumInputBytes: 1_024 * 1_024,
            maximumPixelDimension: 128,
            maximumPixelCount: 128 * 128
        )

        XCTAssertThrowsError(
            try processor.process(
                data: source,
                declaredContentTypeIdentifier: UTType.jpeg.identifier
            )
        ) { error in
            XCTAssertEqual(error as? AvatarImageProcessingError, .outputTooLarge)
        }
    }

    private func makeImageData(
        type: UTType,
        width: Int,
        height: Int,
        properties: [CFString: Any] = [:]
    ) throws -> Data {
        let colorSpace = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
        let context = try XCTUnwrap(
            CGContext(
                data: nil,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
            )
        )
        context.setFillColor(CGColor(red: 0.82, green: 0.24, blue: 0.12, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let image = try XCTUnwrap(context.makeImage())
        let output = NSMutableData()
        let destination = try XCTUnwrap(
            CGImageDestinationCreateWithData(output, type.identifier as CFString, 1, nil)
        )
        CGImageDestinationAddImage(destination, image, properties as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return output as Data
    }

    private func imageProperties(_ data: Data) throws -> [CFString: Any] {
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        return try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
    }
}

@MainActor
final class SettingsViewModelTests: XCTestCase {
    func testSuccessfulNameUpdateRefreshesSession() async {
        let client = SettingsClientSpy()
        let refreshCount = MainActorCounter()
        let viewModel = makeViewModel(
            client: client,
            refreshSession: { refreshCount.value += 1 }
        )

        let didSave = await viewModel.saveName("New Name")
        XCTAssertTrue(didSave)
        XCTAssertEqual(viewModel.snapshot.account.displayName, "New Name")
        XCTAssertEqual(refreshCount.value, 1)
    }

    func testUnauthorizedMutationRequestsFullScreenReauthentication() async {
        let client = SettingsClientSpy()
        await client.setError(SettingsClientError(kind: .unauthorized, code: "UNAUTHORIZED"))
        let reauthenticationCount = MainActorCounter()
        let viewModel = makeViewModel(
            client: client,
            showReauthentication: { reauthenticationCount.value += 1 }
        )

        let didSave = await viewModel.saveName("New Name")
        XCTAssertFalse(didSave)
        XCTAssertEqual(reauthenticationCount.value, 1)
        XCTAssertNil(viewModel.alert)
    }

    func testPasswordDoesNotReachClientWhenNamespacePurgeFails() async {
        let client = SettingsClientSpy()
        let viewModel = makeViewModel(
            client: client,
            purgeCurrentNamespace: { throw TestFailure.purge }
        )

        let didChange = await viewModel.changePassword(
            currentPassword: "old-password",
            newPassword: "new-password",
            confirmation: "new-password"
        )
        XCTAssertFalse(didChange)
        let passwordCallCount = await client.passwordUpdateCallCount()
        XCTAssertEqual(passwordCallCount, 0)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.security.purgeFailed")
    }

    func testPasswordPurgesBeforeUpdateAndLogsOutAfterSuccess() async {
        let events = EventRecorder()
        let client = SettingsClientSpy(events: events)
        let viewModel = makeViewModel(
            client: client,
            purgeCurrentNamespace: { await events.record("purge") },
            logout: { await events.record("logout") }
        )

        let didChange = await viewModel.changePassword(
            currentPassword: "old-password",
            newPassword: "new-password",
            confirmation: "new-password"
        )
        XCTAssertTrue(didChange)
        let recordedEvents = await events.values()
        XCTAssertEqual(recordedEvents, ["purge", "updatePassword", "logout"])
    }

    func testPasswordDoesNotReportSuccessWhenLocalLogoutFails() async {
        let client = SettingsClientSpy()
        let viewModel = makeViewModel(
            client: client,
            logout: { throw TestFailure.logout }
        )

        let didChange = await viewModel.changePassword(
            currentPassword: "old-password",
            newPassword: "new-password",
            confirmation: "new-password"
        )

        XCTAssertFalse(didChange)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.error.transport")
    }

    private func makeViewModel(
        client: SettingsClientSpy,
        refreshSession: @escaping @MainActor @Sendable () async -> Void = {},
        showReauthentication: @escaping @MainActor @Sendable () -> Void = {},
        purgeCurrentNamespace: @escaping @MainActor @Sendable () async throws -> Void = {},
        logout: @escaping @MainActor @Sendable () async throws -> Void = {}
    ) -> SettingsViewModel {
        SettingsViewModel(
            initialSnapshot: SettingsSnapshot(
                account: SettingsAccount(
                    id: "user-1",
                    displayName: "Original Name",
                    email: "reader@example.com",
                    avatarURL: nil
                ),
                locale: .zhCN,
                server: SettingsServer(
                    displayName: "library.example.com",
                    baseURL: "https://library.example.com/base",
                    serverIdentity: "server-1",
                    version: nil
                ),
                app: SettingsAppInfo(version: "1.0", build: "1")
            ),
            client: client,
            lifecycle: SettingsLifecycleHooks(
                refreshSession: refreshSession,
                showReauthentication: showReauthentication,
                purgeCurrentNamespace: purgeCurrentNamespace,
                logout: logout
            )
        )
    }
}

private enum TestFailure: Error {
    case purge
    case logout
}

@MainActor
private final class MainActorCounter {
    var value = 0
}

private actor EventRecorder {
    private var events: [String] = []

    func record(_ event: String) {
        events.append(event)
    }

    func values() -> [String] {
        events
    }
}

private actor SettingsClientSpy: SettingsClient {
    private var error: SettingsClientError?
    private var passwordCalls = 0
    private let events: EventRecorder?

    init(events: EventRecorder? = nil) {
        self.events = events
    }

    func setError(_ error: SettingsClientError) {
        self.error = error
    }

    func passwordUpdateCallCount() -> Int {
        passwordCalls
    }

    func loadSettings() async throws -> (account: SettingsAccount, locale: SettingsLocale) {
        try throwIfNeeded()
        return (account(name: "Original Name"), .zhCN)
    }

    func updateName(_ name: String) async throws -> SettingsAccount {
        try throwIfNeeded()
        return account(name: name)
    }

    func updateEmail(_ email: String, currentPassword: String) async throws -> SettingsAccount {
        try throwIfNeeded()
        return SettingsAccount(id: "user-1", displayName: "Original Name", email: email, avatarURL: nil)
    }

    func updatePassword(
        currentPassword: String,
        newPassword: String
    ) async throws -> SettingsPasswordChange {
        passwordCalls += 1
        try throwIfNeeded()
        if let events { await events.record("updatePassword") }
        return SettingsPasswordChange(requiresLogin: true)
    }

    func loadAvatar(etag: String?) async throws -> SettingsAvatarContent {
        try throwIfNeeded()
        return SettingsAvatarContent(data: Data(), contentType: nil, etag: nil, notModified: false)
    }

    func uploadAvatar(_ upload: SettingsAvatarUpload) async throws -> SettingsAccount {
        try throwIfNeeded()
        return account(name: "Original Name")
    }

    func deleteAvatar() async throws -> SettingsAccount {
        try throwIfNeeded()
        return account(name: "Original Name")
    }

    func updateLocale(_ locale: SettingsLocale) async throws -> SettingsLocale {
        try throwIfNeeded()
        return locale
    }

    func loadServerVersion() async throws -> String {
        try throwIfNeeded()
        return "1.0.0"
    }

    private func throwIfNeeded() throws {
        if let error { throw error }
    }

    private func account(name: String) -> SettingsAccount {
        SettingsAccount(
            id: "user-1",
            displayName: name,
            email: "reader@example.com",
            avatarURL: nil
        )
    }
}
