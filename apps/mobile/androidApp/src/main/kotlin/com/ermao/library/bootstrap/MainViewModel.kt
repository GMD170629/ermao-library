package com.ermao.library.bootstrap

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.lifecycle.viewModelScope
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.modules.auth.NavigationDirective
import com.ermao.library.shared.modules.auth.Observation
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.SessionObserver
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ServerFormState(
    val displayName: String = "",
    val rawBaseUrl: String = "",
    val displayNameError: ServerFormError? = null,
    val baseUrlError: ServerFormError? = null,
)

enum class ServerFormError { RequiredDisplayName, InvalidBaseUrl }

data class LoginFormState(
    val email: String = "",
    val password: String = "",
    val emailRequired: Boolean = false,
    val passwordRequired: Boolean = false,
    val invalidCredentials: Boolean = false,
)

data class SetupFormState(
    val name: String = "",
    val email: String = "",
    val password: String = "",
    val passwordConfirmation: String = "",
    val nameError: SetupFieldError? = null,
    val emailError: SetupFieldError? = null,
    val passwordError: SetupFieldError? = null,
    val confirmationError: SetupFieldError? = null,
)

enum class SetupFieldError { Required, InvalidEmail, PasswordTooShort, PasswordMismatch, Rejected }

enum class ServerEditorMode { Add, Edit }

data class MainUiState(
    val session: AppSession,
    val serverProfiles: List<ServerProfileSnapshot> = emptyList(),
    val serverForm: ServerFormState = ServerFormState(),
    val loginForm: LoginFormState = LoginFormState(),
    val setupForm: SetupFormState = SetupFormState(),
    val showServerCenter: Boolean = false,
    val showServerEditor: Boolean = false,
    val serverEditorMode: ServerEditorMode = ServerEditorMode.Add,
    val editingProfileId: String? = null,
    val selectedProfileId: String? = null,
    val operationInProgress: Boolean = false,
    val operationErrorCode: String? = null,
    val isReauthenticating: Boolean = false,
    val reauthUserName: String? = null,
    val reauthUserEmail: String? = null,
    val reauthEntitlementExpiresAt: Long? = null,
    val reauthServerUnavailable: Boolean = false,
    val shellEpoch: Int = 0,
)

class MainViewModel(private val runtime: MobileRuntime) : ViewModel() {
    private val mutableUiState = MutableStateFlow(
        MainUiState(session = runtime.currentSession, serverProfiles = runtime.serverProfiles),
    )
    val uiState: StateFlow<MainUiState> = mutableUiState.asStateFlow()

    private val observation: Observation = runtime.observeSession(
        SessionObserver { session ->
            mutableUiState.update { current ->
                current.copy(
                    session = session,
                    serverProfiles = runtime.serverProfiles,
                    serverForm = session.draftOrNull()?.toFormState() ?: current.serverForm,
                    loginForm = current.loginForm.copy(
                        email = session.lastKnownEmail() ?: current.loginForm.email,
                        password = if (session is AppSession.Authenticated) "" else current.loginForm.password,
                        invalidCredentials = false,
                    ),
                    setupForm = if (session.keepsSetupSecrets()) {
                        current.setupForm
                    } else {
                        current.setupForm.copy(password = "", passwordConfirmation = "")
                    },
                    isReauthenticating = if (session is AppSession.Authenticated || session is AppSession.SignedOut) {
                        false
                    } else {
                        current.isReauthenticating
                    },
                    reauthUserName = session.lastKnownName() ?: current.reauthUserName,
                    reauthUserEmail = session.lastKnownEmail() ?: current.reauthUserEmail,
                    reauthEntitlementExpiresAt = session.entitlementExpiry() ?: current.reauthEntitlementExpiresAt,
                    reauthServerUnavailable = when (session) {
                        is AppSession.SessionUnavailable -> true
                        is AppSession.Authenticated, is AppSession.SignedOut -> false
                        else -> current.reauthServerUnavailable
                    },
                    operationErrorCode = null,
                )
            }
        },
    )

    init { viewModelScope.launch { performRuntimeOperation { runtime.start() } } }

    fun updateServerDisplayName(value: String) = mutableUiState.update {
        it.copy(serverForm = it.serverForm.copy(displayName = value, displayNameError = null))
    }

