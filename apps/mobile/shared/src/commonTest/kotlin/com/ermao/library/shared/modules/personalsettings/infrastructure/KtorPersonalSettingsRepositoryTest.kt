package com.ermao.library.shared.modules.personalsettings.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatarMimeType
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatarUpload
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsContext
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsErrorKind
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsResult
import com.ermao.library.shared.modules.personalsettings.createPersonalSettingsContext
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.OutgoingContent
import io.ktor.http.headersOf
import io.ktor.utils.io.ByteChannel
import io.ktor.utils.io.readRemaining
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.io.readByteArray
import kotlinx.serialization.json.Json

class KtorPersonalSettingsRepositoryTest {
    @Test
    fun loadsSessionAndMapsAvatarLocaleWithoutLeakingWireTypes() = runBlocking {
        val harness = Harness(Response(200, SESSION))

        val snapshot = assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.loadSettings(context()),
        ).value
        val settings = assertIs<com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsSnapshot>(snapshot)

        assertEquals("user-1", settings.account.id)
        assertEquals("Reader", settings.account.displayName)
        assertEquals("/api/auth/avatar", settings.account.avatarUrl)
        assertEquals(PersonalSettingsLocale.EnUs, settings.preferences.locale)
        assertEquals(HttpMethod.Get, harness.requests.single().method)
        assertEquals("/base/api/auth/me", harness.requests.single().path)
    }

    @Test
    fun mutationsUseEstablishedMethodsPathsAndJsonBodies() = runBlocking {
        val harness =
            Harness(
                Response(200, USER),
                Response(200, USER),
                Response(200, PASSWORD_CHANGED),
                Response(200, PREFERENCES_ZH),
                Response(200, USER_WITHOUT_AVATAR),
                Response(200, COMPATIBILITY),
            )

        assertIs<PersonalSettingsResult.Content<*>>(harness.repository.updateName(context(), "  New Reader  "))
        assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.updateEmail(context(), " new@example.com ", "current-secret"),
        )
        assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.updatePassword(context(), "current-secret", "new-password"),
        )
        assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.updateLocale(context(), PersonalSettingsLocale.ZhCn),
        )
        assertIs<PersonalSettingsResult.Content<*>>(harness.repository.deleteAvatar(context()))
        val about = assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.loadServerAbout(context()),
        ).value

        assertEquals("2.4.0", assertIs<com.ermao.library.shared.modules.personalsettings.domain.PersonalServerAbout>(about).serverVersion)
        assertEquals(
            listOf(
                HttpMethod.Patch to "/base/api/auth/account/name",
                HttpMethod.Patch to "/base/api/auth/account/email",
                HttpMethod.Patch to "/base/api/auth/account/password",
                HttpMethod.Patch to "/base/api/auth/preferences",
                HttpMethod.Delete to "/base/api/auth/avatar",
                HttpMethod.Get to "/base/api/mobile/compatibility",
            ),
            harness.requests.map { it.method to it.path },
        )
        assertEquals("""{"name":"New Reader"}""", harness.requests[0].body)
        assertEquals(
            """{"email":"new@example.com","currentPassword":"current-secret"}""",
            harness.requests[1].body,
        )
        assertEquals(
            """{"currentPassword":"current-secret","newPassword":"new-password"}""",
            harness.requests[2].body,
        )
        assertEquals("""{"preferences":{"locale":"zh-CN"}}""", harness.requests[3].body)
    }

    @Test
    fun avatarUploadUsesTypedMultipartWithoutAcceptingAPlatformPath() = runBlocking {
        val harness = Harness(Response(200, USER))
        val bytes = "avatar-content".encodeToByteArray()

        val account = assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.uploadAvatar(
                context(),
                PersonalAvatarUpload(bytes, PersonalAvatarMimeType.Png),
            ),
        ).value
        val request = harness.requests.single()

        assertEquals("/api/auth/avatar", assertIs<com.ermao.library.shared.modules.personalsettings.domain.PersonalAccount>(account).avatarUrl)
        assertEquals(HttpMethod.Post, request.method)
        assertEquals("/base/api/auth/avatar", request.path)
        assertContains(requireNotNull(request.contentType), "multipart/form-data")
        assertContains(request.body, "name=\"avatar\"")
        assertContains(request.body, "filename=\"avatar.png\"")
        assertContains(request.body, "image/png")
        assertContains(request.body, "avatar-content")
    }

    @Test
    fun avatarDownloadPreservesTypedBytesEtagAndNotModifiedState() = runBlocking {
        val harness =
            Harness(
                Response(
                    statusCode = 200,
                    body = "image-content",
                    contentType = "image/webp",
                    headers = mapOf(HttpHeaders.ETag to "avatar-v2"),
                ),
                Response(
                    statusCode = 304,
                    body = "",
                    contentType = "image/webp",
                ),
            )

        val loaded = assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.loadAvatar(context(), "avatar-v1"),
        ).value
        val fresh = assertIs<com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatar>(loaded)
        val unchanged = assertIs<PersonalSettingsResult.Content<*>>(
            harness.repository.loadAvatar(context(), "avatar-v2"),
        ).value
        val notModified = assertIs<com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatar>(unchanged)

        assertContentEquals("image-content".encodeToByteArray(), fresh.bytes)
        assertEquals("image/webp", fresh.contentType)
        assertEquals("avatar-v2", fresh.etag)
        assertEquals(false, fresh.notModified)
        assertContentEquals(byteArrayOf(), notModified.bytes)
        assertEquals(true, notModified.notModified)
        assertEquals("avatar-v1", harness.requests[0].headers[HttpHeaders.IfNoneMatch])
        assertEquals("avatar-v2", harness.requests[1].headers[HttpHeaders.IfNoneMatch])
    }

    @Test
    fun localizedServerMessagesNeverDriveOrEscapeTheTypedError() = runBlocking {
        val harness =
            Harness(
                Response(
                    400,
                    """{"ok":false,"error":{"message":"当前密码不正确"}}""",
                ),
            )

        val failure = assertIs<PersonalSettingsResult.Failure>(
            harness.repository.updateEmail(context(), "reader@example.com", "wrong-password"),
        )

        assertEquals(PersonalSettingsErrorKind.Validation, failure.error.kind)
        assertEquals("BAD_REQUEST", failure.error.code)
        assertEquals(emptyList(), failure.error.fieldViolations)
        assertEquals(false, failure.toString().contains("当前密码不正确"))
    }

    @Test
    fun httpFailuresMapByStatusAndStableCodesOnly() = runBlocking {
        val cases =
            listOf(
                ErrorCase(
                    statusCode = 401,
                    errorBody = """{"message":"请重新登录","code":"UNAUTHORIZED"}""",
                    expectedKind = PersonalSettingsErrorKind.Unauthorized,
                    expectedCode = "UNAUTHORIZED",
                ),
                ErrorCase(
                    statusCode = 409,
                    errorBody = """{"message":"邮箱已占用","code":"EMAIL_IN_USE"}""",
                    expectedKind = PersonalSettingsErrorKind.Conflict,
                    expectedCode = "EMAIL_IN_USE",
                ),
                ErrorCase(
                    statusCode = 413,
                    errorBody = """{"message":"文件过大","code":"AVATAR_TOO_LARGE"}""",
                    expectedKind = PersonalSettingsErrorKind.Validation,
                    expectedCode = "AVATAR_TOO_LARGE",
                ),
                ErrorCase(
                    statusCode = 422,
                    errorBody =
                        """{"message":"validation failed","code":"VALIDATION_FAILED","details":[{"loc":["body","name"],"type":"string_too_long","msg":"too long"}]}""",
                    expectedKind = PersonalSettingsErrorKind.Validation,
                    expectedCode = "VALIDATION_FAILED",
                    expectedFields = listOf("name"),
                ),
                ErrorCase(
                    statusCode = 429,
                    errorBody = """{"message":"请求过于频繁"}""",
                    expectedKind = PersonalSettingsErrorKind.RateLimited,
                    expectedCode = "RATE_LIMITED",
                ),
                ErrorCase(
                    statusCode = 503,
                    errorBody = """{"message":"稍后再试","code":"AVATAR_UPDATE_DEFERRED"}""",
                    expectedKind = PersonalSettingsErrorKind.Server,
                    expectedCode = "AVATAR_UPDATE_DEFERRED",
                ),
            )

        cases.forEach { case ->
            val harness = Harness(Response(case.statusCode, """{"ok":false,"error":${case.errorBody}}"""))

            val failure = assertIs<PersonalSettingsResult.Failure>(
                harness.repository.updateName(context(), "Reader"),
            )

            assertEquals(case.expectedKind, failure.error.kind)
            assertEquals(case.expectedCode, failure.error.code)
            assertEquals(case.expectedFields, failure.error.fieldViolations.map { violation -> violation.field })
            assertEquals(false, failure.toString().contains("请重新登录"))
            assertEquals(false, failure.toString().contains("邮箱已占用"))
            assertEquals(false, failure.toString().contains("文件过大"))
            assertEquals(false, failure.toString().contains("请求过于频繁"))
            assertEquals(false, failure.toString().contains("稍后再试"))
        }
    }

    @Test
    fun passwordChangeRequiresBothConfirmationFlags() = runBlocking {
        val responses =
            listOf(
                """{"ok":true,"data":{"passwordChanged":false,"requiresLogin":true}}""",
                """{"ok":true,"data":{"passwordChanged":true,"requiresLogin":false}}""",
            )

        responses.forEach { response ->
            val harness = Harness(Response(200, response))

            val failure = assertIs<PersonalSettingsResult.Failure>(
                harness.repository.updatePassword(context(), "current-secret", "new-password"),
            )

            assertEquals(PersonalSettingsErrorKind.Protocol, failure.error.kind)
            assertEquals("PASSWORD_CHANGE_NOT_CONFIRMED", failure.error.code)
        }
    }

    @Test
    fun strictSuccessParsingReturnsTypedProtocolFailure() = runBlocking {
        val harness =
            Harness(
                Response(
                    200,
                    """{"ok":true,"data":{"user":{"id":"user-1","name":"Reader"}}}""",
                ),
            )

        val failure = assertIs<PersonalSettingsResult.Failure>(
            harness.repository.updateName(context(), "Reader"),
        )

        assertEquals(PersonalSettingsErrorKind.Protocol, failure.error.kind)
        assertEquals("PROTOCOL_VIOLATION", failure.error.code)
    }

    @Test
    fun cancellationPropagatesInsteadOfBecomingASettingsFailure() = runBlocking {
        val repository =
            KtorPersonalSettingsRepository { profile ->
                ApiClient(
                    profile,
                    HttpClient(MockEngine { throw CancellationException("cancelled") }),
                    Json { ignoreUnknownKeys = false },
                )
            }

        assertFailsWith<CancellationException> {
            repository.loadSettings(context())
        }
        Unit
    }

    @Test
    fun validationStopsBeforeNetworkAndUsesStableCodes() = runBlocking {
        val harness = Harness()

        val emptyAvatar = assertIs<PersonalSettingsResult.Failure>(
            harness.repository.uploadAvatar(
                context(),
                PersonalAvatarUpload(byteArrayOf(), PersonalAvatarMimeType.Webp),
            ),
        )
        val shortPassword = assertIs<PersonalSettingsResult.Failure>(
            harness.repository.updatePassword(context(), "current", "short"),
        )

        assertEquals("AVATAR_EMPTY", emptyAvatar.error.code)
        assertEquals("INVALID_NEW_PASSWORD", shortPassword.error.code)
        assertEquals(emptyList(), harness.requests)
    }

    private fun context(): PersonalSettingsContext {
        return createPersonalSettingsContext(
            profileId = "profile-1",
            displayName = "Books",
            baseUrl = "https://books.example/base",
            serverIdentity = "server-fixture",
            acceptsInsecureTls = false,
        )
    }

    private inner class Harness(vararg responses: Response) {
        val requests = mutableListOf<CapturedRequest>()
        private val pending = ArrayDeque(responses.toList())
        val repository =
            KtorPersonalSettingsRepository { profile ->
                val engine =
                    MockEngine { request ->
                        requests +=
                            CapturedRequest(
                                method = request.method,
                                path = request.url.encodedPath,
                                body = request.body.readText(),
                                contentType = request.body.contentType?.toString() ?: request.headers[HttpHeaders.ContentType],
                                headers = request.headers.entries().associate { (key, value) -> key to value.first() },
                            )
                        val response = pending.removeFirst()
                        respond(
                            content = response.body,
                            status = HttpStatusCode.fromValue(response.statusCode),
                            headers =
                                headersOf(
                                    *(response.headers + (HttpHeaders.ContentType to response.contentType))
                                        .map { (key, value) -> key to listOf(value) }
                                        .toTypedArray(),
                                ),
                        )
                    }
                ApiClient(
                    profile,
                    HttpClient(engine),
                    Json {
                        ignoreUnknownKeys = false
                        explicitNulls = false
                    },
                )
            }
    }

    private suspend fun OutgoingContent.readText(): String =
        when (this) {
            is OutgoingContent.ByteArrayContent -> bytes().decodeToString()
            is OutgoingContent.ReadChannelContent -> readFrom().readRemaining().readByteArray().decodeToString()
            is OutgoingContent.WriteChannelContent -> coroutineScope {
                val channel = ByteChannel()
                launch {
                    try {
                        writeTo(channel)
                    } finally {
                        channel.close()
                    }
                }
                channel.readRemaining().readByteArray().decodeToString()
            }
            else -> ""
        }

    private data class CapturedRequest(
        val method: HttpMethod,
        val path: String,
        val body: String,
        val contentType: String?,
        val headers: Map<String, String>,
    )

    private data class Response(
        val statusCode: Int,
        val body: String,
        val contentType: String = "application/json",
        val headers: Map<String, String> = emptyMap(),
    )

    private data class ErrorCase(
        val statusCode: Int,
        val errorBody: String,
        val expectedKind: PersonalSettingsErrorKind,
        val expectedCode: String,
        val expectedFields: List<String> = emptyList(),
    )

    private companion object {
        const val USER =
            """{"ok":true,"data":{"user":{"id":"user-1","email":"reader@example.com","name":"Reader","role":"member","status":"active","canManageSystem":false,"canViewManualImports":false,"authzVersion":7,"avatarUrl":"/api/auth/avatar"}}}"""
        const val USER_WITHOUT_AVATAR =
            """{"ok":true,"data":{"user":{"id":"user-1","email":"reader@example.com","name":"Reader","role":"member","status":"active","canManageSystem":false,"canViewManualImports":false,"authzVersion":7,"avatarUrl":null}}}"""
        const val SESSION =
            """{"ok":true,"data":{"user":{"id":"user-1","email":"reader@example.com","name":"Reader","role":"member","status":"active","canManageSystem":false,"canViewManualImports":false,"authzVersion":7,"avatarUrl":"/api/auth/avatar","locale":"en-US"},"authorization":{"isAdmin":false,"canManageSystem":false,"allLibraryScopes":true,"monitorFolderIds":[],"canViewManualImports":false,"authzVersion":7},"preferences":{"locale":"en-US"}}}"""
        const val PASSWORD_CHANGED =
            """{"ok":true,"data":{"passwordChanged":true,"requiresLogin":true}}"""
        const val PREFERENCES_ZH =
            """{"ok":true,"data":{"preferences":{"locale":"zh-CN"}}}"""
        const val COMPATIBILITY =
            """{"ok":true,"data":{"service":"ermao-books","serverIdentity":"server-fixture","serverVersion":"2.4.0","protocol":{"version":1,"minimumSupportedClientVersion":1},"readerSchemaVersion":4,"capabilities":{"setup":true,"cookieSession":true,"readerV3":true,"mediaRange":true,"managedOfflineDownloads":false}}}"""
    }
}
