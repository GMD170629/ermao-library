package com.ermao.library.shared.modules.servers.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.servers.application.ServerCompatibilityChecker
import com.ermao.library.shared.modules.servers.application.ServerProbe
import com.ermao.library.shared.modules.servers.application.ServerProbeResult
import com.ermao.library.shared.modules.servers.domain.ServerCompatibilityDecision
import com.ermao.library.shared.modules.servers.domain.ServerProfile

class KtorServerProbe(
    private val compatibilityChecker: ServerCompatibilityChecker = ServerCompatibilityChecker(
        clientProtocolVersion = 3,
        supportedServerProtocolVersions = setOf(3),
        supportedReaderSchemaVersions = setOf(4),
        supportedLibrarySchemaVersions = setOf(1),
    ),
    private val clientProvider: (ServerProfile) -> ApiClient,
) : ServerProbe {
    override suspend fun probe(profile: ServerProfile): ServerProbeResult {
        val client = clientProvider(profile)
        return try {
            when (val health = client.execute(healthRequest())) {
                is ApiResult.Failure -> ServerProbeResult.Failure(health.error)
                is ApiResult.Success -> {
                    if (health.metadata.statusCode !in SUCCESS_STATUS_CODES ||
                        health.value.service != EXPECTED_SERVICE ||
                        health.value.status != HEALTHY_STATUS
                    ) {
                        ServerProbeResult.Failure(
                            AppError(AppErrorKind.ServiceUnavailable, "SERVER_NOT_READY"),
                        )
                    } else {
                        checkCompatibility(client)
                    }
                }
            }
        } finally {
            client.close()
        }
    }

    private suspend fun checkCompatibility(client: ApiClient): ServerProbeResult =
        when (val compatibility = client.execute(compatibilityRequest())) {
            is ApiResult.Failure -> ServerProbeResult.Failure(compatibility.error)
            is ApiResult.Success -> if (compatibility.metadata.statusCode !in SUCCESS_STATUS_CODES) {
                ServerProbeResult.Failure(
                    AppError(AppErrorKind.ProtocolViolation, "COMPATIBILITY_STATUS_INVALID"),
                )
            } else {
                when (val decision = compatibilityChecker.check(compatibility.value.toDomain())) {
                    is ServerCompatibilityDecision.Compatible ->
                        ServerProbeResult.Compatible(decision.compatibility.serverIdentity)
                    is ServerCompatibilityDecision.Incompatible -> ServerProbeResult.Failure(
                        AppError(AppErrorKind.ProtocolViolation, decision.reasonCode),
                    )
                }
            }
        }

    private fun healthRequest() = ApiRequest(
        method = ApiMethod.Get,
        apiPath = "/api/health",
        responseDeserializer = ServiceHealthWire.serializer(),
    )

    private fun compatibilityRequest() = ApiRequest(
        method = ApiMethod.Get,
        apiPath = "/api/mobile/compatibility",
        responseDeserializer = ServerCompatibilityWire.serializer(),
    )

    private companion object {
        const val EXPECTED_SERVICE = "ermao-books"
        const val HEALTHY_STATUS = "ok"
        val SUCCESS_STATUS_CODES = 200..299
    }
}
