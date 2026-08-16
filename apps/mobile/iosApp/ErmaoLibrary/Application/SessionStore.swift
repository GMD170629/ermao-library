import Combine
import Foundation

@MainActor
final class SessionStore: ObservableObject {
    @Published private(set) var snapshot: RuntimeSessionSnapshot
    @Published private(set) var serverProfiles: [RuntimeServerProfile]
    @Published private(set) var isSelectingServer = false
    @Published private(set) var isReauthenticating = false
    @Published private(set) var reauthenticationUserDisplayName: String?
    @Published private(set) var reauthenticationUserEmail: String?
    @Published private(set) var operationFailure: RuntimeOperationFailure?
    @Published private(set) var isPerformingOperation = false
    @Published private(set) var navigationGeneration = 0
    @Published private(set) var editingProfileID: String?
    @Published private(set) var selectedLoginProfileID: String?
    @Published private(set) var serverLoginSummaries: [SavedServerLoginSummary] = []
    @Published var serverDisplayName = ""
    @Published var serverBaseURL = ""
    @Published var email = ""
    @Published var password = ""

    private let runtime: MobileRuntimeClient
    private let credentialStore: ServerCredentialStore
    private let privateContentCache: any PrivateContentCacheClearing
    private var observation: RuntimeObservationToken?
    private var operation: Task<Void, Never>?
    private var activeOperationID: UUID?
    private var hasStarted = false
    private var isConnectingServer = false
    private var credentialStorageCause: Error?

    init(
        runtime: MobileRuntimeClient,
        credentialStore: ServerCredentialStore = KeychainServerCredentialStore(),
        privateContentCache: any PrivateContentCacheClearing = LibraryCacheStore()
    ) {
        self.runtime = runtime
        self.credentialStore = credentialStore
        self.privateContentCache = privateContentCache
        snapshot = runtime.currentSnapshot
        serverProfiles = runtime.serverProfiles
        observation = runtime.observe { [weak self] snapshot in
            self?.receive(snapshot)
        }
        if let profile = snapshot.profile {
            populateLoginForm(from: profile)
        }
        refreshLoginSummaries()
    }

    func close() {
        operation?.cancel()
        operation = nil
        activeOperationID = nil
        isPerformingOperation = false
        observation?.cancel()
        observation = nil
        runtime.close()
    }

    func start() {
        guard !hasStarted else { return }
        hasStarted = true
        perform { [runtime] in try await runtime.start() }
    }

    func refreshForForeground() {
        guard hasStarted, snapshot.phase.canRefreshSession else { return }
        perform { [runtime] in try await runtime.refreshCurrentSession() }
    }

    func refreshCurrentSession() async {
        do {
            let outcome = try await runtime.refreshCurrentSession()
            refreshProfiles()
            apply(outcome.navigationDirective)
        } catch let failure as RuntimeOperationFailure {
            operationFailure = failure
        } catch is CancellationError {
            return
        } catch {
            operationFailure = RuntimeOperationFailure(
                errorKind: "ServerFailure",
                errorCode: "RUNTIME_FAILURE",
                fieldViolations: [],
                parameters: [:]
            )
        }
    }

    func requireReauthentication() {
        captureReauthenticationIdentity(from: snapshot)
        isReauthenticating = true
        refreshForForeground()
    }

    func beginAddingServer() {
        editingProfileID = nil
        serverDisplayName = ""
        serverBaseURL = ""
        operationFailure = nil
    }

    func beginEditingServer(_ profile: RuntimeServerProfile) {
        editingProfileID = profile.id
        serverDisplayName = profile.displayName
        serverBaseURL = profile.baseURL
        operationFailure = nil
    }

    func connectServer() {
        let request = currentServerRequest
        isConnectingServer = true
        if let editingProfileID {
            perform { [runtime] in
                try await runtime.editServer(profileID: editingProfileID, request: request)
            }
        } else {
            perform { [runtime] in try await runtime.connectServer(request) }
        }
    }

    func switchServer(profileID: String) {
        password = ""
        perform { [runtime] in try await runtime.switchServer(profileID: profileID) }
    }

