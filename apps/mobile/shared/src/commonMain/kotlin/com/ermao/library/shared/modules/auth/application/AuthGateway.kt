package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.auth.domain.Authorization
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class VerifiedSession(
    val identity: SessionIdentity,
    val authorization: Authorization,
)

interface AuthGateway {
    suspend fun setupStatus(profile: ServerProfile): ApiResult<Boolean>

    suspend fun setupInitialAdmin(
        profile: ServerProfile,
        name: String,
        email: String,
        password: String,
        locale: String,
    ): ApiResult<Unit>

    suspend fun login(profile: ServerProfile, email: String, password: String): ApiResult<Unit>

    suspend fun verifyCurrentSession(profile: ServerProfile): ApiResult<VerifiedSession>

    suspend fun logout(profile: ServerProfile): ApiResult<Unit>
}
