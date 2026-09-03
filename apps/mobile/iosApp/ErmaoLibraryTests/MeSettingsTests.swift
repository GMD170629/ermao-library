import Foundation
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import ErmaoLibrary

final class SettingsMetricsTests: XCTestCase {
    func testSettingsRowsShareTheApprovedGeometry() {
        XCTAssertEqual(SettingsMetrics.rowMinimumHeight, 54)
        XCTAssertEqual(SettingsMetrics.horizontalInset, 16)
        XCTAssertEqual(SettingsMetrics.verticalInset, 8)
        XCTAssertEqual(SettingsMetrics.rowContentMinimumHeight, 38)
        XCTAssertEqual(SettingsMetrics.iconSlotSize, 28)
        XCTAssertEqual(SettingsMetrics.iconSize, 20)
        XCTAssertEqual(SettingsMetrics.iconTitleSpacing, 12)
        XCTAssertEqual(SettingsMetrics.separatorLeading, 40)
        XCTAssertEqual(SettingsMetrics.trailingSlotWidth, 18)
        XCTAssertEqual(SettingsMetrics.sectionSpacing, 20)
        XCTAssertEqual(SettingsMetrics.sectionHeaderBottomSpacing, 8)
        XCTAssertEqual(SettingsMetrics.bottomActionHeight, 50)
    }

    func testIdentityGeometryUsesTheCompactApprovedMeasurements() {
        XCTAssertEqual(SettingsMetrics.identityAvatarSize, 52)
        XCTAssertEqual(SettingsMetrics.identityMinimumHeight, 76)
        XCTAssertEqual(SettingsMetrics.identityContentMinimumHeight, 60)
    }
}

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
    func testAvatarDownloadUsesTheURLReturnedByTheAccountInterface() async {
        let client = SettingsClientSpy()
        let avatarURL = "/api/auth/avatar?v=42"
        let serverAvatar = Data("server-rendered-avatar".utf8)
        await client.configureAvatar(url: avatarURL, data: serverAvatar)
        let viewModel = makeViewModel(client: client)

        await viewModel.loadIfNeeded()

        let requestedAvatarURLs = await client.requestedAvatarURLs()
        XCTAssertEqual(requestedAvatarURLs, [avatarURL])
        XCTAssertEqual(viewModel.avatarData, serverAvatar)
    }

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

    func testInvalidDisplayNameDoesNotReachClient() async {
        let client = SettingsClientSpy()
        let viewModel = makeViewModel(client: client)

        let didSave = await viewModel.saveName(String(repeating: "x", count: 41))
        let nameCallCount = await client.nameUpdateCallCount()

        XCTAssertFalse(didSave)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.profile.name.maximum")
        XCTAssertEqual(nameCallCount, 0)
    }

    func testUnchangedEmailDoesNotReachClient() async {
        let client = SettingsClientSpy()
        let viewModel = makeViewModel(client: client)

        let didSave = await viewModel.saveEmail(
            " reader@example.com ",
            currentPassword: "current-password"
        )
        let emailCallCount = await client.emailUpdateCallCount()

        XCTAssertFalse(didSave)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.security.email.unchanged")
        XCTAssertEqual(emailCallCount, 0)
    }

    func testInvalidEmailDoesNotReachClient() async {
        let client = SettingsClientSpy()
        let viewModel = makeViewModel(client: client)

        let didSave = await viewModel.saveEmail(
            "not-an-email",
            currentPassword: "current-password"
        )
        let emailCallCount = await client.emailUpdateCallCount()

        XCTAssertFalse(didSave)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.security.email.invalid")
        XCTAssertEqual(emailCallCount, 0)
    }

    func testIncorrectCurrentPasswordShowsSpecificRecoveryMessage() async {
        let client = SettingsClientSpy()
        await client.setError(
            SettingsClientError(kind: .validation, code: "CURRENT_PASSWORD_INCORRECT")
        )
        let viewModel = makeViewModel(client: client)

        let didSave = await viewModel.saveEmail(
            "new@example.com",
            currentPassword: "incorrect-password"
        )

        XCTAssertFalse(didSave)
        XCTAssertEqual(viewModel.alert?.titleKey, "settings.error.currentPassword.title")
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.error.currentPassword.message")
        XCTAssertNil(viewModel.alert?.referenceCode)
    }

    func testEmailConflictShowsSpecificRecoveryMessage() async {
        let client = SettingsClientSpy()
        await client.setError(SettingsClientError(kind: .conflict, code: "EMAIL_IN_USE"))
        let viewModel = makeViewModel(client: client)

        let didSave = await viewModel.saveEmail(
            "used@example.com",
            currentPassword: "current-password"
        )

        XCTAssertFalse(didSave)
        XCTAssertEqual(viewModel.alert?.titleKey, "settings.error.emailInUse.title")
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.error.emailInUse.message")
    }

    func testUnknownStableErrorIncludesReferenceCode() async {
        let client = SettingsClientSpy()
        await client.setError(SettingsClientError(kind: .server, code: "SETTINGS_WRITE_FAILED"))
        let viewModel = makeViewModel(client: client)

        let didSave = await viewModel.saveName("New Name")

        XCTAssertFalse(didSave)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.error.server")
        XCTAssertEqual(viewModel.alert?.referenceCode, "SETTINGS_WRITE_FAILED")
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

    func testShortPasswordDoesNotPurgeOrReachClient() async {
        let client = SettingsClientSpy()
        let purgeCount = MainActorCounter()
        let viewModel = makeViewModel(
            client: client,
            purgeCurrentNamespace: { purgeCount.value += 1 }
        )

        let didChange = await viewModel.changePassword(
            currentPassword: "old-password",
            newPassword: "short",
            confirmation: "short"
        )
        let passwordCallCount = await client.passwordUpdateCallCount()

        XCTAssertFalse(didChange)
        XCTAssertEqual(viewModel.alert?.messageKey, "settings.security.newPassword.minimum")
        XCTAssertEqual(purgeCount.value, 0)
        XCTAssertEqual(passwordCallCount, 0)
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
    private var nameCalls = 0
    private var emailCalls = 0
    private var passwordCalls = 0
    private let events: EventRecorder?
    private var avatarURL: String?
    private var avatarContent = Data()
    private var avatarRequests: [String] = []

    init(events: EventRecorder? = nil) {
        self.events = events
    }

    func setError(_ error: SettingsClientError) {
        self.error = error
    }

    func passwordUpdateCallCount() -> Int {
        passwordCalls
    }

    func nameUpdateCallCount() -> Int {
        nameCalls
    }

    func emailUpdateCallCount() -> Int {
        emailCalls
    }

    func configureAvatar(url: String, data: Data) {
        avatarURL = url
        avatarContent = data
    }

    func requestedAvatarURLs() -> [String] {
        avatarRequests
    }

    func loadSettings() async throws -> (account: SettingsAccount, locale: SettingsLocale) {
        try throwIfNeeded()
        return (account(name: "Original Name"), .zhCN)
    }

    func updateName(_ name: String) async throws -> SettingsAccount {
        nameCalls += 1
        try throwIfNeeded()
        return account(name: name)
    }

    func updateEmail(_ email: String, currentPassword: String) async throws -> SettingsAccount {
        emailCalls += 1
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

    func loadAvatar(from avatarURL: String, etag: String?) async throws -> SettingsAvatarContent {
        try throwIfNeeded()
        avatarRequests.append(avatarURL)
        return SettingsAvatarContent(data: avatarContent, contentType: "image/webp", etag: nil, notModified: false)
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
            avatarURL: avatarURL
        )
    }
}
