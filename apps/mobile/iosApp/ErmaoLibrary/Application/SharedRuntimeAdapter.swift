import Foundation
@preconcurrency import ErmaoShared

enum AppCompositionRoot {
    @MainActor
    static func makeRuntimeClient(
        cookieStore: KeychainCookiePayloadStore = KeychainCookiePayloadStore()
    ) -> MobileRuntimeClient {
        let profiles = UserDefaultsServerProfileStore()
        let entitlements = UserDefaultsOfflineEntitlementStore()
        let bridge = IosCompositionKt.createIosMobileRuntimeBridge(
            cookieStore: cookieStore,
            profileStore: profiles,
            entitlementStore: entitlements
        )
        return SharedMobileRuntimeClient(bridge: bridge)
    }
}

extension KeychainCookiePayloadStore: SecureCookiePayloadStore {
    func loadCookiePayload(profileId: String) throws -> PlatformStoragePayload {
        PlatformStoragePayload(value: try load(profileID: profileId))
    }

    func save(profileId: String, payload: String) throws {
        try save(profileID: profileId, payload: payload)
    }

    func clear(profileId: String) throws {
        try clear(profileID: profileId)
    }
}

extension UserDefaultsServerProfileStore: ServerProfilePayloadStore {
    func loadProfilesPayload() throws -> PlatformStoragePayload {
        PlatformStoragePayload(value: loadProfiles())
    }
}

extension UserDefaultsOfflineEntitlementStore: OfflineEntitlementPayloadStore {
    func loadEntitlementsPayload() throws -> PlatformStoragePayload {
        PlatformStoragePayload(value: loadEntitlements())
    }
}

@MainActor
final class SharedMobileRuntimeClient: MobileRuntimeClient {
    private let bridge: MobileRuntimeBridge

    init(bridge: MobileRuntimeBridge) {
        self.bridge = bridge
    }

    var currentSnapshot: RuntimeSessionSnapshot {
        SharedSessionMapper.map(bridge.currentSession)
    }

    var serverProfiles: [RuntimeServerProfile] {
        bridge.serverProfiles.map(SharedServerProfileMapper.map)
    }

    func observe(
        _ onChange: @escaping @MainActor (RuntimeSessionSnapshot) -> Void
    ) -> RuntimeObservationToken {
        let sink = MainActorSessionSink(onChange)
        let observer = SharedSnapshotObserver(sink: sink)
        let observation = bridge.observeSession(observer_: observer)
        return SharedObservationToken(observation: observation, observer: observer)
    }

    func start() async throws -> RuntimeOperationOutcome {
        try await run { bridge.start(completion: $0) }
    }

    func connectServer(_ request: ConnectServerRequest) async throws -> RuntimeOperationOutcome {
        try await run {
            bridge.connectServer(
                displayName: request.displayName,
                baseUrl: request.baseURL,
                completion: $0
            )
        }
    }

    func editServer(
        profileID: String,
        request: ConnectServerRequest
    ) async throws -> RuntimeOperationOutcome {
        try await run {
            bridge.editServer(
                profileId: profileID,
                displayName: request.displayName,
                baseUrl: request.baseURL,
                completion: $0
            )
        }
    }

    func switchServer(profileID: String) async throws -> RuntimeOperationOutcome {
        try await run { bridge.switchServer(profileId: profileID, completion: $0) }
    }

    func removeServer(profileID: String) async throws -> RuntimeOperationOutcome {
        try await run { bridge.removeServer(profileId: profileID, completion: $0) }
    }

    func restoreSystemTrust(profileID: String) async throws -> RuntimeOperationOutcome {
        try await run { bridge.restoreSystemTrust(profileId: profileID, completion: $0) }
    }

    func acceptInsecureTLS() async throws -> RuntimeOperationOutcome {
        try await run { bridge.acceptInsecureTls(completion: $0) }
    }

    func loginToServer(
        baseURL: String,
        email: String,
        password: String
    ) async throws -> RuntimeOperationOutcome {
        try await run {
            bridge.loginToServer(
                baseUrl: baseURL,
                email: email,
                password: password,
                completion: $0
            )
        }
    }

    func loginToServerAcceptingInsecureTLS(
        baseURL: String,
        email: String,
        password: String
    ) async throws -> RuntimeOperationOutcome {
        try await run {
            bridge.loginToServerAcceptingInsecureTls(
                baseUrl: baseURL,
                email: email,
                password: password,
                completion: $0
            )
        }
    }