    fun updateServerBaseUrl(value: String) = mutableUiState.update {
        it.copy(serverForm = it.serverForm.copy(rawBaseUrl = value, baseUrlError = null))
    }

    fun openServerCenter() = mutableUiState.update {
        it.copy(showServerCenter = true, showServerEditor = false, selectedProfileId = null, operationErrorCode = null)
    }

    fun closeServerCenter() = mutableUiState.update {
        it.copy(showServerCenter = false, showServerEditor = false, selectedProfileId = null, operationErrorCode = null)
    }

    fun selectServerProfile(profileId: String) = mutableUiState.update {
        it.copy(selectedProfileId = profileId, operationErrorCode = null)
    }

    fun closeServerDetail() = mutableUiState.update { it.copy(selectedProfileId = null, operationErrorCode = null) }

    fun openAddServer() = mutableUiState.update {
        it.copy(
            showServerCenter = it.showServerCenter || it.serverProfiles.isNotEmpty(),
            showServerEditor = true,
            serverEditorMode = ServerEditorMode.Add,
            editingProfileId = null,
            serverForm = ServerFormState(),
            operationErrorCode = null,
        )
    }

    fun openEditServer(profileId: String) {
        val profile = mutableUiState.value.serverProfiles.firstOrNull { it.id == profileId } ?: return
        mutableUiState.update {
            it.copy(
                showServerEditor = true,
                serverEditorMode = ServerEditorMode.Edit,
                editingProfileId = profileId,
                serverForm = ServerFormState(profile.displayName, profile.baseUrl),
                operationErrorCode = null,
            )
        }
    }

    fun closeServerEditor() = mutableUiState.update {
        it.copy(showServerEditor = false, editingProfileId = null, operationErrorCode = null)
    }

    fun reopenConnectionDraft() = mutableUiState.update {
        it.copy(showServerEditor = true, serverEditorMode = ServerEditorMode.Add, operationErrorCode = null)
    }

    fun saveServer() {
        val state = mutableUiState.value
        val draft = validatedServerDraft(state.serverForm) ?: return
        viewModelScope.launch {
            val result = performRuntimeOperation {
                if (state.serverEditorMode == ServerEditorMode.Edit) {
                    runtime.editServer(requireNotNull(state.editingProfileId), draft)
                } else {
                    runtime.connectServer(draft)
                }
            }
            if (result is RuntimeOperationResult.Success) {
                mutableUiState.update {
                    val returnToDetail = state.serverEditorMode == ServerEditorMode.Edit &&
                        runtime.currentSession is AppSession.Authenticated
                    it.copy(
                        showServerEditor = false,
                        showServerCenter = returnToDetail,
                        selectedProfileId = state.editingProfileId.takeIf { returnToDetail },
                    )
                }
            }
        }
    }

    fun retryServerConnection() = launchOperation { runtime.retry() }
    fun permanentlyIgnoreTlsAndConnect() = launchOperation { runtime.acceptInsecureTls() }
    fun switchServer(profileId: String) = launchOperation { runtime.switchServer(profileId) }
    fun removeServer(profileId: String) = launchOperation { runtime.removeServer(profileId) }
    fun restoreSystemTrust(profileId: String) = launchOperation { runtime.restoreSystemTrust(profileId) }
    fun retrySession() = launchOperation { runtime.refreshCurrentSession() }
    fun enterOfflineMode() = launchOperation { runtime.enterOfflineMode() }
    fun logout() = launchOperation { runtime.logout() }

    fun onForegrounded() {
        if (mutableUiState.value.operationInProgress) return
        when (mutableUiState.value.session) {
            is AppSession.Authenticated, is AppSession.OfflineGrace ->
                launchOperation { runtime.refreshCurrentSession() }
            else -> Unit
        }
    }

    fun updateLoginEmail(value: String) = mutableUiState.update {
        it.copy(loginForm = it.loginForm.copy(email = value, emailRequired = false, invalidCredentials = false))
    }

    fun updateLoginPassword(value: String) = mutableUiState.update {
        it.copy(loginForm = it.loginForm.copy(password = value, passwordRequired = false, invalidCredentials = false))
    }