    func selectServerForLogin(_ profile: RuntimeServerProfile) {
        operationFailure = nil
        populateLoginForm(from: profile)
    }

    func selectServerForLogin(profileID: String) {
        guard let profile = serverProfiles.first(where: { $0.id == profileID }) else { return }
        selectServerForLogin(profile)
    }

    func reconcileSelectedLoginProfileWithAddress() {
        guard let selectedLoginProfileID else { return }
        let selectedBaseURL = serverProfiles.first { $0.id == selectedLoginProfileID }?.baseURL
        let enteredBaseURL = serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if selectedBaseURL != enteredBaseURL {
            self.selectedLoginProfileID = nil
        }
    }

    var selectedLoginProfile: RuntimeServerProfile? {
        if let selectedLoginProfileID {
            return serverProfiles.first { $0.id == selectedLoginProfileID }
        }
        let normalized = serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return serverProfiles.first { $0.baseURL == normalized }
    }

    var otherServerLoginSummaries: [SavedServerLoginSummary] {
        serverLoginSummaries.filter { $0.id != selectedLoginProfile?.id }
    }

    func deleteSelectedLoginServer() {
        guard let profile = selectedLoginProfile else { return }
        perform(
            { [runtime] in try await runtime.removeServer(profileID: profile.id) },
            onSuccess: { [weak self] _ in
                guard let self else { return }
                self.clearLoginForm()
                do {
                    try self.credentialStore.clear(profileID: profile.id)
                } catch {
                    self.recordCredentialStorageFailure(error)
                }
            }
        )
    }

    func clearLoginForm() {
        selectedLoginProfileID = nil
        serverDisplayName = ""
        serverBaseURL = ""
        email = ""
        password = ""
        operationFailure = nil
    }

    func removeServer(profileID: String) {
        perform { [runtime] in try await runtime.removeServer(profileID: profileID) }
    }

    func restoreSystemTrust(profileID: String) {
        perform { [runtime] in try await runtime.restoreSystemTrust(profileID: profileID) }
    }

    func acceptInsecureTLS() {
        perform { [runtime] in try await runtime.acceptInsecureTLS() }
    }

    func login() {
        let request = LoginRequest(
            email: email.trimmingCharacters(in: .whitespacesAndNewlines),
            password: password
        )
        perform { [runtime] in try await runtime.login(request) }
    }

    func loginToCurrentServer(acceptingInsecureTLS: Bool = false) {
        let baseURL = serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let submittedPassword = password
        perform(
            { [runtime] in
                if acceptingInsecureTLS {
                    return try await runtime.loginToServerAcceptingInsecureTLS(
                        baseURL: baseURL,
                        email: normalizedEmail,
                        password: submittedPassword
                    )
                }
                return try await runtime.loginToServer(
                    baseURL: baseURL,
                    email: normalizedEmail,
                    password: submittedPassword
                )
            },
            onSuccess: { [weak self] _ in
                self?.persistAuthenticatedCredentials(
                    email: normalizedEmail,
                    password: submittedPassword
                )
            }
        )
    }

    func setup(name: String, email: String, password: String, locale: String) {
        let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let submittedPassword = password
        let request = SetupRequest(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            email: normalizedEmail,
            password: submittedPassword,
            locale: locale
        )
        perform(
            { [runtime] in try await runtime.setup(request) },
            onSuccess: { [weak self] _ in
                self?.persistAuthenticatedCredentials(
                    email: normalizedEmail,
                    password: submittedPassword
                )
            }
        )
    }

    func retry() {
        perform { [runtime] in try await runtime.retry() }
    }

    func logout() {
        Task {
            do {
                try await logoutAwaitingCompletion()
            } catch let failure as RuntimeOperationFailure {
                operationFailure = failure
            } catch is CancellationError {
                return
            } catch {
                operationFailure = RuntimeOperationFailure(
                    errorKind: "ServerFailure",
                    errorCode: "RUNTIME_FAILURE",
                    fieldViolations: [],
                    parameters: [:]
                )
            }
        }
    }