    func login(_ request: LoginRequest) async throws -> RuntimeOperationOutcome {
        try await run {
            bridge.login(email: request.email, password: request.password, completion: $0)
        }
    }

    func setup(_ request: SetupRequest) async throws -> RuntimeOperationOutcome {
        try await run {
            bridge.setupInitialAdmin(
                name: request.name,
                email: request.email,
                password: request.password,
                locale: request.locale,
                completion: $0
            )
        }
    }

    func retry() async throws -> RuntimeOperationOutcome {
        try await run { bridge.retry(completion: $0) }
    }

    func refreshCurrentSession() async throws -> RuntimeOperationOutcome {
        try await run { bridge.refreshCurrentSession(completion: $0) }
    }

    func enterOfflineMode() async throws -> RuntimeOperationOutcome {
        try await run { bridge.enterOfflineMode(completion: $0) }
    }

    func logout() async throws -> RuntimeOperationOutcome {
        try await run { bridge.logout(completion: $0) }
    }

    func close() {
        bridge.close()
    }

    private func run(
        _ operation: (OperationCompletion) -> Observation
    ) async throws -> RuntimeOperationOutcome {
        try Task.checkCancellation()
        let gate = OperationContinuationGate()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                guard gate.install(continuation) else { return }
                let observation = operation(SharedOperationCompletion { result in
                    gate.complete(result: result)
                })
                gate.attach(observation)
            }
        } onCancel: {
            gate.cancel()
        }
    }
}

private enum SharedSessionMapper {
    static func map(_ snapshot: AppSessionSnapshot) -> RuntimeSessionSnapshot {
        let authorizationVersion = snapshot.authorizationVersion?.int64Value
        let authorization = authorizationVersion.map {
            RuntimeAuthorization(
                isAdmin: snapshot.isAdmin,
                canManageSystem: snapshot.canManageSystem,
                allLibraryScopes: snapshot.allLibraryScopes,
                monitorFolderIDs: snapshot.monitorFolderIds,
                canViewManualImports: snapshot.canViewManualImports,
                authorizationVersion: $0
            )
        }
        let entitlementExpiresAt = snapshot.entitlementExpiresAtEpochMillis.map {
            Date(timeIntervalSince1970: TimeInterval($0.int64Value) / 1_000)
        }
        return RuntimeSessionSnapshot(
            phase: mapKind(snapshot.kind.name),
            profile: makeCurrentProfile(snapshot),
            userID: snapshot.userId,
            userDisplayName: snapshot.userDisplayName,
            userEmail: snapshot.userEmail,
            userAvatarURL: snapshot.userAvatarUrl,
            userLocale: snapshot.userLocale,
            authorization: authorization,
            entitlementExpiresAt: entitlementExpiresAt,
            reasonCode: snapshot.reasonCode
        )
    }

    private static func mapKind(_ name: String) -> SessionPhase {
        switch name {
        case "NoServer": .noServer
        case "CheckingServer": .checkingServer
        case "ServerConnectionFailed": .serverConnectionFailed
        case "TlsRisk": .tlsRisk
        case "SetupRequired": .setupRequired
        case "SettingUp": .settingUp
        case "SetupFailed": .setupFailed
        case "SignedOut": .signedOut
        case "Authenticating": .authenticating
        case "LoginFailed": .loginFailed
        case "AccountDisabled": .accountDisabled
        case "Authenticated": .authenticated
        case "SessionUnavailable": .sessionUnavailable
        case "SessionExpired": .sessionExpired
        case "OfflineGrace": .offlineGrace
        case "IncompatibleServer": .incompatibleServer
        default: .sessionUnavailable
        }
    }

    private static func makeCurrentProfile(_ snapshot: AppSessionSnapshot) -> RuntimeServerProfile? {
        guard
            let id = snapshot.profileId,
            let displayName = snapshot.profileDisplayName,
            let baseURL = snapshot.profileBaseUrl,
            let serverIdentity = snapshot.profileServerIdentity
        else {
            return nil
        }
        return RuntimeServerProfile(
            id: id,
            displayName: displayName,
            baseURL: baseURL,
            serverIdentity: serverIdentity,
            isActive: true,
            tlsMode: SharedServerProfileMapper.tlsMode(snapshot.profileTlsMode?.name)
        )
    }
}

