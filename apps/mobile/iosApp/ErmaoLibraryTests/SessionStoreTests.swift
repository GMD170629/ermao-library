import Combine
import XCTest
@testable import ErmaoLibrary

@MainActor
final class SessionStoreTests: XCTestCase {
    func testExpiredSessionRestoresSavedServerAccountAndPassword() throws {
        let profile = makeProfile(id: "saved", baseURL: "https://books.example.com/base", active: true)
        let credentials = InMemoryCredentialStore()
        try credentials.save(
            profileID: profile.id,
            credentials: SavedServerCredentials(
                email: "reader@example.com",
                password: "remembered-password"
            )
        )
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .sessionExpired,
                profile: profile,
                userDisplayName: "Reader",
                userEmail: "reader@example.com",
                reasonCode: "UNAUTHORIZED"
            )
        )

        let store = SessionStore(runtime: runtime, credentialStore: credentials)

        XCTAssertEqual(store.serverBaseURL, profile.baseURL)
        XCTAssertEqual(store.email, "reader@example.com")
        XCTAssertEqual(store.password, "remembered-password")
        XCTAssertEqual(store.selectedLoginProfile?.id, profile.id)
    }

    func testSelectingAnotherServerOnlyFillsTheLoginForm() throws {
        let first = makeProfile(id: "first", baseURL: "https://first.example.com", active: true)
        let second = makeProfile(id: "second", baseURL: "https://second.example.com", active: false)
        let credentials = InMemoryCredentialStore()
        try credentials.save(
            profileID: second.id,
            credentials: SavedServerCredentials(email: "second@example.com", password: "second-password")
        )
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .signedOut,
                profile: first,
                userDisplayName: nil,
                userEmail: nil,
                reasonCode: nil
            ),
            serverProfiles: [first, second]
        )
        let store = SessionStore(runtime: runtime, credentialStore: credentials)

        store.selectServerForLogin(second)

        XCTAssertEqual(store.serverBaseURL, second.baseURL)
        XCTAssertEqual(store.email, "second@example.com")
        XCTAssertEqual(store.password, "second-password")
        XCTAssertEqual(store.snapshot.profile?.id, first.id, "Selection must not connect before sign-in")
        XCTAssertEqual(store.otherServerLoginSummaries.map(\.id), [first.id])
        XCTAssertEqual(store.serverLoginSummaries.first(where: { $0.id == second.id })?.accountOrAddress, "second@example.com")
    }

    func testUnifiedLoginSavesHostnameProfileAndCredentialsAfterAuthentication() async throws {
        let credentials = InMemoryCredentialStore()
        let runtime = PreviewMobileRuntime()
        let store = SessionStore(runtime: runtime, credentialStore: credentials)
        store.serverBaseURL = "https://books.example.com/library"
        store.email = "reader@example.com"
        store.password = "saved-password"

        store.loginToCurrentServer()
        await waitUntilIdle(store)

        let profile = try XCTUnwrap(store.snapshot.profile)
        XCTAssertEqual(store.snapshot.phase, .authenticated)
        XCTAssertEqual(profile.displayName, "books.example.com")
        XCTAssertEqual(
            try credentials.load(profileID: profile.id),
            SavedServerCredentials(email: "reader@example.com", password: "saved-password")
        )
        XCTAssertEqual(store.serverLoginSummaries.first?.accountOrAddress, "reader@example.com")
    }

    func testDeletingSelectedServerClearsCredentialsAndForm() async throws {
        let profile = makeProfile(id: "saved", baseURL: "https://books.example.com", active: true)
        let credentials = InMemoryCredentialStore()
        try credentials.save(
            profileID: profile.id,
            credentials: SavedServerCredentials(email: "reader@example.com", password: "saved-password")
        )
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .signedOut,
                profile: profile,
                userDisplayName: nil,
                userEmail: nil,
                reasonCode: nil
            )
        )
        let store = SessionStore(runtime: runtime, credentialStore: credentials)

        store.deleteSelectedLoginServer()
        await waitUntilIdle(store)

        XCTAssertTrue(store.serverBaseURL.isEmpty)
        XCTAssertTrue(store.email.isEmpty)
        XCTAssertTrue(store.password.isEmpty)
        XCTAssertNil(store.selectedLoginProfile)
        XCTAssertNil(try credentials.load(profileID: profile.id))
    }

    func testSuccessfulLoginSurfacesCredentialSaveFailureWithoutLosingSession() async {
        let credentials = FailingCredentialStore(failingOperation: .save)
        let runtime = PreviewMobileRuntime()
        let store = SessionStore(runtime: runtime, credentialStore: credentials)
        store.serverBaseURL = "https://books.example.com"
        store.email = "reader@example.com"
        store.password = "saved-password"

        store.loginToCurrentServer()
        await waitUntilIdle(store)

        XCTAssertEqual(store.snapshot.phase, .authenticated)
        XCTAssertEqual(store.operationErrorCode, "CREDENTIAL_STORAGE_FAILED")
        XCTAssertTrue(store.isPresentingInfrastructureError)
    }

    func testSuccessfulDeleteSurfacesCredentialClearFailureAndStillClearsForm() async {
        let profile = makeProfile(id: "saved", baseURL: "https://books.example.com", active: true)
        let credentials = FailingCredentialStore(failingOperation: .clear)
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .signedOut,
                profile: profile,
                userDisplayName: nil,
                userEmail: nil,
                reasonCode: nil
            )
        )
        let store = SessionStore(runtime: runtime, credentialStore: credentials)

        store.deleteSelectedLoginServer()
        await waitUntilIdle(store)

        XCTAssertTrue(store.serverProfiles.isEmpty)
        XCTAssertTrue(store.serverBaseURL.isEmpty)
        XCTAssertEqual(store.operationErrorCode, "CREDENTIAL_STORAGE_FAILED")
        XCTAssertTrue(store.isPresentingInfrastructureError)
    }

    func testServerSummaryFallsBackToAddressWithoutSavedAccount() {
        let profile = makeProfile(id: "saved", baseURL: "https://books.example.com", active: true)
        let store = SessionStore(
            runtime: PreviewMobileRuntime(
                snapshot: RuntimeSessionSnapshot(
                    phase: .signedOut,
                    profile: profile,
                    userDisplayName: nil,
                    userEmail: nil,
                    reasonCode: nil
                )
            ),
            credentialStore: InMemoryCredentialStore()
        )

        XCTAssertEqual(store.serverLoginSummaries.first?.displayName, "books.example.com")
        XCTAssertEqual(store.serverLoginSummaries.first?.accountOrAddress, profile.baseURL)
    }

    func testCredentialLoadFailureIsNotTreatedAsMissingCredentials() {
        let profile = makeProfile(id: "saved", baseURL: "https://books.example.com", active: true)
        let store = SessionStore(
            runtime: PreviewMobileRuntime(
                snapshot: RuntimeSessionSnapshot(
                    phase: .sessionExpired,
                    profile: profile,
                    userDisplayName: "Reader",
                    userEmail: "reader@example.com",
                    reasonCode: "UNAUTHORIZED"
                )
            ),
            credentialStore: FailingCredentialStore(failingOperation: .load)
        )

        XCTAssertEqual(store.operationErrorCode, "CREDENTIAL_STORAGE_FAILED")
        XCTAssertTrue(store.isPresentingInfrastructureError)
        XCTAssertEqual(store.serverLoginSummaries.first?.accountOrAddress, profile.baseURL)
    }

    func testConnectAndLoginFollowTheGateSequence() async {
        let runtime = PreviewMobileRuntime()
        let credentials = InMemoryCredentialStore()
        let store = SessionStore(runtime: runtime, credentialStore: credentials)
        store.serverDisplayName = "Home Library"
        store.serverBaseURL = "https://books.example.com/base"
        let signedOut = expectation(description: "server connection reaches signed-out gate")
        let signedOutObservation = store.$snapshot
            .filter { $0.phase == .signedOut }
            .first()
            .sink { _ in signedOut.fulfill() }

        store.connectServer()
        await fulfillment(of: [signedOut], timeout: 1)

        XCTAssertEqual(store.snapshot.phase, .signedOut)
        XCTAssertEqual(store.snapshot.profile?.displayName, "Home Library")
        XCTAssertEqual(store.snapshot.profile?.baseURL, "https://books.example.com/base")

        store.email = "reader@example.com"
        store.password = "correct horse battery staple"
        let authenticated = expectation(description: "verified session reaches shell")
        let authenticatedObservation = store.$snapshot
            .filter { $0.phase == .authenticated }
            .first()
            .sink { _ in authenticated.fulfill() }
        store.login()
        await fulfillment(of: [authenticated], timeout: 1)

        XCTAssertEqual(store.snapshot.phase, .authenticated)
        XCTAssertEqual(store.snapshot.userEmail, "reader@example.com")
        XCTAssertTrue(store.password.isEmpty)
        withExtendedLifetime((signedOutObservation, authenticatedObservation)) {}
    }

    func testSelectingAnotherServerDoesNotExposeAuthenticatedShell() {
        let profile = RuntimeServerProfile(
            id: "server-a",
            displayName: "Home Library",
            baseURL: "https://books.example.com",
            serverIdentity: "identity-a",
            isActive: true,
            tlsMode: .systemTrust
        )
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .authenticated,
                profile: profile,
                userDisplayName: "Reader",
                userEmail: "reader@example.com",
                reasonCode: nil
            )
        )
        let credentials = InMemoryCredentialStore()
        let store = SessionStore(runtime: runtime, credentialStore: credentials)

        store.chooseAnotherServer()

        XCTAssertTrue(store.isSelectingServer)
    }

    func testSetupCreatesAuthenticatedAdministrator() async {
        let profile = RuntimeServerProfile(
            id: "server-a",
            displayName: "Home Library",
            baseURL: "https://books.example.com",
            serverIdentity: "identity-a",
            isActive: true,
            tlsMode: .systemTrust
        )
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .setupRequired,
                profile: profile,
                userDisplayName: nil,
                userEmail: nil,
                reasonCode: nil
            )
        )
        let credentials = InMemoryCredentialStore()
        let store = SessionStore(runtime: runtime, credentialStore: credentials)
        let authenticated = expectation(description: "setup reaches authenticated shell")
        let observation = store.$snapshot
            .filter { $0.phase == .authenticated }
            .first()
            .sink { _ in authenticated.fulfill() }

        store.setup(
            name: "Administrator",
            email: "admin@example.com",
            password: "long-password",
            locale: "en-US"
        )
        await fulfillment(of: [authenticated], timeout: 1)

        XCTAssertEqual(store.snapshot.userDisplayName, "Administrator")
        XCTAssertEqual(store.snapshot.userEmail, "admin@example.com")
        XCTAssertEqual(
            try credentials.load(profileID: profile.id),
            SavedServerCredentials(email: "admin@example.com", password: "long-password")
        )
        withExtendedLifetime(observation) {}
    }

    func testSuccessfulSetupSurfacesCredentialSaveFailureWithoutLosingSession() async {
        let profile = makeProfile(id: "server-a", baseURL: "https://books.example.com", active: true)
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .setupRequired,
                profile: profile,
                userDisplayName: nil,
                userEmail: nil,
                reasonCode: nil
            )
        )
        let store = SessionStore(
            runtime: runtime,
            credentialStore: FailingCredentialStore(failingOperation: .save)
        )

        store.setup(
            name: "Administrator",
            email: "admin@example.com",
            password: "long-password",
            locale: "en-US"
        )
        await waitUntilIdle(store)

        XCTAssertEqual(store.snapshot.phase, .authenticated)
        XCTAssertEqual(store.operationErrorCode, "CREDENTIAL_STORAGE_FAILED")
        XCTAssertTrue(store.isPresentingInfrastructureError)
    }

    func testSwitchAndRemoveMaintainSingleActiveServer() async {
        let first = RuntimeServerProfile(
            id: "first",
            displayName: "First",
            baseURL: "https://first.example.com",
            serverIdentity: "identity-first",
            isActive: true,
            tlsMode: .systemTrust
        )
        let second = RuntimeServerProfile(
            id: "second",
            displayName: "Second",
            baseURL: "https://second.example.com",
            serverIdentity: "identity-second",
            isActive: false,
            tlsMode: .insecureSkipAllValidation
        )
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .signedOut,
                profile: first,
                userDisplayName: nil,
                userEmail: nil,
                reasonCode: nil
            ),
            serverProfiles: [first, second]
        )
        let store = SessionStore(runtime: runtime)

        store.switchServer(profileID: second.id)
        await waitUntilIdle(store)
        XCTAssertEqual(store.serverProfiles.filter(\.isActive).map(\.id), [second.id])

        store.restoreSystemTrust(profileID: second.id)
        await waitUntilIdle(store)
        XCTAssertEqual(store.serverProfiles.first(where: { $0.id == second.id })?.tlsMode, .systemTrust)

        store.removeServer(profileID: first.id)
        await waitUntilIdle(store)
        XCTAssertEqual(store.serverProfiles.map(\.id), [second.id])
    }

    func testLogoutCanSkipSecondNamespacePurgeAfterPasswordChange() async throws {
        let profile = makeProfile(id: "server-a", baseURL: "https://books.example.com", active: true)
        let cache = RecordingPrivateContentCache()
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .authenticated,
                profile: profile,
                userID: "reader-1",
                userDisplayName: "Reader",
                userEmail: "reader@example.com",
                authorization: RuntimeAuthorization(
                    isAdmin: false,
                    canManageSystem: false,
                    allLibraryScopes: true,
                    libraryIDs: [],
                    canViewManualImports: false,
                    authorizationVersion: 7
                ),
                reasonCode: nil
            )
        )
        let store = SessionStore(runtime: runtime, privateContentCache: cache)

        try await store.logoutAwaitingCompletion(purgeNamespace: false)

        let removedNamespaces = await cache.removedNamespaces()
        XCTAssertEqual(removedNamespaces, [])
        XCTAssertEqual(store.snapshot.phase, .signedOut)
    }

    func testServerSwitchClosesReadersAndTransfersBeforeRemovingOldNamespace() async throws {
        let first = makeProfile(id: "first", baseURL: "https://first.example.com", active: true)
        let second = makeProfile(id: "second", baseURL: "https://second.example.com", active: false)
        let events = PrivateTransitionEvents()
        let cache = OrderedPrivateContentCache(events: events)
        let runtime = PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .authenticated,
                profile: first,
                userID: "reader-1",
                userDisplayName: "Reader",
                userEmail: "reader@example.com",
                authorization: RuntimeAuthorization(
                    isAdmin: false,
                    canManageSystem: false,
                    allLibraryScopes: true,
                    libraryIDs: [],
                    canViewManualImports: false,
                    authorizationVersion: 7
                ),
                reasonCode: nil
            ),
            serverProfiles: [first, second]
        )
        let store = SessionStore(
            runtime: runtime,
            privateContentCache: cache,
            preparePrivateNamespaceTransition: {
                await events.append("reader-and-downloads-closed")
            }
        )

        store.switchServer(profileID: second.id)
        await waitUntilIdle(store)

        let recordedEvents = await events.values()
        XCTAssertEqual(
            recordedEvents,
            [
                "reader-and-downloads-closed",
                "removed:identity-first|reader-1|7",
            ]
        )
        XCTAssertEqual(store.snapshot.profile?.id, second.id)
    }

    private func waitUntilIdle(_ store: SessionStore) async {
        for _ in 0..<100 where store.isPerformingOperation {
            await Task.yield()
        }
    }

    private func makeProfile(id: String, baseURL: String, active: Bool) -> RuntimeServerProfile {
        RuntimeServerProfile(
            id: id,
            displayName: URL(string: baseURL)?.host ?? id,
            baseURL: baseURL,
            serverIdentity: "identity-\(id)",
            isActive: active,
            tlsMode: .systemTrust
        )
    }
}

