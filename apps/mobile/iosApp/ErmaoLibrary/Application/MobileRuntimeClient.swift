import Foundation

enum SessionPhase: Equatable, Sendable {
    case noServer
    case checkingServer
    case serverConnectionFailed
    case tlsRisk
    case setupRequired
    case settingUp
    case setupFailed
    case signedOut
    case authenticating
    case loginFailed
    case accountDisabled
    case authenticated
    case sessionExpired
    case incompatibleServer
}

enum RuntimeTLSMode: String, Codable, Equatable, Sendable {
    case systemTrust = "SystemTrust"
    case insecureSkipAllValidation = "InsecureSkipAllValidation"
}

struct RuntimeServerProfile: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let displayName: String
    let baseURL: String
    let serverIdentity: String
    let isActive: Bool
    let tlsMode: RuntimeTLSMode

    private enum CodingKeys: String, CodingKey {
        case id
        case displayName
        case baseURL = "baseUrl"
        case serverIdentity
        case isActive
        case tlsMode
    }
}

struct SavedServerLoginSummary: Equatable, Identifiable, Sendable {
    let id: String
    let displayName: String
    let accountOrAddress: String
}

struct RuntimeAuthorization: Equatable, Sendable {
    let isAdmin: Bool
    let canManageSystem: Bool
    let allLibraryScopes: Bool
    let monitorFolderIDs: [String]
    let canViewManualImports: Bool
    let authorizationVersion: Int64
}

struct RuntimeSessionSnapshot: Equatable, Sendable {
    let phase: SessionPhase
    let profile: RuntimeServerProfile?
    let userID: String?
    let userDisplayName: String?
    let userEmail: String?
    let userAvatarURL: String?
    let userLocale: String?
    let authorization: RuntimeAuthorization?
    let reasonCode: String?

    init(
        phase: SessionPhase,
        profile: RuntimeServerProfile?,
        userID: String? = nil,
        userDisplayName: String?,
        userEmail: String?,
        userAvatarURL: String? = nil,
        userLocale: String? = nil,
        authorization: RuntimeAuthorization? = nil,
        reasonCode: String?
    ) {
        self.phase = phase
        self.profile = profile
        self.userID = userID
        self.userDisplayName = userDisplayName
        self.userEmail = userEmail
        self.userAvatarURL = userAvatarURL
        self.userLocale = userLocale
        self.authorization = authorization
        self.reasonCode = reasonCode
    }

    static let noServer = RuntimeSessionSnapshot(
        phase: .noServer,
        profile: nil,
        userDisplayName: nil,
        userEmail: nil,
        reasonCode: nil
    )
}

struct ConnectServerRequest: Equatable, Sendable {
    let displayName: String
    let baseURL: String
    let tlsMode: RuntimeTLSMode
}

struct LoginRequest: Equatable, Sendable {
    let email: String
    let password: String
}

struct SetupRequest: Equatable, Sendable {
    let name: String
    let email: String
    let password: String
    let locale: String
}

struct RuntimeFieldViolation: Equatable, Sendable {
    let field: String
    let code: String
}

enum RuntimeNavigationDirective: String, Equatable, Sendable {
    case keepCurrentStacks = "KeepCurrentStacks"
    case restoreSelectedTab = "RestoreSelectedTab"
    case resetAllStacksHome = "ResetAllStacksHome"
    case revalidatePrivateShell = "RevalidatePrivateShell"
    case hidePrivateShell = "HidePrivateShell"
    case showServerProfiles = "ShowServerProfiles"
}

struct RuntimeOperationOutcome: Equatable, Sendable {
    let outcomeCode: String
    let fieldViolations: [RuntimeFieldViolation]
    let parameters: [String: String]
    let navigationDirective: RuntimeNavigationDirective

    static let success = RuntimeOperationOutcome(
        outcomeCode: "SUCCESS",
        fieldViolations: [],
        parameters: [:],
        navigationDirective: .keepCurrentStacks
    )
}

struct RuntimeOperationFailure: Error, Equatable, Sendable {
    let errorKind: String
    let errorCode: String
    let fieldViolations: [RuntimeFieldViolation]
    let parameters: [String: String]
}

protocol RuntimeObservationToken: AnyObject {
    func cancel()
}

@MainActor
protocol MobileRuntimeClient: AnyObject {
    var currentSnapshot: RuntimeSessionSnapshot { get }
    var serverProfiles: [RuntimeServerProfile] { get }

    func observe(
        _ onChange: @escaping @MainActor (RuntimeSessionSnapshot) -> Void
    ) -> RuntimeObservationToken

    func start() async throws -> RuntimeOperationOutcome
    func connectServer(_ request: ConnectServerRequest) async throws -> RuntimeOperationOutcome
    func editServer(profileID: String, request: ConnectServerRequest) async throws -> RuntimeOperationOutcome
    func switchServer(profileID: String) async throws -> RuntimeOperationOutcome
    func removeServer(profileID: String) async throws -> RuntimeOperationOutcome
    func restoreSystemTrust(profileID: String) async throws -> RuntimeOperationOutcome
    func acceptInsecureTLS() async throws -> RuntimeOperationOutcome
    func loginToServer(
        baseURL: String,
        email: String,
        password: String
    ) async throws -> RuntimeOperationOutcome
    func loginToServerAcceptingInsecureTLS(
        baseURL: String,
        email: String,
        password: String
    ) async throws -> RuntimeOperationOutcome
    func login(_ request: LoginRequest) async throws -> RuntimeOperationOutcome
    func setup(_ request: SetupRequest) async throws -> RuntimeOperationOutcome
    func retry() async throws -> RuntimeOperationOutcome
    func refreshCurrentSession() async throws -> RuntimeOperationOutcome
    func logout() async throws -> RuntimeOperationOutcome
    func close()
}
