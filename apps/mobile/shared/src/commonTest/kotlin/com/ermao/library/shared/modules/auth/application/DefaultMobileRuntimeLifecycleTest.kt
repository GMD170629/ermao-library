package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.network.CookieVault
import com.ermao.library.shared.core.network.InMemoryCookieVault
import com.ermao.library.shared.core.network.PersistedCookie
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.Authorization
import com.ermao.library.shared.modules.auth.domain.EpochMillisClock
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord
import com.ermao.library.shared.modules.servers.application.InMemoryServerProfileRepository
import com.ermao.library.shared.modules.servers.application.ServerProbe
import com.ermao.library.shared.modules.servers.application.ServerProbeResult
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield

class DefaultMobileRuntimeLifecycleTest {
    @Test
    fun savedVerifiedSessionPublishesAuthenticatedBeforeNetworkValidationCompletes() = runBlocking {
        val activeProfile = profile("profile-a", "server-a", true)
        val profiles = InMemoryServerProfileRepository().also { it.upsert(activeProfile) }
        val verifiedSessions = InMemoryVerifiedSessionRepository()
        val identity = identity(activeProfile)
        val authorization = authorization()
        verifiedSessions.save(
            VerifiedSessionRecord.from(activeProfile.id, identity, authorization, validatedAtEpochMillis = 500),
        )
        val probeGate = CompletableDeferred<Unit>()
        val runtime = runtime(
            profiles = profiles,
            verifiedSessions = verifiedSessions,
            probe = ServerProbe {
                probeGate.await()
                ServerProbeResult.Failure(AppError(AppErrorKind.Timeout, "TIMEOUT"))
            },
        )

        val startup = async { runtime.start() }
        while (runtime.currentSession !is AppSession.Authenticated) yield()

        val restored = assertIs<AppSession.Authenticated>(runtime.currentSession)
        assertEquals(identity, restored.identity)
        assertEquals(authorization, restored.authorization)
        probeGate.complete(Unit)
        assertIs<RuntimeOperationResult.Success>(startup.await())
        assertIs<AppSession.Authenticated>(runtime.currentSession)
        Unit
    }

    @Test
    fun serverIdentityChangeRefreshesTheProfileWithoutBlockingTheSession() = runBlocking {
        val activeProfile = profile("profile-a", "server-a", true)
        val profiles = InMemoryServerProfileRepository().also { it.upsert(activeProfile) }
        val verifiedSessions = InMemoryVerifiedSessionRepository().also {
            val previouslyVerifiedProfile = activeProfile.copy(serverIdentity = "previous-session-server")
            it.save(
                VerifiedSessionRecord.from(
                    activeProfile.id,
                    identity(previouslyVerifiedProfile),
                    authorization(),
                    validatedAtEpochMillis = 500,
                ),
            )
        }
        val cookies = RecordingCookieVault()
        val runtime = runtime(
            profiles = profiles,
            verifiedSessions = verifiedSessions,
            cookieVault = cookies,
            probe = ServerProbe { ServerProbeResult.Compatible("different-server") },
        )

        assertIs<RuntimeOperationResult.Success>(runtime.start())

        val authenticated = assertIs<AppSession.Authenticated>(runtime.currentSession)
        assertEquals("different-server", authenticated.profile.serverIdentity)
        assertEquals("different-server", profiles.activeProfile()?.serverIdentity)
        assertEquals(false, cookies.cleared)
    }

    @Test
    fun setupStatusRegressionDoesNotInvalidateAnAlreadyVerifiedSession() = runBlocking {
        val activeProfile = profile("profile-a", "server-a", true)
        val profiles = InMemoryServerProfileRepository().also { it.upsert(activeProfile) }
        val verifiedSessions = InMemoryVerifiedSessionRepository().also {
            it.save(
                VerifiedSessionRecord.from(
                    activeProfile.id,
                    identity(activeProfile),
                    authorization(),
                    validatedAtEpochMillis = 500,
                ),
            )
        }
        val cookies = RecordingCookieVault()
        val runtime = runtime(
            profiles = profiles,
            verifiedSessions = verifiedSessions,
            cookieVault = cookies,
            gateway = FakeAuthGateway(setupCompleted = false),
        )

        assertIs<RuntimeOperationResult.Success>(runtime.start())

        assertIs<AppSession.Authenticated>(runtime.currentSession)
        assertEquals(false, cookies.cleared)
        assertEquals(true, verifiedSessions.load(activeProfile.id) != null)
    }

    @Test
    fun failedTargetPreflightKeepsThePreviousServerActive() = runBlocking {
        val profiles = profiles()
        val runtime = runtime(
            profiles = profiles,
            probe = ServerProbe { profile ->
                if (profile.id == "profile-b") {
                    ServerProbeResult.Failure(AppError(AppErrorKind.NetworkUnavailable, "OFFLINE"))
                } else {
                    ServerProbeResult.Compatible(profile.serverIdentity)
                }
            },
        )
        assertIs<RuntimeOperationResult.Success>(runtime.start())

        assertIs<RuntimeOperationResult.Failure>(runtime.switchServer("profile-b"))

        assertEquals("profile-a", profiles.activeProfile()?.id)
        assertEquals("profile-a", assertIs<AppSession.Authenticated>(runtime.currentSession).profile.id)
    }

