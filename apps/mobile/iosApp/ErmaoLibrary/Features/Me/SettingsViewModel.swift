import Combine
import Foundation

enum SettingsOperation: Equatable, Sendable {
    case loading
    case savingName
    case savingEmail
    case changingPassword
    case uploadingAvatar
    case deletingAvatar
    case updatingLocale
    case signingOut
}

enum SettingsServerVersionState: Equatable, Sendable {
    case idle
    case loading
    case loaded
    case failed
}

@MainActor
final class SettingsViewModel: ObservableObject {
    @Published private(set) var snapshot: SettingsSnapshot
    @Published private(set) var avatarData: Data?
    @Published private(set) var operation: SettingsOperation?
    @Published private(set) var alert: SettingsAlert?
    @Published private(set) var serverVersionState: SettingsServerVersionState

    private let client: any SettingsClient
    private let lifecycle: SettingsLifecycleHooks
    private let avatarProcessor: AvatarImageProcessor
    private var avatarETag: String?
    private var hasLoaded = false
    private var loadRequestID: UUID?
    private var avatarRequestID: UUID?
    private var serverVersionRequestID: UUID?

    init(
        initialSnapshot: SettingsSnapshot,
        client: any SettingsClient,
        lifecycle: SettingsLifecycleHooks,
        avatarProcessor: AvatarImageProcessor = AvatarImageProcessor()
    ) {
        snapshot = initialSnapshot
        self.client = client
        self.lifecycle = lifecycle
        self.avatarProcessor = avatarProcessor
        serverVersionState = initialSnapshot.server.version == nil ? .idle : .loaded
    }

    var isBusy: Bool { operation != nil }

    func isWorking(_ expected: SettingsOperation) -> Bool {
        operation == expected
    }

    func loadIfNeeded() async {
        guard !hasLoaded, operation == nil else { return }
        let requestID = UUID()
        loadRequestID = requestID
        operation = .loading
        defer {
            if loadRequestID == requestID { operation = nil }
        }

        do {
            let loaded = try await client.loadSettings()
            guard loadRequestID == requestID else { return }
            snapshot.account = loaded.account
            snapshot.locale = loaded.locale
            hasLoaded = true

            if loaded.account.avatarURL == nil {
                avatarData = nil
                avatarETag = nil
            } else {
                await loadAvatarIfPresent()
            }
            await loadServerVersionIfNeeded()
        } catch {
            handle(error)
        }
    }

    func loadServerVersionIfNeeded(force: Bool = false) async {
        guard force || serverVersionState == .idle else { return }
        let requestID = UUID()
        serverVersionRequestID = requestID
        serverVersionState = .loading
        do {
            let version = try await client.loadServerVersion()
            guard serverVersionRequestID == requestID else { return }
            snapshot.server.version = version
            serverVersionState = .loaded
        } catch let error as SettingsClientError where error.kind == .unauthorized {
            guard serverVersionRequestID == requestID else { return }
            serverVersionState = .failed
            handle(error)
        } catch {
            guard serverVersionRequestID == requestID else { return }
            serverVersionState = .failed
        }
    }

    func saveName(_ rawName: String) async -> Bool {
        let name = rawName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            presentValidation(messageKey: "settings.profile.name.required")
            return false
        }
        guard SettingsInputValidation.isValidDisplayName(name) else {
            presentValidation(messageKey: "settings.profile.name.maximum")
            return false
        }
        guard operation == nil else { return false }
        operation = .savingName
        defer { operation = nil }

