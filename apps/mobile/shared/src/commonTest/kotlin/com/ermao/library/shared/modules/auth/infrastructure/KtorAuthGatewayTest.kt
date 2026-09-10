package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.InMemoryCookieVault
import com.ermao.library.shared.modules.auth.application.VerifiedSession
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.headersOf
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

class KtorAuthGatewayTest {
    @Test
    fun loginAndSessionVerificationAcceptServerAvatarImageUrl() = runBlocking {
        val paths = mutableListOf<String>()
        val gateway = gateway(SESSION, paths)
        assertIs<ApiResult.Success<Unit>>(gateway.login(profile, "reader@example.com", "fixture-password"))
        val verified = assertIs<ApiResult.Success<VerifiedSession>>(gateway.verifyCurrentSession(profile))
        assertEquals(200, verified.metadata.statusCode)
        assertEquals("reader-1", verified.value.identity.userId)
        assertEquals("zh-CN", verified.value.identity.locale)
        assertEquals(listOf("/api/auth/login", "/api/auth/me"), paths)
    }

    @Test
    fun missingAvatarImageUrlRejectsLoginAndSession() = runBlocking {
        val gateway = gateway(SESSION.replace(",\"avatarImageUrl\":\"/api/auth/avatar\"", ""))
        val login = assertIs<ApiResult.Failure>(gateway.login(profile, "reader@example.com", "fixture-password"))
        assertEquals("PROTOCOL_VIOLATION", login.error.code)
        val session = assertIs<ApiResult.Failure>(gateway.verifyCurrentSession(profile))
        assertEquals("PROTOCOL_VIOLATION", session.error.code)
    }

    @Test
    fun nullAvatarImageUrlRejectsSession() = runBlocking {
        val gateway = gateway(SESSION.replace("\"avatarImageUrl\":\"/api/auth/avatar\"", "\"avatarImageUrl\":null"))
        val failure = assertIs<ApiResult.Failure>(gateway.verifyCurrentSession(profile))
        assertEquals("PROTOCOL_VIOLATION", failure.error.code)
    }

    @Test
    fun invalidAvatarImageUrlStillRejectsSession() = runBlocking {
        val gateway = gateway(SESSION.replace("\"avatarImageUrl\":\"/api/auth/avatar\"", "\"avatarImageUrl\":42"))
        val failure = assertIs<ApiResult.Failure>(gateway.verifyCurrentSession(profile))
        assertEquals("PROTOCOL_VIOLATION", failure.error.code)
    }

    private fun gateway(body: String, paths: MutableList<String> = mutableListOf()) = KtorAuthGateway(
        ApiClientFactory(InMemoryCookieVault()),
    ) { server ->
        ApiClient(server, HttpClient(MockEngine { request ->
            paths += request.url.encodedPath
            respond(body, headers = headersOf(HttpHeaders.ContentType, "application/json"))
        }), Json { ignoreUnknownKeys = false; explicitNulls = false })
    }

    private val profile = ServerProfile(
        "fixture", "Books",
        (ServerBaseUrl.parse("https://books.example") as ServerBaseUrlParseResult.Valid).baseUrl,
        "server-fixture", true, TlsMode.SystemTrust,
    )

    private companion object {
        const val SESSION = """{"ok":true,"data":{"user":{"id":"reader-1","email":"reader@example.com","name":"Reader","role":"member","status":"active","canManageSystem":false,"canViewManualImports":false,"authzVersion":1,"avatarUrl":null,"avatarImageUrl":"/api/auth/avatar","locale":"zh-CN"},"authorization":{"isAdmin":false,"canManageSystem":false,"allLibraryScopes":true,"libraryIds":[],"canViewManualImports":false,"authzVersion":1},"preferences":{"locale":"zh-CN"}}}"""
    }
}
