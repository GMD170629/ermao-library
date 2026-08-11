import Combine
import Foundation

@MainActor
final class SessionStore: ObservableObject {
    @Published private(set) var snapshot: RuntimeSessionSnapshot
    @Published private(set) var serverProfiles: [RuntimeServerProfile]
    @Published private(set) var isSelectingServer = false
    @Published private(set) var operationFailure: RuntimeOperationFailure?
    @Published private(set) var isPerformingOperation = false
    @Published private(set) var navigationGeneration = 0
    @Published private(set) var editingProfileID: String?
    @Published var serverDisplayName = ""
    @Published var serverBaseURL = ""
    @Published var email = ""
    @Published var password = ""

    private let runtime: MobileRuntimeClient
    private var observation: RuntimeObservationToken?
    private var operation: Task<Void, Never>?
    private var activeOperationID: UUID?
    private var hasStarted = false
    private var isConnectingServer = false

    init(runtime: MobileRuntimeClient) {
        self.runtime = runtime
        snapshot = runtime.currentSnapshot
        serverProfiles = runtime.serverProfiles
        observation = runtime.observe { [weak self] snapshot in
            self?.receive(snapshot)
        }
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

    func setup(name: String, email: String, password: String, locale: String) {
        let request = SetupRequest(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            email: email.trimmingCharacters(in: .whitespacesAndNewlines),
            password: password,
            locale: locale
        )
        perform { [runtime] in try await runtime.setup(request) }
    }

    func retry() {
        perform { [runtime] in try await runtime.retry() }
    }

    func enterOfflineMode() {
        perform { [runtime] in try await runtime.enterOfflineMode() }
    }

    func logout() {
        password = ""
        perform { [runtime] in try await runtime.logout() }
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
        operationErrorCode == "STORAGE_FAILURE" || operationErrorCode == "RUNTIME_FAILURE"
    }

    func dismissInfrastructureError() {
        operationFailure = nil
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

    private func receive(_ newSnapshot: RuntimeSessionSnapshot) {
        snapshot = newSnapshot
        refreshProfiles()
        if let profile = newSnapshot.profile, !isSelectingServer {
            serverDisplayName = profile.displayName
            serverBaseURL = profile.baseURL
        }
        if isConnectingServer, !newSnapshot.phase.isServerConnectionPhase {
            isConnectingServer = false
            editingProfileID = nil
            isSelectingServer = false
        }
        if [.authenticated, .offlineGrace, .accountDisabled].contains(newSnapshot.phase) {
            isSelectingServer = false
            password = ""
        }
    }

    private func refreshProfiles() {
        serverProfiles = runtime.serverProfiles
    }

    private func perform(
        _ work: @escaping @MainActor () async throws -> RuntimeOperationOutcome
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

    private func apply(_ directive: RuntimeNavigationDirective) {
        switch directive {
        case .resetAllStacksHome:
            navigationGeneration += 1
            isSelectingServer = false
        case .showServerProfiles:
            isSelectingServer = true
        case .hidePrivateShell, .enterOfflineShell:
            navigationGeneration += 1
            isSelectingServer = false
        case .keepCurrentStacks, .restoreSelectedTab:
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
        case .authenticated, .offlineGrace, .sessionUnavailable:
            true
        default:
            false
        }
    }
}