    @Test
    fun verifiedSessionFailureAfterActivationCompensatesToThePreviousServer() = runBlocking {
        val profiles = profiles()
        val verifiedSessions = FailingTargetVerifiedSessions("profile-b")
        val runtime = runtime(profiles = profiles, verifiedSessions = verifiedSessions)
        assertIs<RuntimeOperationResult.Success>(runtime.start())

        assertIs<RuntimeOperationResult.Failure>(runtime.switchServer("profile-b"))

        assertEquals("profile-a", profiles.activeProfile()?.id)
        assertEquals("profile-a", assertIs<AppSession.Authenticated>(runtime.currentSession).profile.id)
    }

    @Test
    fun logoutCallsTheServerBeforeClearingTheCookieAndRemovesVerifiedSessionOnRemoteFailure() = runBlocking {
        val profiles = profiles()
        val verifiedSessions = InMemoryVerifiedSessionRepository()
        val cookieVault = RecordingCookieVault()
        val gateway = FakeAuthGateway(
            onLogout = { check(!cookieVault.cleared) { "Cookie cleared before remote logout" } },
            logoutResult = ApiResult.Failure(AppError(AppErrorKind.ServiceUnavailable, "UNAVAILABLE")),
        )
        val runtime = runtime(profiles, verifiedSessions, cookieVault = cookieVault, gateway = gateway)
        assertIs<RuntimeOperationResult.Success>(runtime.start())

        val result = assertIs<RuntimeOperationResult.Success>(runtime.logout())

        assertEquals("LOGGED_OUT_REMOTE_UNCONFIRMED", result.outcomeCode)
        assertEquals(true, cookieVault.cleared)
        assertEquals(null, verifiedSessions.load("profile-a"))
        assertIs<AppSession.SignedOut>(runtime.currentSession)
        Unit
    }

    private fun runtime(
        profiles: InMemoryServerProfileRepository,
        verifiedSessions: VerifiedSessionRepository = InMemoryVerifiedSessionRepository(),
        probe: ServerProbe = ServerProbe { ServerProbeResult.Compatible(it.serverIdentity) },
        cookieVault: CookieVault = InMemoryCookieVault(),
        gateway: AuthGateway = FakeAuthGateway(),
    ) = DefaultMobileRuntime(
        profileRepository = profiles,
        cookieVault = cookieVault,
        verifiedSessionRepository = verifiedSessions,
        serverProbe = probe,
        authGateway = gateway,
        clock = EpochMillisClock { 1_000 },
    )

    private suspend fun profiles() = InMemoryServerProfileRepository().also { repository ->
        repository.upsert(profile("profile-a", "server-a", true))
        repository.upsert(profile("profile-b", "server-b", false))
    }

    private fun profile(id: String, serverIdentity: String, active: Boolean): ServerProfile {
        val parsed = ServerBaseUrl.parse("https://$serverIdentity.example") as ServerBaseUrlParseResult.Valid
        return ServerProfile(id, id, parsed.baseUrl, serverIdentity, active, TlsMode.SystemTrust)
    }

    private class FakeAuthGateway(
        private val onLogout: () -> Unit = {},
        private val logoutResult: ApiResult<Unit> = ApiResult.Success(Unit),
        private val setupCompleted: Boolean = true,
    ) : AuthGateway {
        override suspend fun setupStatus(profile: ServerProfile): ApiResult<Boolean> =
            ApiResult.Success(setupCompleted)

        override suspend fun setupInitialAdmin(
            profile: ServerProfile,
            name: String,
            email: String,
            password: String,
            locale: String,
        ): ApiResult<Unit> = error("Not used")

        override suspend fun login(
            profile: ServerProfile,
            email: String,
            password: String,
        ): ApiResult<Unit> = error("Not used")

        override suspend fun verifyCurrentSession(profile: ServerProfile): ApiResult<VerifiedSession> {
            val identity = SessionIdentity(
                userId = "user-${profile.id}",
                email = "${profile.id}@example.com",
                displayName = profile.displayName,
                namespace = PrivateDataNamespace(profile.serverIdentity, "user-${profile.id}", 1),
            )
            return ApiResult.Success(
                VerifiedSession(
                    identity,
                    Authorization(false, false, true, emptySet(), false, 1),
                ),
            )
        }

        override suspend fun logout(profile: ServerProfile): ApiResult<Unit> {
            onLogout()
            return logoutResult
        }
    }

    private class RecordingCookieVault : CookieVault {
        var cleared = false
            private set

        override suspend fun load(profileId: String): List<PersistedCookie> = emptyList()

        override suspend fun mutate(
            profileId: String,
            transform: (List<PersistedCookie>) -> List<PersistedCookie>,
        ): List<PersistedCookie> = transform(emptyList())

        override suspend fun clear(profileId: String) {
            cleared = true
        }
    }

    private fun identity(profile: ServerProfile) = SessionIdentity(
        userId = "user-${profile.id}",
        email = "${profile.id}@example.com",
        displayName = profile.displayName,
        namespace = PrivateDataNamespace(profile.serverIdentity, "user-${profile.id}", 1),
    )

    private fun authorization() = Authorization(false, false, true, emptySet(), false, 1)

    private class FailingTargetVerifiedSessions(
        private val failingProfileId: String,
    ) : VerifiedSessionRepository {
        private val delegate = InMemoryVerifiedSessionRepository()

        override suspend fun load(profileId: String): VerifiedSessionRecord? = delegate.load(profileId)

        override suspend fun save(record: VerifiedSessionRecord) {
            if (record.profileId == failingProfileId) error("Injected verified-session failure")
            delegate.save(record)
        }

        override suspend fun removeSession(profileId: String) = delegate.removeSession(profileId)
    }
}
