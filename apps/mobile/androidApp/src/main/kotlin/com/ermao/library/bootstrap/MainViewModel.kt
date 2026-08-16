package com.ermao.library.bootstrap

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.lifecycle.viewModelScope
import com.ermao.library.platform.persistence.LoginCredentialStore
import com.ermao.library.platform.persistence.NoOpLoginCredentialStore
import com.ermao.library.platform.persistence.SavedLoginCredential
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
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import android.content.Context
import com.ermao.library.features.me.platform.AppLocaleController
import com.ermao.library.features.reader.infrastructure.AndroidPdfRangeCache
import com.ermao.library.platform.persistence.AndroidCoverCache
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.io.File

data class ServerFormState(
    val displayName: String = "",
    val rawBaseUrl: String = "",
    val displayNameError: ServerFormError? = null,
    val baseUrlError: ServerFormError? = null,
)

enum class ServerFormError { RequiredDisplayName, InvalidBaseUrl }

data class LoginFormState(
    val serverAddress: String = "",
    val email: String = "",
    val password: String = "",
    val serverAddressError: Boolean = false,
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
    val loginProfileId: String? = null,
    val savedAccountEmails: Map<String, String> = emptyMap(),
    val operationInProgress: Boolean = false,
    val operationErrorCode: String? = null,
    val operationErrorKind: AppErrorKind? = null,
    val isReauthenticating: Boolean = false,
    val reauthUserName: String? = null,
    val reauthUserEmail: String? = null,
    val shellEpoch: Int = 0,
)