    fun login(fixedEmail: String? = null) {
        val form = mutableUiState.value.loginForm
        val email = fixedEmail ?: form.email
        val emailRequired = email.isBlank()
        val passwordRequired = form.password.isBlank()
        if (emailRequired || passwordRequired) {
            mutableUiState.update {
                it.copy(loginForm = it.loginForm.copy(emailRequired = emailRequired, passwordRequired = passwordRequired))
            }
            return
        }
        if (fixedEmail != null) {
            mutableUiState.update { it.copy(isReauthenticating = true, reauthUserEmail = fixedEmail) }
        }
        viewModelScope.launch {
            val result = performRuntimeOperation { runtime.login(email.trim(), form.password) }
            if (result is RuntimeOperationResult.Failure && result.error.kind == AppErrorKind.Unauthorized) {
                mutableUiState.update {
                    it.copy(loginForm = it.loginForm.copy(invalidCredentials = true, password = ""))
                }
            }
            if (fixedEmail != null && result is RuntimeOperationResult.Failure) {
                mutableUiState.update {
                    it.copy(
                        reauthServerUnavailable = result.error.kind in setOf(
                            AppErrorKind.NetworkUnavailable,
                            AppErrorKind.Timeout,
                            AppErrorKind.ServiceUnavailable,
                        ),
                    )
                }
            }
        }
    }

    fun updateSetupName(value: String) = mutableUiState.update {
        it.copy(setupForm = it.setupForm.copy(name = value, nameError = null))
    }
    fun updateSetupEmail(value: String) = mutableUiState.update {
        it.copy(setupForm = it.setupForm.copy(email = value, emailError = null))
    }
    fun updateSetupPassword(value: String) = mutableUiState.update {
        it.copy(setupForm = it.setupForm.copy(password = value, passwordError = null, confirmationError = null))
    }
    fun updateSetupConfirmation(value: String) = mutableUiState.update {
        it.copy(setupForm = it.setupForm.copy(passwordConfirmation = value, confirmationError = null))
    }

    fun setupInitialAdmin(locale: String) {
        val form = mutableUiState.value.setupForm
        val validated = form.validated()
        if (validated != form) {
            mutableUiState.update { it.copy(setupForm = validated) }
            return
        }
        viewModelScope.launch {
            val result = performRuntimeOperation {
                runtime.setupInitialAdmin(form.name, form.email, form.password, locale)
            }
            if (result is RuntimeOperationResult.Failure && result.error.kind == AppErrorKind.Validation) {
                applySetupFieldErrors(result.error)
            }
            if (result is RuntimeOperationResult.Success && result.outcomeCode == "SETUP_ALREADY_COMPLETED") {
                mutableUiState.update { it.copy(setupForm = SetupFormState()) }
            }
        }
    }

    fun dismissOperationError() = mutableUiState.update { it.copy(operationErrorCode = null) }

    private fun validatedServerDraft(form: ServerFormState): ServerConnectionDraft? {
        val nameError = ServerFormError.RequiredDisplayName.takeIf { form.displayName.isBlank() }
        val urlError = ServerFormError.InvalidBaseUrl.takeIf {
            ServerBaseUrl.parse(form.rawBaseUrl) !is ServerBaseUrlParseResult.Valid
        }
        if (nameError != null || urlError != null) {
            mutableUiState.update {
                it.copy(serverForm = it.serverForm.copy(displayNameError = nameError, baseUrlError = urlError))
            }
            return null
        }
        val tlsMode = mutableUiState.value.editingProfileId
            ?.let { id -> mutableUiState.value.serverProfiles.firstOrNull { it.id == id }?.tlsMode }
            ?: TlsMode.SystemTrust
        return ServerConnectionDraft(form.displayName.trim(), form.rawBaseUrl.trim(), tlsMode)
    }

    private fun SetupFormState.validated(): SetupFormState {
        val normalizedEmail = email.trim()
        return copy(
            nameError = SetupFieldError.Required.takeIf { name.isBlank() },
            emailError = when {
                normalizedEmail.isBlank() -> SetupFieldError.Required
                !normalizedEmail.looksLikeEmail() -> SetupFieldError.InvalidEmail
                else -> null
            },
            passwordError = when {
                password.isBlank() -> SetupFieldError.Required
                password.length < 10 -> SetupFieldError.PasswordTooShort
                else -> null
            },
            confirmationError = when {
                passwordConfirmation.isBlank() -> SetupFieldError.Required
                passwordConfirmation != password -> SetupFieldError.PasswordMismatch
                else -> null
            },
        )
    }