        do {
            snapshot.account = try await client.updateName(name)
            await lifecycle.refreshSession()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func saveEmail(_ rawEmail: String, currentPassword: String) async -> Bool {
        let email = rawEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard SettingsInputValidation.isValidEmail(email) else {
            presentValidation(messageKey: "settings.security.email.invalid")
            return false
        }
        guard email != snapshot.account.email else {
            presentValidation(messageKey: "settings.security.email.unchanged")
            return false
        }
        guard !currentPassword.isEmpty else {
            presentValidation(messageKey: "settings.security.currentPassword.required")
            return false
        }
        guard SettingsInputValidation.isValidCurrentPassword(currentPassword) else {
            presentValidation(messageKey: "settings.security.currentPassword.maximum")
            return false
        }
        guard operation == nil else { return false }
        operation = .savingEmail
        defer { operation = nil }

        do {
            snapshot.account = try await client.updateEmail(email, currentPassword: currentPassword)
            await lifecycle.refreshSession()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func changePassword(
        currentPassword: String,
        newPassword: String,
        confirmation: String
    ) async -> Bool {
        guard !currentPassword.isEmpty else {
            presentValidation(messageKey: "settings.security.currentPassword.required")
            return false
        }
        guard SettingsInputValidation.isValidCurrentPassword(currentPassword) else {
            presentValidation(messageKey: "settings.security.currentPassword.maximum")
            return false
        }
        guard newPassword.count >= SettingsInputValidation.minimumPasswordLength else {
            presentValidation(messageKey: "settings.security.newPassword.minimum")
            return false
        }
        guard SettingsInputValidation.isValidNewPassword(newPassword) else {
            presentValidation(messageKey: "settings.security.newPassword.maximum")
            return false
        }
        guard newPassword == confirmation else {
            presentValidation(messageKey: "settings.security.password.mismatch")
            return false
        }
        guard operation == nil else { return false }
        operation = .changingPassword
        defer { operation = nil }

        do {
            try await lifecycle.purgeCurrentNamespace()
        } catch {
            alert = SettingsAlert(
                titleKey: "settings.error.title",
                messageKey: "settings.security.purgeFailed"
            )
            return false
        }

        do {
            _ = try await client.updatePassword(
                currentPassword: currentPassword,
                newPassword: newPassword
            )
            try await lifecycle.logout()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func uploadAvatar(data: Data, declaredContentTypeIdentifier: String?) async -> Bool {
        guard operation == nil else { return false }
        operation = .uploadingAvatar
        defer { operation = nil }

        do {
            let processor = avatarProcessor
            let upload = try await Task.detached(priority: .userInitiated) {
                try processor.process(
                    data: data,
                    declaredContentTypeIdentifier: declaredContentTypeIdentifier
                )
            }.value
            snapshot.account = try await client.uploadAvatar(upload)
            avatarData = nil
            avatarETag = nil
            await loadAvatarIfPresent()
            await lifecycle.refreshSession()
            return true
        } catch let error as AvatarImageProcessingError {
            alert = SettingsAlert(
                titleKey: "settings.avatar.error.title",
                messageKey: avatarMessageKey(for: error)
            )
            return false
        } catch {
            handle(error)
            return false
        }
    }

    func deleteAvatar() async -> Bool {
        guard operation == nil else { return false }
        operation = .deletingAvatar
        defer { operation = nil }

        do {
            snapshot.account = try await client.deleteAvatar()
            avatarData = nil
            avatarETag = nil
            await lifecycle.refreshSession()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func updateLocale(_ locale: SettingsLocale) async -> Bool {
        guard locale != snapshot.locale else { return true }
        guard operation == nil else { return false }
        operation = .updatingLocale
        defer { operation = nil }

        do {
            snapshot.locale = try await client.updateLocale(locale)
            await lifecycle.refreshSession()
            return true
        } catch {
            handle(error)
            return false
        }
    }

    func signOut() async {
        guard operation == nil else { return }
        operation = .signingOut
        do {
            try await lifecycle.logout()
        } catch {
            handle(error)
        }
        operation = nil
    }

    func presentPhotoLoadingFailure() {
        alert = SettingsAlert(
            titleKey: "settings.avatar.error.title",
            messageKey: "settings.avatar.error.read"
        )
    }

    func dismissAlert() {
        alert = nil
    }

    private func loadAvatarIfPresent() async {
        guard let avatarURL = snapshot.account.avatarURL else {
            avatarData = nil
            avatarETag = nil
            return
        }
        let requestID = UUID()
        avatarRequestID = requestID
        do {
            let content = try await client.loadAvatar(from: avatarURL, etag: avatarETag)
            guard avatarRequestID == requestID else { return }
            guard !content.notModified else { return }
            avatarData = content.data
            avatarETag = content.etag
        } catch let error as SettingsClientError where error.kind == .notFound {
            guard avatarRequestID == requestID else { return }
            avatarData = nil
            avatarETag = nil
        } catch let error as SettingsClientError where error.kind == .unauthorized {
            guard avatarRequestID == requestID else { return }
            handle(error)
        } catch {
            guard avatarRequestID == requestID else { return }
            avatarData = nil
            avatarETag = nil
        }
    }

    private func presentValidation(messageKey: String) {
        alert = SettingsAlert(titleKey: "settings.validation.title", messageKey: messageKey)
    }

    private func handle(_ error: Error) {
        guard let settingsError = error as? SettingsClientError else {
            alert = SettingsAlert(
                titleKey: "settings.error.title",
                messageKey: "settings.error.transport"
            )
            return
        }

        if settingsError.kind == .unauthorized {
            lifecycle.showReauthentication()
            return
        }

        if let specificAlert = specificAlert(for: settingsError) {
            alert = specificAlert
            return
        }

        let messageKey: String = switch settingsError.kind {
        case .validation: "settings.error.validation"
        case .forbidden: "settings.error.forbidden"
        case .conflict: "settings.error.conflict"
        case .rateLimited: "settings.error.rateLimited"
        case .notFound: "settings.error.notFound"
        case .server: "settings.error.server"
        case .transport: "settings.error.transport"
        case .protocolViolation: "settings.error.protocol"
        case .unauthorized: "settings.error.unauthorized"
        }
        alert = SettingsAlert(
            titleKey: "settings.error.title",
            messageKey: messageKey,
            referenceCode: safeReferenceCode(settingsError.code)
        )
    }

    private func specificAlert(for error: SettingsClientError) -> SettingsAlert? {
        switch error.code {
        case "CURRENT_PASSWORD_INCORRECT":
            SettingsAlert(
                titleKey: "settings.error.currentPassword.title",
                messageKey: "settings.error.currentPassword.message"
            )
        case "EMAIL_IN_USE":
            SettingsAlert(
                titleKey: "settings.error.emailInUse.title",
                messageKey: "settings.error.emailInUse.message"
            )
        case "NEW_PASSWORD_MUST_DIFFER":
            SettingsAlert(
                titleKey: "settings.error.newPasswordMustDiffer.title",
                messageKey: "settings.error.newPasswordMustDiffer.message"
            )
        default:
            nil
        }
    }

    private func safeReferenceCode(_ code: String) -> String? {
        guard !code.isEmpty, code.count <= 64 else { return nil }
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
        return code.unicodeScalars.allSatisfy(allowed.contains) ? code : nil
    }

    private func avatarMessageKey(for error: AvatarImageProcessingError) -> String {
        switch error {
        case .inputTooLarge, .outputTooLarge: "settings.avatar.error.tooLarge"
        case .invalidImage, .unsafeDimensions, .unableToEncode: "settings.avatar.error.invalid"
        }
    }
}