private final class InMemoryCredentialStore: ServerCredentialStore {
    private var credentialsByProfileID: [String: SavedServerCredentials] = [:]

    func load(profileID: String) throws -> SavedServerCredentials? {
        credentialsByProfileID[profileID]
    }

    func save(profileID: String, credentials: SavedServerCredentials) throws {
        credentialsByProfileID[profileID] = credentials
    }

    func clear(profileID: String) throws {
        credentialsByProfileID.removeValue(forKey: profileID)
    }
}

private final class FailingCredentialStore: ServerCredentialStore {
    enum Operation {
        case load
        case save
        case clear
    }

    private let failingOperation: Operation

    init(failingOperation: Operation) {
        self.failingOperation = failingOperation
    }

    func load(profileID: String) throws -> SavedServerCredentials? {
        if failingOperation == .load { throw TestCredentialStorageError.failed }
        return nil
    }

    func save(profileID: String, credentials: SavedServerCredentials) throws {
        if failingOperation == .save { throw TestCredentialStorageError.failed }
    }

    func clear(profileID: String) throws {
        if failingOperation == .clear { throw TestCredentialStorageError.failed }
    }
}

private enum TestCredentialStorageError: Error {
    case failed
}

private actor RecordingPrivateContentCache: PrivateContentCacheClearing {
    private var namespaces: [String] = []

    func removeNamespace(_ namespace: String) async throws {
        namespaces.append(namespace)
    }

    func removedNamespaces() -> [String] {
        namespaces
    }
}

private actor PrivateTransitionEvents {
    private var events: [String] = []

    func append(_ event: String) { events.append(event) }
    func values() -> [String] { events }
}

private struct OrderedPrivateContentCache: PrivateContentCacheClearing {
    let events: PrivateTransitionEvents

    func removeNamespace(_ namespace: String) async throws {
        await events.append("removed:\(namespace)")
    }
}
