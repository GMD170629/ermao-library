package com.ermao.library.shared.modules.servers.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.modules.servers.domain.ServerProfile

fun interface ServerProbe {
    suspend fun probe(profile: ServerProfile): ServerProbeResult
}

sealed interface ServerProbeResult {
    data class Compatible(val serverIdentity: String) : ServerProbeResult

    data class Failure(val error: AppError) : ServerProbeResult
}
