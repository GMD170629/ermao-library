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
        guard !email.isEmpty, email.contains("@") else {
            presentValidation(messageKey: "settings.security.email.invalid")
            return false
        }
        guard !currentPassword.isEmpty else {
            presentValidation(messageKey: "settings.security.currentPassword.required")
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
        guard newPassword.count >= 10 else {
            presentValidation(messageKey: "settings.security.newPassword.minimum")
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
            avatarData = upload.data
            avatarETag = nil
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
        let requestID = UUID()
        avatarRequestID = requestID
        do {
            let content = try await client.loadAvatar(etag: avatarETag)
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
            // The account remains usable with initials when avatar loading fails.
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

        let messageKey: String = switch settingsError.kind {
        case .validation: "settings.error.validation"
        case .forbidden: "settings.error.forbidden"
        case .conflict: "settings.error.conflict"
        case .rateLimited: "settings.error.rateLimited"
        case .notFound: "settings.error.notFound"
        case .server, .transport: "settings.error.transport"
        case .protocolViolation: "settings.error.protocol"
        case .unauthorized: "settings.error.unauthorized"
        }
        alert = SettingsAlert(titleKey: "settings.error.title", messageKey: messageKey)
    }

    private func avatarMessageKey(for error: AvatarImageProcessingError) -> String {
        switch error {
        case .inputTooLarge, .outputTooLarge: "settings.avatar.error.tooLarge"
        case .invalidImage, .unsafeDimensions, .unableToEncode: "settings.avatar.error.invalid"
        }
    }
}
