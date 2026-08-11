import Combine
import XCTest
@testable import ErmaoLibrary

@MainActor
final class SessionStoreTests: XCTestCase {
    func testConnectAndLoginFollowTheGateSequence() async {
        let runtime = PreviewMobileRuntime()
        let store = SessionStore(runtime: runtime)
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
        let store = SessionStore(runtime: runtime)

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
        let store = SessionStore(runtime: runtime)
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
        withExtendedLifetime(observation) {}
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

    private func waitUntilIdle(_ store: SessionStore) async {
        for _ in 0..<100 where store.isPerformingOperation {
            await Task.yield()
        }
    }
}