    private fun applySetupFieldErrors(error: AppError) {
        val fields = error.fieldErrors.keys
        mutableUiState.update {
            it.copy(
                setupForm = it.setupForm.copy(
                    nameError = SetupFieldError.Rejected.takeIf { "name" in fields },
                    emailError = SetupFieldError.Rejected.takeIf { "email" in fields },
                    passwordError = SetupFieldError.Rejected.takeIf { "password" in fields },
                ),
            )
        }
    }

    private fun launchOperation(operation: suspend () -> RuntimeOperationResult) {
        viewModelScope.launch { performRuntimeOperation(operation) }
    }

    private suspend fun performRuntimeOperation(
        operation: suspend () -> RuntimeOperationResult,
    ): RuntimeOperationResult? {
        mutableUiState.update { it.copy(operationInProgress = true, operationErrorCode = null) }
        return try {
            operation().also { result ->
                mutableUiState.update { current ->
                    val directive = (result as? RuntimeOperationResult.Success)?.navigationDirective
                    current.copy(
                        serverProfiles = runtime.serverProfiles,
                        operationInProgress = false,
                        operationErrorCode = (result as? RuntimeOperationResult.Failure)?.error?.code,
                        showServerCenter = when (directive) {
                            NavigationDirective.ResetAllStacksHome -> false
                            NavigationDirective.ShowServerProfiles -> runtime.serverProfiles.isNotEmpty()
                            else -> current.showServerCenter
                        },
                        selectedProfileId = if (directive == NavigationDirective.ResetAllStacksHome) null else current.selectedProfileId,
                        shellEpoch = if (directive == NavigationDirective.ResetAllStacksHome) current.shellEpoch + 1 else current.shellEpoch,
                    )
                }
            }
        } catch (cancelled: CancellationException) {
            mutableUiState.update { it.copy(operationInProgress = false) }
            throw cancelled
        } catch (_: Exception) {
            mutableUiState.update { it.copy(operationInProgress = false, operationErrorCode = "RUNTIME_FAILURE") }
            null
        }
    }

    override fun onCleared() {
        observation.cancel()
        super.onCleared()
    }

    companion object {
        fun factory(runtime: MobileRuntime): ViewModelProvider.Factory = viewModelFactory {
            initializer { MainViewModel(runtime) }
        }
    }
}

private fun String.looksLikeEmail(): Boolean {
    val at = indexOf('@')
    return at > 0 && at < lastIndex && indexOf('.', startIndex = at + 2) in (at + 2)..<length
}

private fun AppSession.keepsSetupSecrets(): Boolean = when (this) {
    is AppSession.SetupRequired,
    is AppSession.SettingUp,
    is AppSession.SetupFailed,
    -> true
    else -> false
}

private fun AppSession.lastKnownEmail(): String? = when (this) {
    is AppSession.Authenticated -> identity.email
    is AppSession.SessionUnavailable -> lastKnownIdentity?.email
    is AppSession.SessionExpired -> lastKnownIdentity?.email
    is AppSession.OfflineGrace -> identity.email
    is AppSession.LoginFailed -> email
    is AppSession.AccountDisabled -> email
    else -> null
}

private fun AppSession.lastKnownName(): String? = when (this) {
    is AppSession.Authenticated -> identity.displayName
    is AppSession.SessionUnavailable -> lastKnownIdentity?.displayName
    is AppSession.SessionExpired -> lastKnownIdentity?.displayName
    is AppSession.OfflineGrace -> identity.displayName
    else -> null
}

private fun AppSession.entitlementExpiry(): Long? = when (this) {
    is AppSession.SessionUnavailable -> entitlementExpiresAtEpochMillis
    is AppSession.SessionExpired -> entitlementExpiresAtEpochMillis
    is AppSession.OfflineGrace -> entitlementExpiresAtEpochMillis
    else -> null
}

private fun AppSession.draftOrNull(): ServerConnectionDraft? = when (this) {
    is AppSession.CheckingServer -> draft
    is AppSession.ServerConnectionFailed -> draft
    is AppSession.TlsRisk -> draft
    is AppSession.IncompatibleServer -> draft
    else -> null
}

private fun ServerConnectionDraft.toFormState() = ServerFormState(displayName, rawBaseUrl)
