import Foundation

@MainActor
final class PreviewMobileRuntime: MobileRuntimeClient {
    var currentSnapshot: RuntimeSessionSnapshot
    var serverProfiles: [RuntimeServerProfile]
    private var observers: [UUID: @MainActor (RuntimeSessionSnapshot) -> Void] = [:]

    init(
        snapshot: RuntimeSessionSnapshot = .noServer,
        serverProfiles: [RuntimeServerProfile]? = nil
    ) {
        currentSnapshot = snapshot
        self.serverProfiles = serverProfiles ?? snapshot.profile.map { [$0] } ?? []
    }

    func observe(
        _ onChange: @escaping @MainActor (RuntimeSessionSnapshot) -> Void
    ) -> RuntimeObservationToken {
        let identifier = UUID()
        observers[identifier] = onChange
        return PreviewObservation { [weak self] in
            Task { @MainActor in self?.observers.removeValue(forKey: identifier) }
        }
    }

    func start() async throws -> RuntimeOperationOutcome { .success }

    func connectServer(_ request: ConnectServerRequest) async throws -> RuntimeOperationOutcome {
        let profile = RuntimeServerProfile(
            id: UUID().uuidString,
            displayName: request.displayName,
            baseURL: request.baseURL,
            serverIdentity: "preview-\(serverProfiles.count + 1)",
            isActive: true,
            tlsMode: request.tlsMode
        )
        serverProfiles = serverProfiles.map { replacingActive($0, activeID: profile.id) } + [profile]
        transition(to: signedOut(profile))
        return .success
    }

    func editServer(
        profileID: String,
        request: ConnectServerRequest
    ) async throws -> RuntimeOperationOutcome {
        guard let existing = serverProfiles.first(where: { $0.id == profileID }) else {
            throw previewFailure("SERVER_PROFILE_NOT_FOUND")
        }
        let updated = RuntimeServerProfile(
            id: existing.id,
            displayName: request.displayName,
            baseURL: request.baseURL,
            serverIdentity: existing.serverIdentity,
            isActive: existing.isActive,
            tlsMode: existing.tlsMode
        )
        serverProfiles = serverProfiles.map { $0.id == profileID ? updated : $0 }
        if updated.isActive { transition(to: signedOut(updated)) }
        return .success
    }

    func switchServer(profileID: String) async throws -> RuntimeOperationOutcome {
        guard let selected = serverProfiles.first(where: { $0.id == profileID }) else {
            throw previewFailure("SERVER_PROFILE_NOT_FOUND")
        }
        serverProfiles = serverProfiles.map { replacingActive($0, activeID: profileID) }
        transition(to: signedOut(replacingActive(selected, activeID: profileID)))
        return RuntimeOperationOutcome(
            outcomeCode: "SERVER_SWITCHED",
            fieldViolations: [],
            parameters: [:],
            navigationDirective: .resetAllStacksHome
        )
    }

    func removeServer(profileID: String) async throws -> RuntimeOperationOutcome {
        let removedActive = serverProfiles.first(where: { $0.id == profileID })?.isActive == true
        serverProfiles.removeAll { $0.id == profileID }
        if removedActive { transition(to: .noServer) }
        return RuntimeOperationOutcome(
            outcomeCode: "SERVER_REMOVED",
            fieldViolations: [],
            parameters: [:],
            navigationDirective: .showServerProfiles
        )
    }

    func restoreSystemTrust(profileID: String) async throws -> RuntimeOperationOutcome {
        serverProfiles = serverProfiles.map { profile in
            guard profile.id == profileID else { return profile }
            return RuntimeServerProfile(
                id: profile.id,
                displayName: profile.displayName,
                baseURL: profile.baseURL,
                serverIdentity: profile.serverIdentity,
                isActive: profile.isActive,
                tlsMode: .systemTrust
            )
        }
        return .success
    }

    func acceptInsecureTLS() async throws -> RuntimeOperationOutcome { .success }

    func loginToServer(
        baseURL: String,
        email: String,
        password: String
    ) async throws -> RuntimeOperationOutcome {
        try await loginToServer(
            baseURL: baseURL,
            email: email,
            password: password,
            tlsMode: .systemTrust
        )
    }

    func loginToServerAcceptingInsecureTLS(
        baseURL: String,
        email: String,
        password: String
    ) async throws -> RuntimeOperationOutcome {
        try await loginToServer(
            baseURL: baseURL,
            email: email,
            password: password,
            tlsMode: .insecureSkipAllValidation
        )
    }

