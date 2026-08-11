package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.InMemoryCookieVault
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.EpochMillisClock
import com.ermao.library.shared.modules.auth.infrastructure.KtorAuthGateway
import com.ermao.library.shared.modules.servers.application.InMemoryServerProfileRepository
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.servers.infrastructure.KtorServerProbe
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

class DefaultMobileRuntimeTest {
    @Test
    fun connectRunsHealthCompatibilityAndSetupInOrder() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
            Response(200, SETUP_REQUIRED),
        )
        val runtime = harness.runtime()

        assertIs<RuntimeOperationResult.Success>(
            runtime.connectServer(ServerConnectionDraft("Books", "https://books.example")),
        )
        assertIs<AppSession.SetupRequired>(runtime.currentSession)
        assertEquals(
            listOf("/api/health", "/api/mobile/compatibility", "/api/auth/setup/status"),
            harness.requestPaths,
        )
        val saved = requireNotNull(harness.profiles.activeProfile())
        assertEquals("server-fixture", saved.serverIdentity)
        assertTrue(saved.id != saved.serverIdentity)
    }

    @Test
    fun health503WithASuccessEnvelopeStillStopsTheGate() = runBlocking {
        val harness = RuntimeHarness(Response(503, HEALTHY))
        val runtime = harness.runtime()

        assertIs<RuntimeOperationResult.Failure>(
            runtime.connectServer(ServerConnectionDraft("Books", "https://books.example")),
        )
        assertIs<AppSession.ServerConnectionFailed>(runtime.currentSession)
        assertEquals(listOf("/api/health"), harness.requestPaths)
    }

    @Test
    fun loginRequiresMeAndDeferredRefreshKeepsTheVerifiedSession() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
            Response(200, SETUP_COMPLETE),
            Response(401, UNAUTHORIZED),
            Response(200, SESSION),
            Response(200, SESSION, mapOf("X-Shuku-Session-Refresh" to "required")),
            Response(503, REFRESH_DEFERRED),
        )
        harness.profiles.upsert(profile())
        val runtime = harness.runtime()

        assertIs<RuntimeOperationResult.Failure>(runtime.start())
        assertIs<AppSession.SessionExpired>(runtime.currentSession)
        assertIs<RuntimeOperationResult.Success>(runtime.login("reader@example.com", "secret"))
        val authenticated = assertIs<AppSession.Authenticated>(runtime.currentSession)
        assertEquals("server-fixture", authenticated.identity.namespace.serverIdentity)
        assertEquals("user-1", authenticated.identity.namespace.userId)
        assertEquals(7, authenticated.identity.namespace.authorizationVersion)
        assertTrue(authenticated.authorization.allLibraryScopes)
        assertEquals(
            listOf(
                "/api/health",
                "/api/mobile/compatibility",
                "/api/auth/setup/status",
                "/api/auth/me",
                "/api/auth/login",
                "/api/auth/me",
                "/api/auth/session/refresh",
            ),
            harness.requestPaths,
        )
    }

    @Test
    fun serviceFailureDuringLoginIsRetryableAndNotInvalidCredentials() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
            Response(200, SETUP_COMPLETE),
            Response(401, UNAUTHORIZED),
            Response(503, UNAVAILABLE),
        )
        harness.profiles.upsert(profile())
        val runtime = harness.runtime()
        runtime.start()

        runtime.login("reader@example.com", "secret")

        val failure = assertIs<AppSession.LoginFailed>(runtime.currentSession)
        assertEquals("UNAVAILABLE", failure.failureCode)
        assertEquals("reader@example.com", failure.email)
    }

    @Test
    fun invalidCredentialsRemainOnTheLoginGate() = runBlocking {
        val harness = authenticatedServerHarness(Response(401, UNAUTHORIZED))
        val runtime = harness.runtime()
        runtime.start()

        assertIs<RuntimeOperationResult.Failure>(runtime.login(" Reader@Example.com ", "wrong"))

        val failure = assertIs<AppSession.LoginFailed>(runtime.currentSession)
        assertEquals("Reader@Example.com", failure.email)
        assertEquals("INVALID_CREDENTIALS", failure.failureCode)
    }

    @Test
    fun disabledAccountHasADistinctStableState() = runBlocking {
        val harness = authenticatedServerHarness(Response(403, ACCOUNT_DISABLED))
        val runtime = harness.runtime()
        runtime.start()

        assertIs<RuntimeOperationResult.Failure>(runtime.login("reader@example.com", "secret"))

        val disabled = assertIs<AppSession.AccountDisabled>(runtime.currentSession)
        assertEquals("reader@example.com", disabled.email)
    }

    @Test
    fun nestedSetupRequiredDuringLoginReturnsToTheBlockingGate() = runBlocking {
        val harness = authenticatedServerHarness(Response(409, NESTED_SETUP_REQUIRED))
        val runtime = harness.runtime()
        runtime.start()

        assertIs<RuntimeOperationResult.Failure>(runtime.login("reader@example.com", "secret"))

        assertIs<AppSession.SetupRequired>(runtime.currentSession)
        Unit
    }

    @Test
    fun setupCreatesSessionThenRequiresMeAndWritesOfflineEntitlement() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
            Response(200, SETUP_REQUIRED),
            Response(201, SETUP_SESSION),
            Response(200, SESSION),
        )
        val runtime = harness.runtime()
        runtime.connectServer(ServerConnectionDraft("Books", "https://books.example"))

        assertIs<RuntimeOperationResult.Success>(
            runtime.setupInitialAdmin("Reader", "reader@example.com", "long-secret", "zh-CN"),
        )

        val authenticated = assertIs<AppSession.Authenticated>(runtime.currentSession)
        val entitlement = requireNotNull(harness.entitlements.load(authenticated.profile.id))
        assertEquals(harness.now + 30L * 24L * 60L * 60L * 1_000L, entitlement.expiresAtEpochMillis)
        assertEquals(
            listOf(
                "/api/health",
                "/api/mobile/compatibility",
                "/api/auth/setup/status",
                "/api/auth/setup",
                "/api/auth/me",
            ),
            harness.requestPaths,
        )
    }

    @Test
    fun setupConflictRechecksStatusAndReplacesWithLogin() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
            Response(200, SETUP_REQUIRED),
            Response(409, CONFLICT),
            Response(200, SETUP_COMPLETE),
        )
        val runtime = harness.runtime()
        runtime.connectServer(ServerConnectionDraft("Books", "https://books.example"))

        val result = assertIs<RuntimeOperationResult.Success>(
            runtime.setupInitialAdmin("Reader", "reader@example.com", "long-secret", "zh-CN"),
        )

        assertEquals("SETUP_ALREADY_COMPLETED", result.outcomeCode)
        assertIs<AppSession.SignedOut>(runtime.currentSession)
        Unit
    }

    @Test
    fun explicit401OffersOfflineModeOnlyWhileEntitlementIsValid() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, COMPATIBLE),
            Response(200, SETUP_COMPLETE),
            Response(200, SESSION),
            Response(401, UNAUTHORIZED),
        )
        harness.profiles.upsert(profile())
        val runtime = harness.runtime()
        assertIs<RuntimeOperationResult.Success>(runtime.start())

        assertIs<RuntimeOperationResult.Failure>(runtime.refreshCurrentSession())
        val expired = assertIs<AppSession.SessionExpired>(runtime.currentSession)
        assertTrue(expired.entitlementExpiresAtEpochMillis != null)
        assertIs<RuntimeOperationResult.Success>(runtime.enterOfflineMode())
        assertIs<AppSession.OfflineGrace>(runtime.currentSession)
        Unit
    }

    @Test
    fun unavailableSavedServerDoesNotExpireOrClearTheSession() = runBlocking {
        val harness = RuntimeHarness(Response(503, HEALTHY))
        harness.profiles.upsert(profile())
        val runtime = harness.runtime()

        assertIs<RuntimeOperationResult.Failure>(runtime.start())

        val unavailable = assertIs<AppSession.SessionUnavailable>(runtime.currentSession)
        assertEquals("server-fixture", unavailable.profile.id)
        assertEquals(null, unavailable.lastKnownIdentity)
        assertEquals(listOf("/api/health"), harness.requestPaths)
    }

    @Test
    fun incompatibleProtocolStopsBeforeSetupAndLogin() = runBlocking {
        val harness = RuntimeHarness(
            Response(200, HEALTHY),
            Response(200, INCOMPATIBLE_PROTOCOL),
        )
        val runtime = harness.runtime()

        assertIs<RuntimeOperationResult.Failure>(
            runtime.connectServer(ServerConnectionDraft("Books", "https://books.example")),
        )

        val incompatible = assertIs<AppSession.IncompatibleServer>(runtime.currentSession)
        assertEquals("UNSUPPORTED_PROTOCOL_VERSION", incompatible.reasonCode)
        assertEquals(
            listOf("/api/health", "/api/mobile/compatibility"),
            harness.requestPaths,
        )
    }

    private suspend fun authenticatedServerHarness(loginResponse: Response): RuntimeHarness = RuntimeHarness(
        Response(200, HEALTHY),
        Response(200, COMPATIBLE),
        Response(200, SETUP_COMPLETE),
        Response(401, UNAUTHORIZED),
        loginResponse,
    ).also { harness -> harness.profiles.upsert(profile()) }

    private class RuntimeHarness(vararg responses: Response) {
        val profiles = InMemoryServerProfileRepository()
        val entitlements = InMemoryOfflineEntitlementRepository()
        var now = 1_000L
        val requestPaths = mutableListOf<String>()
        private val remaining = ArrayDeque(responses.toList())
        private val json = Json { ignoreUnknownKeys = false; explicitNulls = false }

        fun runtime(): DefaultMobileRuntime = DefaultMobileRuntime(
            profileRepository = profiles,
            cookieVault = cookieVault,
            entitlementRepository = entitlements,
            serverProbe = KtorServerProbe(clientProvider = clientProvider),
            authGateway = KtorAuthGateway(ApiClientFactory(cookieVault), clientProvider),
            clock = EpochMillisClock { now },
        )

        private val cookieVault = InMemoryCookieVault()
        private val clientProvider: (ServerProfile) -> ApiClient = { profile ->
                val engine = MockEngine { request ->
                    requestPaths += request.url.encodedPath
                    val response = remaining.removeFirst()
                    val headers = buildList {
                        add(HttpHeaders.ContentType to listOf("application/json"))
                        response.headers.forEach { (key, value) -> add(key to listOf(value)) }
                    }
                    respond(response.body, HttpStatusCode.fromValue(response.status), headersOf(*headers.toTypedArray()))
                }
                ApiClient(profile, HttpClient(engine), json)
            }
    }

    private data class Response(
        val status: Int,
        val body: String,
        val headers: Map<String, String> = emptyMap(),
    )

    private companion object {
        val HEALTHY = """{"ok":true,"data":{"service":"ermao-books","status":"ok"}}"""
        val COMPATIBLE = """{"ok":true,"data":{"service":"ermao-books","serverIdentity":"server-fixture","serverVersion":"1.0","protocol":{"version":1,"minimumSupportedClientVersion":1},"readerSchemaVersion":4,"capabilities":{"setup":true,"cookieSession":true,"readerV3":true,"mediaRange":true,"managedOfflineDownloads":false}}}"""
        val INCOMPATIBLE_PROTOCOL = """{"ok":true,"data":{"service":"ermao-books","serverIdentity":"server-fixture","serverVersion":"1.0","protocol":{"version":99,"minimumSupportedClientVersion":1},"readerSchemaVersion":4,"capabilities":{"setup":true,"cookieSession":true,"readerV3":true,"mediaRange":true,"managedOfflineDownloads":false}}}"""
        val SETUP_REQUIRED = """{"ok":true,"data":{"initialized":false}}"""
        val SETUP_COMPLETE = """{"ok":true,"data":{"initialized":true}}"""
        val UNAUTHORIZED = """{"ok":false,"error":{"message":"UNAUTHORIZED","code":"UNAUTHORIZED"}}"""
        val UNAVAILABLE = """{"ok":false,"error":{"message":"busy","code":"UNAVAILABLE"}}"""
        val ACCOUNT_DISABLED = """{"ok":false,"error":{"message":"disabled","code":"ACCOUNT_DISABLED"}}"""
        val NESTED_SETUP_REQUIRED = """{"ok":false,"error":{"message":"setup required","details":{"code":"SETUP_REQUIRED"}}}"""
        val REFRESH_DEFERRED = """{"ok":false,"error":{"message":"SESSION_REFRESH_DEFERRED","code":"SESSION_REFRESH_DEFERRED"}}"""
        val SESSION = """{"ok":true,"data":{"user":{"id":"user-1","email":"reader@example.com","name":"Reader","role":"member","status":"active","canManageSystem":false,"canViewManualImports":false,"authzVersion":7,"avatarUrl":null,"locale":"zh-CN"},"authorization":{"isAdmin":false,"canManageSystem":false,"allLibraryScopes":true,"monitorFolderIds":[],"canViewManualImports":false,"authzVersion":7},"preferences":{"locale":"zh-CN"}}}"""
        val SETUP_SESSION = """{"ok":true,"data":{"initialized":true,"user":{"id":"user-1","email":"reader@example.com","name":"Reader","role":"admin","status":"active","canManageSystem":true,"canViewManualImports":true,"authzVersion":1,"avatarUrl":null,"locale":"zh-CN"},"authorization":{"isAdmin":true,"canManageSystem":true,"allLibraryScopes":true,"monitorFolderIds":[],"canViewManualImports":true,"authzVersion":1},"preferences":{"locale":"zh-CN"}}}"""
        val CONFLICT = """{"ok":false,"error":{"message":"already initialized","code":"CONFLICT"}}"""

        fun profile(): ServerProfile {
            val baseUrl = (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl
            return ServerProfile(
                id = "server-fixture",
                displayName = "Books",
                baseUrl = baseUrl,
                serverIdentity = "server-fixture",
                isActive = true,
                tlsMode = TlsMode.SystemTrust,
            )
        }
    }
}