    func purgeCurrentNamespace() async throws {
        guard let namespace = currentPrivateNamespace else { return }
        do {
            try await privateContentCache.removeNamespace(namespace)
            try IosPdfRangeCache.clearAll()
        } catch {
            throw RuntimeOperationFailure(
                errorKind: "StorageFailure",
                errorCode: "CACHE_PURGE_FAILED",
                fieldViolations: [],
                parameters: [:]
            )
        }
    }

    func logoutAwaitingCompletion(purgeNamespace: Bool = true) async throws {
        password = ""
        if purgeNamespace {
            try await purgeCurrentNamespace()
        }
        let outcome = try await runtime.logout()
        refreshProfiles()
        apply(outcome.navigationDirective)
    }

    func chooseAnotherServer() {
        password = ""
        operationFailure = nil
        isConnectingServer = false
        editingProfileID = nil
        isSelectingServer = true
        refreshProfiles()
    }

    func cancelServerSelection() {
        guard snapshot.profile != nil else { return }
        isConnectingServer = false
        editingProfileID = nil
        isSelectingServer = false
    }

    func fieldViolation(for field: String) -> RuntimeFieldViolation? {
        operationFailure?.fieldViolations.first { $0.field == field }
    }

    var operationErrorCode: String? { operationFailure?.errorCode }

    var isPresentingInfrastructureError: Bool {
        operationErrorCode == "STORAGE_FAILURE" ||
            operationErrorCode == "RUNTIME_FAILURE" ||
            operationErrorCode == "CREDENTIAL_STORAGE_FAILED" ||
            operationErrorCode == "CACHE_PURGE_FAILED"
    }

    func dismissInfrastructureError() {
        operationFailure = nil
        credentialStorageCause = nil
    }

