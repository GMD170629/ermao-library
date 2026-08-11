package com.ermao.library.shared.modules.auth

import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.AppSessionSnapshot
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.core.network.AppError

fun interface SessionObserver {
    fun onSessionChanged(session: AppSession)
}

fun interface Observation {
    fun cancel()
}

interface MobileRuntime {
    val currentSession: AppSession

    val serverProfiles: List<ServerProfileSnapshot>

    fun observeSession(observer: SessionObserver): Observation

    suspend fun start(): RuntimeOperationResult

    suspend fun connectServer(command: ServerConnectionDraft): RuntimeOperationResult

    suspend fun editServer(profileId: String, command: ServerConnectionDraft): RuntimeOperationResult

    suspend fun switchServer(profileId: String): RuntimeOperationResult

    suspend fun removeServer(profileId: String): RuntimeOperationResult

    suspend fun restoreSystemTrust(profileId: String): RuntimeOperationResult

    suspend fun acceptInsecureTls(): RuntimeOperationResult

    suspend fun retry(): RuntimeOperationResult

    suspend fun login(email: String, password: String): RuntimeOperationResult

    suspend fun setupInitialAdmin(
        name: String,
        email: String,
        password: String,
        locale: String,
    ): RuntimeOperationResult

    suspend fun refreshCurrentSession(): RuntimeOperationResult

    suspend fun enterOfflineMode(): RuntimeOperationResult

    suspend fun logout(): RuntimeOperationResult

    fun close()
}

sealed interface RuntimeOperationResult {
    data class Success(
        val outcomeCode: String = "SUCCESS",
        val navigationDirective: NavigationDirective = NavigationDirective.KeepCurrentStacks,
    ) : RuntimeOperationResult

    data class Failure(val error: AppError) : RuntimeOperationResult
}

enum class NavigationDirective {
    KeepCurrentStacks,
    RestoreSelectedTab,
    ResetAllStacksHome,
    HidePrivateShell,
    EnterOfflineShell,
    ShowServerProfiles,
}

data class FieldViolationSnapshot(
    val field: String,
    val code: String,
)

data class OperationResultSnapshot(
    val succeeded: Boolean,
    val outcomeCode: String,
    val errorKind: String? = null,
    val errorCode: String? = null,
    val fieldViolations: List<FieldViolationSnapshot> = emptyList(),
    val parameters: Map<String, String> = emptyMap(),
    val navigationDirective: NavigationDirective = NavigationDirective.KeepCurrentStacks,
)

fun RuntimeOperationResult.toSnapshot(): OperationResultSnapshot = when (this) {
    is RuntimeOperationResult.Success -> OperationResultSnapshot(
        succeeded = true,
        outcomeCode = outcomeCode,
        navigationDirective = navigationDirective,
    )
    is RuntimeOperationResult.Failure -> OperationResultSnapshot(
        succeeded = false,
        outcomeCode = "FAILURE",
        errorKind = error.kind.name,
        errorCode = error.code,
        fieldViolations = error.fieldErrors.flatMap { (field, codes) ->
            codes.map { code -> FieldViolationSnapshot(field, code) }
        },
        parameters = error.parameters,
    )
}

/** Swift-facing observer contract. No Flow, suspend function, Ktor type, or Throwable crosses this seam. */
fun interface SessionSnapshotObserver {
    fun onSessionChanged(snapshot: AppSessionSnapshot)
}

fun interface OperationCompletion {
    fun complete(result: OperationResultSnapshot)
}

interface MobileRuntimeBridge {
    val currentSession: AppSessionSnapshot

    val serverProfiles: List<ServerProfileSnapshot>

    fun observeSession(observer: SessionSnapshotObserver): Observation

    fun start(completion: OperationCompletion): Observation

    fun connectServer(displayName: String, baseUrl: String, completion: OperationCompletion): Observation

    fun editServer(profileId: String, displayName: String, baseUrl: String, completion: OperationCompletion): Observation

    fun switchServer(profileId: String, completion: OperationCompletion): Observation

    fun removeServer(profileId: String, completion: OperationCompletion): Observation

    fun restoreSystemTrust(profileId: String, completion: OperationCompletion): Observation

    fun acceptInsecureTls(completion: OperationCompletion): Observation

    fun retry(completion: OperationCompletion): Observation

    fun login(email: String, password: String, completion: OperationCompletion): Observation

    fun setupInitialAdmin(
        name: String,
        email: String,
        password: String,
        locale: String,
        completion: OperationCompletion,
    ): Observation

    fun refreshCurrentSession(completion: OperationCompletion): Observation

    fun enterOfflineMode(completion: OperationCompletion): Observation

    fun logout(completion: OperationCompletion): Observation

    fun close()
}
