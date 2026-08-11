package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.modules.auth.MobileRuntimeBridge
import com.ermao.library.shared.modules.auth.Observation
import com.ermao.library.shared.modules.auth.OperationCompletion
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.OperationResultSnapshot
import com.ermao.library.shared.modules.auth.toSnapshot
import com.ermao.library.shared.modules.auth.SessionObserver
import com.ermao.library.shared.modules.auth.SessionSnapshotObserver
import com.ermao.library.shared.modules.auth.domain.AppSessionSnapshot
import com.ermao.library.shared.modules.auth.domain.toSnapshot
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class DefaultMobileRuntimeBridge(
    private val runtime: MobileRuntime,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main),
) : MobileRuntimeBridge {
    private val operationMutex = Mutex()
    override val currentSession: AppSessionSnapshot
        get() = runtime.currentSession.toSnapshot()

    override val serverProfiles: List<ServerProfileSnapshot>
        get() = runtime.serverProfiles

    override fun observeSession(observer: SessionSnapshotObserver): Observation =
        runtime.observeSession(SessionObserver { observer.onSessionChanged(it.toSnapshot()) })

    override fun start(completion: OperationCompletion) = launch(completion) { runtime.start() }

    override fun connectServer(
        displayName: String,
        baseUrl: String,
        completion: OperationCompletion,
    ) = launch(completion) {
        runtime.connectServer(ServerConnectionDraft(displayName, baseUrl))
    }

    override fun editServer(
        profileId: String,
        displayName: String,
        baseUrl: String,
        completion: OperationCompletion,
    ) = launch(completion) {
        val tlsMode = runtime.serverProfiles.firstOrNull { it.id == profileId }?.tlsMode
            ?: TlsMode.SystemTrust
        runtime.editServer(profileId, ServerConnectionDraft(displayName, baseUrl, tlsMode))
    }

    override fun switchServer(profileId: String, completion: OperationCompletion) =
        launch(completion) { runtime.switchServer(profileId) }

    override fun removeServer(profileId: String, completion: OperationCompletion) =
        launch(completion) { runtime.removeServer(profileId) }

    override fun restoreSystemTrust(profileId: String, completion: OperationCompletion) =
        launch(completion) { runtime.restoreSystemTrust(profileId) }

    override fun acceptInsecureTls(completion: OperationCompletion) =
        launch(completion) { runtime.acceptInsecureTls() }

    override fun retry(completion: OperationCompletion) = launch(completion) { runtime.retry() }

    override fun login(email: String, password: String, completion: OperationCompletion) =
        launch(completion) { runtime.login(email, password) }

    override fun setupInitialAdmin(
        name: String,
        email: String,
        password: String,
        locale: String,
        completion: OperationCompletion,
    ) = launch(completion) { runtime.setupInitialAdmin(name, email, password, locale) }

    override fun refreshCurrentSession(completion: OperationCompletion) =
        launch(completion) { runtime.refreshCurrentSession() }

    override fun enterOfflineMode(completion: OperationCompletion) =
        launch(completion) { runtime.enterOfflineMode() }

    override fun logout(completion: OperationCompletion) = launch(completion) { runtime.logout() }

    override fun close() {
        runtime.close()
        scope.cancel()
    }

    private fun launch(
        completion: OperationCompletion,
        operation: suspend () -> RuntimeOperationResult,
    ): Observation {
        val job = scope.launch {
            val snapshot = try {
                operationMutex.withLock { operation() }.toSnapshot()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                OperationResultSnapshot(
                    succeeded = false,
                    outcomeCode = "FAILURE",
                    errorKind = "ServerFailure",
                    errorCode = "RUNTIME_FAILURE",
                )
            }
            completion.complete(snapshot)
        }
        return Observation { job.cancel() }
    }
}