    private var currentServerRequest: ConnectServerRequest {
        ConnectServerRequest(
            displayName: serverDisplayName.trimmingCharacters(in: .whitespacesAndNewlines),
            baseURL: serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines),
            tlsMode: editingProfileID.flatMap { identifier in
                serverProfiles.first(where: { $0.id == identifier })?.tlsMode
            } ?? .systemTrust
        )
    }

    private var currentPrivateNamespace: String? {
        guard
            let profile = snapshot.profile,
            let userID = snapshot.userID,
            let authorizationVersion = snapshot.authorization?.authorizationVersion
        else { return nil }
        return "\(profile.serverIdentity)|\(userID)|\(authorizationVersion)"
    }

    private func receive(_ newSnapshot: RuntimeSessionSnapshot) {
        if newSnapshot.phase == .sessionExpired {
            captureReauthenticationIdentity(from: newSnapshot)
        }
        snapshot = newSnapshot
        refreshProfiles()
        if let profile = newSnapshot.profile, !isSelectingServer {
            serverDisplayName = profile.displayName
            serverBaseURL = profile.baseURL
            selectedLoginProfileID = profile.id
            if [.signedOut, .sessionExpired].contains(newSnapshot.phase) {
                populateLoginForm(from: profile)
            }
        }
        if isConnectingServer, !newSnapshot.phase.isServerConnectionPhase {
            isConnectingServer = false
            editingProfileID = nil
            isSelectingServer = false
        }
        if [.authenticated, .accountDisabled].contains(newSnapshot.phase) {
            isSelectingServer = false
            password = ""
        }
        switch newSnapshot.phase {
        case .sessionExpired:
            isReauthenticating = true
        case .authenticated, .signedOut, .accountDisabled:
            isReauthenticating = false
        default:
            break
        }
    }

    private func captureReauthenticationIdentity(from source: RuntimeSessionSnapshot) {
        reauthenticationUserDisplayName = source.userDisplayName ?? reauthenticationUserDisplayName
        reauthenticationUserEmail = source.userEmail ?? reauthenticationUserEmail
    }

    private func refreshProfiles() {
        serverProfiles = runtime.serverProfiles
        refreshLoginSummaries()
    }

    private func perform(
        _ work: @escaping @MainActor () async throws -> RuntimeOperationOutcome,
        onSuccess: @escaping @MainActor (RuntimeOperationOutcome) -> Void = { _ in }
    ) {
        operation?.cancel()
        operationFailure = nil
        isPerformingOperation = true
        let operationID = UUID()
        activeOperationID = operationID
        operation = Task { @MainActor in
            defer {
                if activeOperationID == operationID {
                    activeOperationID = nil
                    operation = nil
                    isPerformingOperation = false
                }
            }
            do {
                let outcome = try await work()
                refreshProfiles()
                onSuccess(outcome)
                apply(outcome.navigationDirective)
            } catch let failure as RuntimeOperationFailure {
                operationFailure = failure
                refreshProfiles()
            } catch is CancellationError {
                return
            } catch {
                operationFailure = RuntimeOperationFailure(
                    errorKind: "ServerFailure",
                    errorCode: "RUNTIME_FAILURE",
                    fieldViolations: [],
                    parameters: [:]
                )
            }
        }
    }

    private func populateLoginForm(from profile: RuntimeServerProfile) {
        selectedLoginProfileID = profile.id
        serverDisplayName = profile.displayName
        serverBaseURL = profile.baseURL
        do {
            guard let credentials = try credentialStore.load(profileID: profile.id) else {
                email = profile.isActive ? snapshot.userEmail ?? "" : ""
                password = ""
                return
            }
            email = credentials.email
            password = credentials.password
        } catch {
            email = profile.isActive ? snapshot.userEmail ?? "" : ""
            password = ""
            recordCredentialStorageFailure(error)
        }
    }

    private func refreshLoginSummaries() {
        serverLoginSummaries = serverProfiles.map { profile in
            do {
                let savedEmail = try credentialStore.loadEmail(profileID: profile.id)
                return SavedServerLoginSummary(
                    id: profile.id,
                    displayName: profile.displayName,
                    accountOrAddress: savedEmail ?? profile.baseURL
                )
            } catch {
                recordCredentialStorageFailure(error)
                return SavedServerLoginSummary(
                    id: profile.id,
                    displayName: profile.displayName,
                    accountOrAddress: profile.baseURL
                )
            }
        }
    }

    private func recordCredentialStorageFailure(_ error: Error) {
        credentialStorageCause = error
        operationFailure = RuntimeOperationFailure(
            errorKind: "StorageFailure",
            errorCode: "CREDENTIAL_STORAGE_FAILED",
            fieldViolations: [],
            parameters: [:]
        )
    }

    private func persistAuthenticatedCredentials(email: String, password: String) {
        guard
            runtime.currentSnapshot.phase == .authenticated,
            let profile = runtime.currentSnapshot.profile
        else { return }
        do {
            try credentialStore.save(
                profileID: profile.id,
                credentials: SavedServerCredentials(email: email, password: password)
            )
            clearCredentialStorageFailureIfPresent()
            refreshLoginSummaries()
        } catch {
            recordCredentialStorageFailure(error)
        }
        selectedLoginProfileID = profile.id
    }

    private func clearCredentialStorageFailureIfPresent() {
        guard operationErrorCode == "CREDENTIAL_STORAGE_FAILED" else { return }
        operationFailure = nil
        credentialStorageCause = nil
    }

    private func apply(_ directive: RuntimeNavigationDirective) {
        switch directive {
        case .resetAllStacksHome:
            navigationGeneration += 1
            isSelectingServer = false
        case .showServerProfiles:
            isSelectingServer = true
        case .hidePrivateShell:
            navigationGeneration += 1
            isSelectingServer = false
        case .keepCurrentStacks, .restoreSelectedTab, .revalidatePrivateShell:
            break
        }
    }
}

private extension SessionPhase {
    var isServerConnectionPhase: Bool {
        switch self {
        case .checkingServer, .serverConnectionFailed, .tlsRisk, .incompatibleServer:
            true
        default:
            false
        }
    }

    var canRefreshSession: Bool {
        switch self {
        case .authenticated:
            true
        default:
            false
        }
    }
}