    func login(_ request: LoginRequest) async throws -> RuntimeOperationOutcome {
        guard let profile = currentSnapshot.profile else { throw previewFailure("NO_ACTIVE_SERVER") }
        transition(to: authenticated(profile: profile, email: request.email))
        return .success
    }

    func setup(_ request: SetupRequest) async throws -> RuntimeOperationOutcome {
        guard let profile = currentSnapshot.profile else { throw previewFailure("NO_ACTIVE_SERVER") }
        transition(to: authenticated(profile: profile, email: request.email, name: request.name))
        return .success
    }

    func retry() async throws -> RuntimeOperationOutcome { .success }
    func refreshCurrentSession() async throws -> RuntimeOperationOutcome { .success }

    func logout() async throws -> RuntimeOperationOutcome {
        guard let profile = currentSnapshot.profile else { return .success }
        transition(to: signedOut(profile))
        return RuntimeOperationOutcome(
            outcomeCode: "LOGGED_OUT_LOCALLY",
            fieldViolations: [],
            parameters: [:],
            navigationDirective: .hidePrivateShell
        )
    }

    func close() {}

    func transition(to snapshot: RuntimeSessionSnapshot) {
        currentSnapshot = snapshot
        observers.values.forEach { $0(snapshot) }
    }

    private func signedOut(_ profile: RuntimeServerProfile) -> RuntimeSessionSnapshot {
        RuntimeSessionSnapshot(
            phase: .signedOut,
            profile: profile,
            userDisplayName: nil,
            userEmail: nil,
            reasonCode: nil
        )
    }

    private func loginToServer(
        baseURL: String,
        email: String,
        password: String,
        tlsMode: RuntimeTLSMode
    ) async throws -> RuntimeOperationOutcome {
        guard let url = URL(string: baseURL), let host = url.host, !email.isEmpty, !password.isEmpty else {
            throw previewFailure("INVALID_LOGIN_FORM")
        }
        let existing = serverProfiles.first { $0.baseURL == baseURL }
        let profile = RuntimeServerProfile(
            id: existing?.id ?? UUID().uuidString,
            displayName: host,
            baseURL: baseURL,
            serverIdentity: existing?.serverIdentity ?? "preview-\(serverProfiles.count + 1)",
            isActive: true,
            tlsMode: tlsMode
        )
        serverProfiles = serverProfiles
            .filter { $0.id != profile.id }
            .map { replacingActive($0, activeID: profile.id) } + [profile]
        transition(to: authenticated(profile: profile, email: email))
        return RuntimeOperationOutcome(
            outcomeCode: "AUTHENTICATED",
            fieldViolations: [],
            parameters: [:],
            navigationDirective: .resetAllStacksHome
        )
    }

    private func authenticated(
        profile: RuntimeServerProfile,
        email: String,
        name: String? = nil
    ) -> RuntimeSessionSnapshot {
        RuntimeSessionSnapshot(
            phase: .authenticated,
            profile: profile,
            userID: "preview-user",
            userDisplayName: name ?? email,
            userEmail: email,
            authorization: RuntimeAuthorization(
                isAdmin: false,
                canManageSystem: false,
                allLibraryScopes: true,
                libraryIDs: [],
                canViewManualImports: false,
                authorizationVersion: 1
            ),
            reasonCode: nil
        )
    }

    private func replacingActive(
        _ profile: RuntimeServerProfile,
        activeID: String
    ) -> RuntimeServerProfile {
        RuntimeServerProfile(
            id: profile.id,
            displayName: profile.displayName,
            baseURL: profile.baseURL,
            serverIdentity: profile.serverIdentity,
            isActive: profile.id == activeID,
            tlsMode: profile.tlsMode
        )
    }

    private func previewFailure(_ code: String) -> RuntimeOperationFailure {
        RuntimeOperationFailure(
            errorKind: "InvalidRequest",
            errorCode: code,
            fieldViolations: [],
            parameters: [:]
        )
    }
}

private final class PreviewObservation: RuntimeObservationToken {
    private var cancellation: (() -> Void)?

    init(cancellation: @escaping () -> Void) {
        self.cancellation = cancellation
    }

    func cancel() {
        cancellation?()
        cancellation = nil
    }
}
