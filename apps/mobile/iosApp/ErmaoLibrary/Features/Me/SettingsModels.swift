import Foundation

enum SettingsRoute: String, CaseIterable, Hashable, Identifiable, Sendable {
    case profile
    case security
    case language
    case about

    var id: String { rawValue }
}

enum SettingsLocale: String, CaseIterable, Hashable, Identifiable, Sendable {
    case zhCN = "zh-CN"
    case enUS = "en-US"

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .zhCN: "settings.language.zhCN"
        case .enUS: "settings.language.enUS"
        }
    }
}

struct SettingsAccount: Equatable, Sendable {
    let id: String
    let displayName: String
    let email: String
    let avatarURL: String?
}

struct SettingsServer: Equatable, Sendable {
    let displayName: String
    let baseURL: String
    let serverIdentity: String
    var version: String?

    var displayAddress: String {
        guard let url = URL(string: baseURL), let host = url.host else { return baseURL }
        let port = url.port.map { ":\($0)" } ?? ""
        let path = url.path == "/" ? "" : url.path
        return host + port + path
    }
}

struct SettingsAppInfo: Equatable, Sendable {
    let version: String
    let build: String

    static func current(bundle: Bundle = .main) -> SettingsAppInfo {
        SettingsAppInfo(
            version: bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—",
            build: bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"
        )
    }
}

struct SettingsSnapshot: Equatable, Sendable {
    var account: SettingsAccount
    var locale: SettingsLocale
    var server: SettingsServer
    let app: SettingsAppInfo
}

enum SettingsAvatarMimeType: String, Equatable, Sendable {
    case jpeg = "image/jpeg"
    case png = "image/png"
    case webP = "image/webp"
}

struct SettingsAvatarUpload: Equatable, Sendable {
    let data: Data
    let mimeType: SettingsAvatarMimeType
}

struct SettingsAvatarContent: Equatable, Sendable {
    let data: Data
    let contentType: String?
    let etag: String?
    let notModified: Bool
}

struct SettingsPasswordChange: Equatable, Sendable {
    let requiresLogin: Bool
}

enum SettingsClientErrorKind: String, Equatable, Sendable {
    case validation
    case unauthorized
    case forbidden
    case notFound
    case conflict
    case rateLimited
    case server
    case transport
    case protocolViolation
}

struct SettingsFieldViolation: Equatable, Sendable {
    let field: String
    let code: String
}

struct SettingsClientError: Error, Equatable, Sendable {
    let kind: SettingsClientErrorKind
    let code: String
    let fieldViolations: [SettingsFieldViolation]

    init(
        kind: SettingsClientErrorKind,
        code: String,
        fieldViolations: [SettingsFieldViolation] = []
    ) {
        self.kind = kind
        self.code = code
        self.fieldViolations = fieldViolations
    }
}

protocol SettingsClient: Sendable {
    func loadSettings() async throws -> (account: SettingsAccount, locale: SettingsLocale)
    func updateName(_ name: String) async throws -> SettingsAccount
    func updateEmail(_ email: String, currentPassword: String) async throws -> SettingsAccount
    func updatePassword(currentPassword: String, newPassword: String) async throws -> SettingsPasswordChange
    func loadAvatar(etag: String?) async throws -> SettingsAvatarContent
    func uploadAvatar(_ upload: SettingsAvatarUpload) async throws -> SettingsAccount
    func deleteAvatar() async throws -> SettingsAccount
    func updateLocale(_ locale: SettingsLocale) async throws -> SettingsLocale
    func loadServerVersion() async throws -> String
}

struct SettingsLifecycleHooks: Sendable {
    let refreshSession: @MainActor @Sendable () async -> Void
    let showReauthentication: @MainActor @Sendable () -> Void
    let purgeCurrentNamespace: @MainActor @Sendable () async throws -> Void
    let logout: @MainActor @Sendable () async throws -> Void

    init(
        refreshSession: @escaping @MainActor @Sendable () async -> Void,
        showReauthentication: @escaping @MainActor @Sendable () -> Void,
        purgeCurrentNamespace: @escaping @MainActor @Sendable () async throws -> Void,
        logout: @escaping @MainActor @Sendable () async throws -> Void
    ) {
        self.refreshSession = refreshSession
        self.showReauthentication = showReauthentication
        self.purgeCurrentNamespace = purgeCurrentNamespace
        self.logout = logout
    }
}

struct SettingsAlert: Identifiable, Equatable, Sendable {
    let id = UUID()
    let titleKey: String
    let messageKey: String
}