private enum SharedServerProfileMapper {
    static func map(_ snapshot: ServerProfileSnapshot) -> RuntimeServerProfile {
        RuntimeServerProfile(
            id: snapshot.id,
            displayName: snapshot.displayName,
            baseURL: snapshot.baseUrl,
            serverIdentity: snapshot.serverIdentity,
            isActive: snapshot.isActive,
            tlsMode: tlsMode(snapshot.tlsMode.name)
        )
    }

    static func tlsMode(_ name: String?) -> RuntimeTLSMode {
        name == "InsecureSkipAllValidation" ? .insecureSkipAllValidation : .systemTrust
    }
}

@MainActor
private final class MainActorSessionSink {
    private let onChange: @MainActor (RuntimeSessionSnapshot) -> Void

    init(_ onChange: @escaping @MainActor (RuntimeSessionSnapshot) -> Void) {
        self.onChange = onChange
    }

    func receive(_ snapshot: RuntimeSessionSnapshot) {
        onChange(snapshot)
    }
}

private final class SharedSnapshotObserver: SessionSnapshotObserver {
    private let sink: MainActorSessionSink

    init(sink: MainActorSessionSink) {
        self.sink = sink
    }

    func onSessionChanged(snapshot: AppSessionSnapshot) {
        let mapped = SharedSessionMapper.map(snapshot)
        Task { @MainActor [sink] in
            sink.receive(mapped)
        }
    }
}

private final class SharedOperationCompletion: OperationCompletion {
    private let completion: (OperationResultSnapshot) -> Void

    init(_ completion: @escaping (OperationResultSnapshot) -> Void) {
        self.completion = completion
    }

    func complete(result: OperationResultSnapshot) {
        completion(result)
    }
}

private final class OperationContinuationGate: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<RuntimeOperationOutcome, Error>?
    private var operationObservation: Observation?
    private var isFinished = false

    func install(_ continuation: CheckedContinuation<RuntimeOperationOutcome, Error>) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !isFinished else {
            continuation.resume(throwing: CancellationError())
            return false
        }
        self.continuation = continuation
        return true
    }

    func attach(_ observation: Observation) {
        lock.lock()
        let shouldCancel = isFinished
        if !isFinished {
            operationObservation = observation
        }
        lock.unlock()
        if shouldCancel {
            observation.cancel()
        }
    }

    func complete(result: OperationResultSnapshot) {
        let finished = finish()
        let parameters = mapStringParameters(result.parameters)
        let violations = result.fieldViolations.map {
            RuntimeFieldViolation(field: $0.field, code: $0.code)
        }
        if result.succeeded {
            finished.continuation?.resume(
                returning: RuntimeOperationOutcome(
                    outcomeCode: result.outcomeCode,
                    fieldViolations: violations,
                    parameters: parameters,
                    navigationDirective: RuntimeNavigationDirective(
                        rawValue: result.navigationDirective.name
                    ) ?? .keepCurrentStacks
                )
            )
        } else {
            finished.continuation?.resume(
                throwing: RuntimeOperationFailure(
                    errorKind: result.errorKind ?? "ServerFailure",
                    errorCode: result.errorCode ?? "RUNTIME_FAILURE",
                    fieldViolations: violations,
                    parameters: parameters
                )
            )
        }
    }

    private func mapStringParameters(_ source: Any) -> [String: String] {
        guard let dictionary = source as? [AnyHashable: Any] else { return [:] }
        return dictionary.reduce(into: [:]) { result, entry in
            guard let key = entry.key as? String, let value = entry.value as? String else { return }
            result[key] = value
        }
    }

    func cancel() {
        let finished = finish()
        finished.observation?.cancel()
        finished.continuation?.resume(throwing: CancellationError())
    }

    private func finish() -> (
        continuation: CheckedContinuation<RuntimeOperationOutcome, Error>?,
        observation: Observation?
    ) {
        lock.lock()
        defer { lock.unlock() }
        guard !isFinished else { return (nil, nil) }
        isFinished = true
        let finished = (continuation, operationObservation)
        continuation = nil
        operationObservation = nil
        return finished
    }
}

private final class SharedObservationToken: RuntimeObservationToken {
    private var observation: Observation?
    private var retainedObserver: SharedSnapshotObserver?

    init(observation: Observation, observer: SharedSnapshotObserver) {
        self.observation = observation
        retainedObserver = observer
    }

    func cancel() {
        observation?.cancel()
        observation = nil
        retainedObserver = nil
    }
}
