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
import com.ermao.library.shared.modules.auth.domain.OfflineEntitlementStatus
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.auth.domain.ValidatedSessionRecord
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
import kotlinx.coroutines.runBlocking

class DefaultMobileRuntimeLifecycleTest {
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
    fun entitlementFailureAfterActivationCompensatesToThePreviousServer() = runBlocking {
        val profiles = profiles()
        val entitlements = FailingTargetEntitlements("profile-b")
        val runtime = runtime(profiles = profiles, entitlements = entitlements)
        assertIs<RuntimeOperationResult.Success>(runtime.start())

        assertIs<RuntimeOperationResult.Failure>(runtime.switchServer("profile-b"))

        assertEquals("profile-a", profiles.activeProfile()?.id)
        assertEquals("profile-a", assertIs<AppSession.Authenticated>(runtime.currentSession).profile.id)
    }

    @Test
    fun logoutCallsTheServerBeforeClearingTheCookieAndRevokesOfflineAccessOnRemoteFailure() = runBlocking {
        val profiles = profiles()
        val entitlements = InMemoryOfflineEntitlementRepository()
        val cookieVault = RecordingCookieVault()
        val gateway = FakeAuthGateway(
            onLogout = { check(!cookieVault.cleared) { "Cookie cleared before remote logout" } },
            logoutResult = ApiResult.Failure(AppError(AppErrorKind.ServiceUnavailable, "UNAVAILABLE")),
        )
        val runtime = runtime(profiles, entitlements, cookieVault = cookieVault, gateway = gateway)
        assertIs<RuntimeOperationResult.Success>(runtime.start())

        val result = assertIs<RuntimeOperationResult.Success>(runtime.logout())

        assertEquals("LOGGED_OUT_REMOTE_UNCONFIRMED", result.outcomeCode)
        assertEquals(true, cookieVault.cleared)
        assertEquals(
            OfflineEntitlementStatus.RevokedLocally,
            entitlements.load("profile-a")?.status,
        )
        assertIs<AppSession.SignedOut>(runtime.currentSession)
        Unit
    }

    private fun runtime(
        profiles: InMemoryServerProfileRepository,
        entitlements: OfflineEntitlementRepository = InMemoryOfflineEntitlementRepository(),
        probe: ServerProbe = ServerProbe { ServerProbeResult.Compatible(it.serverIdentity) },
        cookieVault: CookieVault = InMemoryCookieVault(),
        gateway: AuthGateway = FakeAuthGateway(),
    ) = DefaultMobileRuntime(
        profileRepository = profiles,
        cookieVault = cookieVault,
        entitlementRepository = entitlements,
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
    ) : AuthGateway {
        override suspend fun setupStatus(profile: ServerProfile): ApiResult<Boolean> = ApiResult.Success(true)

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

    private class FailingTargetEntitlements(
        private val failingProfileId: String,
    ) : OfflineEntitlementRepository {
        private val delegate = InMemoryOfflineEntitlementRepository()

        override suspend fun load(profileId: String): ValidatedSessionRecord? = delegate.load(profileId)

        override suspend fun save(record: ValidatedSessionRecord) {
            if (record.profileId == failingProfileId) error("Injected entitlement failure")
            delegate.save(record)
        }

        override suspend fun revoke(profileId: String) = delegate.revoke(profileId)

        override suspend fun removeEntitlement(profileId: String) = delegate.removeEntitlement(profileId)
    }
}
