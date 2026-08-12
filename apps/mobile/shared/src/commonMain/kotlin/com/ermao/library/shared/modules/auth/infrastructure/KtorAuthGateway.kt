package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.auth.application.AuthGateway
import com.ermao.library.shared.modules.auth.application.VerifiedSession
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.serialization.json.Json

class KtorAuthGateway(
    private val clients: ApiClientFactory,
    private val clientProvider: (ServerProfile) -> ApiClient = clients::create,
) : AuthGateway {
    private val json = Json { explicitNulls = false }

    override suspend fun setupStatus(profile: ServerProfile): ApiResult<Boolean> = withClient(profile) { client ->
        when (
            val result = client.execute(
                ApiRequest(
                    method = ApiMethod.Get,
                    apiPath = "/api/auth/setup/status",
                    responseDeserializer = SetupStatusWire.serializer(),
                ),
            )
        ) {
            is ApiResult.Success -> ApiResult.Success(result.value.initialized, result.metadata)
            is ApiResult.Failure -> result
        }
    }

    override suspend fun setupInitialAdmin(
        profile: ServerProfile,
        name: String,
        email: String,
        password: String,
        locale: String,
    ): ApiResult<Unit> = withClient(profile) { client ->
        val body = json.encodeToString(
            SetupRequestWire.serializer(),
            SetupRequestWire(name, email, password, locale),
        )
        when (
            val result = client.execute(
                ApiRequest(
                    method = ApiMethod.Post,
                    apiPath = "/api/auth/setup",
                    responseDeserializer = SetupSessionWire.serializer(),
                    requestBody = body,
                ),
            )
        ) {
            is ApiResult.Success -> ApiResult.Success(Unit, result.metadata)
            is ApiResult.Failure -> result
        }
    }

    override suspend fun login(
        profile: ServerProfile,
        email: String,
        password: String,
    ): ApiResult<Unit> = withClient(profile) { client ->
        val body = json.encodeToString(
            LoginRequestWire.serializer(),
            LoginRequestWire(email, password),
        )
        when (
            val result = client.execute(
                ApiRequest(
                    method = ApiMethod.Post,
                    apiPath = "/api/auth/login",
                    responseDeserializer = SessionWire.serializer(),
                    requestBody = body,
                ),
            )
        ) {
            is ApiResult.Success -> ApiResult.Success(Unit, result.metadata)
            is ApiResult.Failure -> result
        }
    }

    override suspend fun verifyCurrentSession(profile: ServerProfile): ApiResult<VerifiedSession> =
        withClient(profile) { client ->
            when (
                val me = client.execute(
                    ApiRequest(
                        method = ApiMethod.Get,
                        apiPath = "/api/auth/me",
                        responseDeserializer = SessionWire.serializer(),
                    ),
                )
            ) {
                is ApiResult.Failure -> me
                is ApiResult.Success -> {
                    val verified = if (me.metadata.firstHeader(SESSION_REFRESH_HEADER) == SESSION_REFRESH_REQUIRED) {
                        when (
                            val refresh = client.execute(
                                ApiRequest(
                                    method = ApiMethod.Post,
                                    apiPath = "/api/auth/session/refresh",
                                    responseDeserializer = SessionWire.serializer(),
                                    requestBody = "{}",
                                ),
                            )
                        ) {
                            is ApiResult.Success -> refresh.value
                            is ApiResult.Failure -> if (refresh.error.code == "SESSION_REFRESH_DEFERRED") {
                                me.value
                            } else {
                                return@withClient refresh
                            }
                        }
                    } else {
                        me.value
                    }
                    val (identity, authorization) = verified.toDomain(profile)
                        ?: return@withClient ApiResult.Failure(
                            AppError(AppErrorKind.ProtocolViolation, "UNSUPPORTED_LOCALE"),
                        )
                    ApiResult.Success(VerifiedSession(identity, authorization), me.metadata)
                }
            }
        }

    override suspend fun logout(profile: ServerProfile): ApiResult<Unit> = withClient(profile) { client ->
        when (
            val result = client.execute(
                ApiRequest(
                    method = ApiMethod.Post,
                    apiPath = "/api/auth/logout",
                    responseDeserializer = LoggedOutWire.serializer(),
                    requestBody = "{}",
                ),
            )
        ) {
            is ApiResult.Success -> ApiResult.Success(Unit, result.metadata)
            is ApiResult.Failure -> result
        }
    }

    private suspend fun <T> withClient(profile: ServerProfile, block: suspend (ApiClient) -> T): T {
        val client = clientProvider(profile)
        return try {
            block(client)
        } finally {
            client.close()
        }
    }

    private companion object {
        const val SESSION_REFRESH_HEADER = "X-Shuku-Session-Refresh"
        const val SESSION_REFRESH_REQUIRED = "required"
    }
}