class MainViewModel(
    private val runtime: MobileRuntime,
    private val credentialStore: LoginCredentialStore = NoOpLoginCredentialStore,
    private val appContext: Context? = null,
    private val localeController: AppLocaleController? = null,
    private val runtimeDispatcher: CoroutineDispatcher = Dispatchers.IO,
    initialLoginForm: LoginFormState = LoginFormState(),
) : ViewModel() {
    private var loadedCredentialProfileId: String? = null
    private var initialSessionRestoreJob: Job? = null
    private val mutableUiState = MutableStateFlow(
        MainUiState(
            session = runtime.currentSession,
            serverProfiles = runtime.serverProfiles,
            loginForm = initialLoginForm,
        ),
    )
    val uiState: StateFlow<MainUiState> = mutableUiState.asStateFlow()

    private val observation: Observation = runtime.observeSession(
        SessionObserver { session ->
            val sessionProfileId = session.profileIdOrNull()
            val profile = sessionProfileId?.let { id -> runtime.serverProfiles.firstOrNull { it.id == id } }
            val sessionProfileAddress = session.profileBaseUrlOrNull()
            mutableUiState.update { current ->
                current.copy(
                    session = session,
                    serverProfiles = runtime.serverProfiles,
                    serverForm = session.draftOrNull()?.toFormState() ?: current.serverForm,
                    loginForm = current.loginForm.copy(
                        serverAddress = sessionProfileAddress ?: current.loginForm.serverAddress,
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
                    } else if (session is AppSession.SessionExpired) {
                        true
                    } else {
                        current.isReauthenticating
                    },
                    reauthUserName = session.lastKnownName() ?: current.reauthUserName,
                    reauthUserEmail = session.lastKnownEmail() ?: current.reauthUserEmail,
                    operationErrorCode = null,
                    operationErrorKind = null,
                    loginProfileId = profile?.id ?: current.loginProfileId,
                    savedAccountEmails = current.savedAccountEmails,
                )
            }
            if (profile != null) loadCredential(profile.id)
            loadSavedAccountEmails(runtime.serverProfiles)
        },
    )

    init {
        runtime.serverProfiles.singleOrNull { it.isActive }?.let { activeProfile ->
            mutableUiState.update {
                it.copy(
                    loginProfileId = activeProfile.id,
                    loginForm = it.loginForm.copy(serverAddress = activeProfile.baseUrl),
                    savedAccountEmails = it.savedAccountEmails,
                )
            }
            loadCredential(activeProfile.id)
            loadSavedAccountEmails(runtime.serverProfiles)
        }
        initialSessionRestoreJob = viewModelScope.launch {
            try {
                withContext(runtimeDispatcher) { runtime.start() }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableUiState.update {
                    it.copy(
                        operationErrorCode = "RUNTIME_FAILURE",
                        operationErrorKind = AppErrorKind.ServerFailure,
                    )
                }
            }
        }
    }

    fun updateServerDisplayName(value: String) = mutableUiState.update {
        it.copy(serverForm = it.serverForm.copy(displayName = value, displayNameError = null))
    }

    fun updateServerBaseUrl(value: String) = mutableUiState.update {
        it.copy(serverForm = it.serverForm.copy(rawBaseUrl = value, baseUrlError = null))
    }

    fun openServerCenter() {
        val activeProfile = runtime.serverProfiles.singleOrNull { it.isActive }
        mutableUiState.update {
            it.copy(
                showServerCenter = true,
                showServerEditor = false,
                selectedProfileId = null,
                loginProfileId = activeProfile?.id ?: it.loginProfileId,
                loginForm = it.loginForm.copy(
                    serverAddress = activeProfile?.baseUrl ?: it.loginForm.serverAddress,
                    invalidCredentials = false,
                ),
                operationErrorCode = null,
                operationErrorKind = null,
            )
        }
        if (activeProfile != null) {
            loadedCredentialProfileId = null
            loadCredential(activeProfile.id)
        }
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
    fun requireReauthentication() {
        val session = runtime.currentSession as? AppSession.Authenticated
        if (session != null) {
            mutableUiState.update {
                it.copy(
                    isReauthenticating = true,
                    reauthUserName = session.identity.displayName,
                    reauthUserEmail = session.identity.email,
                )
            }
        }
        retrySession()
    }

    suspend fun refreshSessionAwaitingCompletion() {
        performRuntimeOperation { runtime.refreshCurrentSession() }
    }

    fun logout() {
        viewModelScope.launch {
            try {
                logoutAwaitingCompletion(purgeNamespace = true)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: SettingsLifecycleFailure) {
                // performRuntimeOperation already published the stable UI failure.
            }
        }
    }

    suspend fun purgeCurrentNamespace() {
        val session = runtime.currentSession as? AppSession.Authenticated
        if (session != null && appContext != null) {
            val context = ContentRequestContext(session.profile, session.identity.namespace)
            try {
                AndroidCoverCache.clearNamespace(appContext, context)
                AndroidPdfRangeCache(File(appContext.cacheDir, "reader/pdf-range-v1")).clearNamespace(
                    ReaderSyncNamespace(
                        session.identity.namespace.serverIdentity,
                        session.identity.namespace.userId,
                        session.identity.namespace.authorizationVersion,
                    ),
                )
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                throw CachePurgeFailure(error)
            }
        }
    }

    suspend fun logoutAwaitingCompletion(purgeNamespace: Boolean) {
        val result = performRuntimeOperation {
            if (purgeNamespace) purgeCurrentNamespace()
            runtime.logout()
        }
        if (runtime.currentSession !is AppSession.Authenticated) {
            localeController?.restoreSystemLanguage()
        }
        if (result !is RuntimeOperationResult.Success) throw SettingsLifecycleFailure()
    }

    fun onForegrounded() {
        if (mutableUiState.value.operationInProgress) return
        when (mutableUiState.value.session) {
            is AppSession.Authenticated ->
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

    fun updateLoginServerAddress(value: String) {
        val matchingProfileId = mutableUiState.value.serverProfiles
            .firstOrNull { profile -> profile.baseUrl == value.trim() }
            ?.id
        mutableUiState.update {
            it.copy(
                loginProfileId = matchingProfileId,
                loginForm = it.loginForm.copy(serverAddress = value, serverAddressError = false),
                operationErrorCode = null,
                operationErrorKind = null,
            )
        }
        if (matchingProfileId != null) loadCredential(matchingProfileId)
    }

    fun selectLoginServer(profileId: String) {
        val profile = mutableUiState.value.serverProfiles.firstOrNull { it.id == profileId } ?: return
        mutableUiState.update {
            it.copy(
                loginProfileId = profileId,
                loginForm = LoginFormState(serverAddress = profile.baseUrl),
                operationErrorCode = null,
                operationErrorKind = null,
            )
        }
        loadedCredentialProfileId = null
        loadCredential(profileId)
    }

    fun loginFromEntry() {
        val state = mutableUiState.value
        if (state.operationInProgress) return
        val form = state.loginForm
        val parsed = ServerBaseUrl.parse(form.serverAddress)
        val invalidAddress = parsed !is ServerBaseUrlParseResult.Valid
        val emailRequired = form.email.isBlank()
        val passwordRequired = form.password.isBlank()
        if (invalidAddress || emailRequired || passwordRequired) {
            mutableUiState.update {
                it.copy(
                    loginForm = it.loginForm.copy(
                        serverAddressError = invalidAddress,
                        emailRequired = emailRequired,
                        passwordRequired = passwordRequired,
                    ),
                )
            }
            return
        }

        launchEntryLogin(parsed.baseUrl.value, form.email.trim(), form.password, acceptUnsafeTls = false)
    }

    fun acceptUnsafeTlsAndLogin() {
        if (mutableUiState.value.operationInProgress) return
        val form = mutableUiState.value.loginForm
        val parsed = ServerBaseUrl.parse(form.serverAddress) as? ServerBaseUrlParseResult.Valid ?: return
        if (form.email.isBlank() || form.password.isBlank()) return
        launchEntryLogin(parsed.baseUrl.value, form.email.trim(), form.password, acceptUnsafeTls = true)
    }

    fun deleteDisplayedServer() {
        val profileId = mutableUiState.value.loginProfileId
        if (profileId == null) {
            clearLoginEntry()
            return
        }
        viewModelScope.launch {
            val result = performRuntimeOperation { runtime.removeServer(profileId) }
            if (result is RuntimeOperationResult.Success) {
                var credentialRemovalFailed = false
                try {
                    withContext(runtimeDispatcher) { credentialStore.remove(profileId) }
                } catch (_: Exception) {
                    credentialRemovalFailed = true
                }
                clearLoginEntry()
                if (credentialRemovalFailed) {
                    mutableUiState.update {
                        it.copy(
                            operationErrorCode = "CREDENTIAL_STORAGE_FAILED",
                            operationErrorKind = AppErrorKind.StorageFailure,
                        )
                    }
                }
            }
        }
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
                    it.copy(loginForm = it.loginForm.copy(invalidCredentials = true))
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
        val email = form.email.trim()
        val password = form.password
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
            if (result is RuntimeOperationResult.Success && runtime.currentSession is AppSession.Authenticated) {
                val profileId = runtime.serverProfiles.singleOrNull { it.isActive }?.id
                if (profileId != null) saveCredential(profileId, email, password)
            }
        }
    }

    fun dismissOperationError() = mutableUiState.update {
        it.copy(operationErrorCode = null, operationErrorKind = null)
    }

    private suspend fun submitEntryLogin(
        baseUrl: String,
        email: String,
        password: String,
        acceptUnsafeTls: Boolean,
    ) {
        val result = performRuntimeOperation {
            if (acceptUnsafeTls) {
                runtime.loginToServerAcceptingInsecureTls(baseUrl, email, password)
            } else {
                runtime.loginToServer(baseUrl, email, password)
            }
        }
        if (result is RuntimeOperationResult.Success && runtime.currentSession is AppSession.Authenticated) {
            val profileId = runtime.serverProfiles.singleOrNull { it.isActive }?.id
            if (profileId != null) {
                saveCredential(profileId, email, password)
            }
        } else if (result is RuntimeOperationResult.Failure && result.error.kind == AppErrorKind.Unauthorized) {
            mutableUiState.update {
                it.copy(loginForm = it.loginForm.copy(invalidCredentials = true))
            }
        }
    }

    private fun launchEntryLogin(
        baseUrl: String,
        email: String,
        password: String,
        acceptUnsafeTls: Boolean,
    ) {
        mutableUiState.update {
            it.copy(operationInProgress = true, operationErrorCode = null, operationErrorKind = null)
        }
        viewModelScope.launch {
            cancelInitialSessionRestore()
            submitEntryLogin(baseUrl, email, password, acceptUnsafeTls)
        }
    }

    private suspend fun cancelInitialSessionRestore() {
        val restoreJob = initialSessionRestoreJob ?: return
        initialSessionRestoreJob = null
        restoreJob.cancelAndJoin()
    }

    private suspend fun saveCredential(profileId: String, email: String, password: String) {
        try {
            withContext(runtimeDispatcher) {
                credentialStore.save(profileId, SavedLoginCredential(email, password))
            }
            loadedCredentialProfileId = null
            mutableUiState.update {
                it.copy(savedAccountEmails = it.savedAccountEmails + (profileId to email))
            }
        } catch (_: Exception) {
            mutableUiState.update {
                it.copy(
                    operationErrorCode = "CREDENTIAL_STORAGE_FAILED",
                    operationErrorKind = AppErrorKind.StorageFailure,
                )
            }
        }
    }

    private fun loadCredential(profileId: String) {
        if (loadedCredentialProfileId == profileId) return
        loadedCredentialProfileId = profileId
        viewModelScope.launch {
            val credential = withContext(runtimeDispatcher) { credentialStore.load(profileId) } ?: return@launch
            mutableUiState.update { state ->
                if (state.loginProfileId != profileId) state else state.copy(
                    loginForm = state.loginForm.copy(email = credential.email, password = credential.password),
                    savedAccountEmails = state.savedAccountEmails + (profileId to credential.email),
                )
            }
        }
    }

    private fun loadSavedAccountEmails(profiles: List<ServerProfileSnapshot>) {
        viewModelScope.launch {
            val accounts = withContext(runtimeDispatcher) {
                profiles.mapNotNull { profile ->
                    runCatching { credentialStore.load(profile.id) }
                        .getOrNull()
                        ?.email
                        ?.let { profile.id to it }
                }.toMap()
            }
            mutableUiState.update { it.copy(savedAccountEmails = accounts) }
        }
    }

    private fun clearLoginEntry() {
        loadedCredentialProfileId = null
        mutableUiState.update {
            it.copy(
                showServerCenter = false,
                loginProfileId = null,
                loginForm = LoginFormState(),
                operationErrorCode = null,
                operationErrorKind = null,
            )
        }
    }

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
            withContext(runtimeDispatcher) { operation() }.also { result ->
                mutableUiState.update { current ->
                    val directive = (result as? RuntimeOperationResult.Success)?.navigationDirective
                    current.copy(
                        serverProfiles = runtime.serverProfiles,
                        operationInProgress = false,
                        operationErrorCode = (result as? RuntimeOperationResult.Failure)?.error?.code,
                        operationErrorKind = (result as? RuntimeOperationResult.Failure)?.error?.kind,
                        showServerCenter = when (directive) {
                            NavigationDirective.ResetAllStacksHome -> false
                            NavigationDirective.ShowServerProfiles ->
                                current.showServerCenter && runtime.serverProfiles.isNotEmpty()
                            NavigationDirective.KeepCurrentStacks,
                            NavigationDirective.RestoreSelectedTab,
                            NavigationDirective.RevalidatePrivateShell,
                            NavigationDirective.HidePrivateShell,
                            null,
                            -> current.showServerCenter
                        },
                        selectedProfileId = if (directive == NavigationDirective.ResetAllStacksHome) null else current.selectedProfileId,
                        shellEpoch = if (directive == NavigationDirective.ResetAllStacksHome) current.shellEpoch + 1 else current.shellEpoch,
                    )
                }
            }
        } catch (cancelled: CancellationException) {
            mutableUiState.update { it.copy(operationInProgress = false) }
            throw cancelled
        } catch (_: CachePurgeFailure) {
            mutableUiState.update {
                it.copy(
                    operationInProgress = false,
                    operationErrorCode = "CACHE_PURGE_FAILED",
                    operationErrorKind = AppErrorKind.StorageFailure,
                )
            }
            null
        } catch (_: Exception) {
            mutableUiState.update {
                it.copy(
                    operationInProgress = false,
                    operationErrorCode = "RUNTIME_FAILURE",
                    operationErrorKind = AppErrorKind.ServerFailure,
                )
            }
            null
        }
    }

    override fun onCleared() {
        observation.cancel()
        super.onCleared()
    }

    companion object {
        fun factory(
            runtime: MobileRuntime,
            credentialStore: LoginCredentialStore = NoOpLoginCredentialStore,
            appContext: Context? = null,
            localeController: AppLocaleController? = null,
            initialLoginForm: LoginFormState = LoginFormState(),
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                MainViewModel(
                    runtime = runtime,
                    credentialStore = credentialStore,
                    appContext = appContext,
                    localeController = localeController,
                    initialLoginForm = initialLoginForm,
                )
            }
        }
    }
}

private class CachePurgeFailure(cause: Throwable) : Exception(cause)
private class SettingsLifecycleFailure : Exception()

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
    is AppSession.SessionExpired -> lastKnownIdentity?.email
    is AppSession.LoginFailed -> email
    is AppSession.AccountDisabled -> email
    else -> null
}

private fun AppSession.profileIdOrNull(): String? = when (this) {
    is AppSession.SetupRequired -> profile.id
    is AppSession.SettingUp -> profile.id
    is AppSession.SetupFailed -> profile.id
    is AppSession.SignedOut -> profile.id
    is AppSession.Authenticating -> profile.id
    is AppSession.LoginFailed -> profile.id
    is AppSession.AccountDisabled -> profile.id
    is AppSession.Authenticated -> profile.id
    is AppSession.SessionExpired -> profile.id
    else -> null
}

private fun AppSession.profileBaseUrlOrNull(): String? = when (this) {
    is AppSession.SetupRequired -> profile.baseUrl.value
    is AppSession.SettingUp -> profile.baseUrl.value
    is AppSession.SetupFailed -> profile.baseUrl.value
    is AppSession.SignedOut -> profile.baseUrl.value
    is AppSession.Authenticating -> profile.baseUrl.value
    is AppSession.LoginFailed -> profile.baseUrl.value
    is AppSession.AccountDisabled -> profile.baseUrl.value
    is AppSession.Authenticated -> profile.baseUrl.value
    is AppSession.SessionExpired -> profile.baseUrl.value
    is AppSession.CheckingServer -> draft.rawBaseUrl
    is AppSession.ServerConnectionFailed -> draft.rawBaseUrl
    is AppSession.TlsRisk -> draft.rawBaseUrl
    is AppSession.IncompatibleServer -> draft.rawBaseUrl
    AppSession.NoServer -> null
}

private fun AppSession.lastKnownName(): String? = when (this) {
    is AppSession.Authenticated -> identity.displayName
    is AppSession.SessionExpired -> lastKnownIdentity?.displayName
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
