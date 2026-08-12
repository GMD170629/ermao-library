package com.ermao.library.features.me.application

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.me.model.AboutViewState
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.features.me.model.MeFailure
import com.ermao.library.features.me.model.MeField
import com.ermao.library.features.me.model.MeOperation
import com.ermao.library.features.me.model.MeRootViewState
import com.ermao.library.features.me.model.ProfileEditorState
import com.ermao.library.features.me.model.SanitizedAvatar
import com.ermao.library.features.me.model.SecurityEditorState
import com.ermao.library.shared.modules.personalsettings.PersonalAccount
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsError
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsErrorKind
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsResult
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsContent
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class MeViewModel(
    private val client: SettingsClient,
    private val sideEffects: SettingsSideEffects,
    serverName: String,
    serverBaseUrl: String,
    appVersion: String,
    initialAccount: MeAccountViewState,
    initialLocale: PersonalSettingsLocale,
) : ViewModel() {
    private val mutableRootState = MutableStateFlow(
        MeRootViewState(
            account = initialAccount,
            locale = initialLocale,
            serverName = serverName,
            serverBaseUrl = serverBaseUrl,
        ),
    )
    val rootState: StateFlow<MeRootViewState> = mutableRootState.asStateFlow()

    private val mutableProfileState = MutableStateFlow(
        ProfileEditorState(displayName = initialAccount.displayName),
    )
    val profileState: StateFlow<ProfileEditorState> = mutableProfileState.asStateFlow()

    private val mutableSecurityState = MutableStateFlow(SecurityEditorState(email = initialAccount.email))
    val securityState: StateFlow<SecurityEditorState> = mutableSecurityState.asStateFlow()

    private val mutableAboutState = MutableStateFlow(AboutViewState(appVersion = appVersion))
    val aboutState: StateFlow<AboutViewState> = mutableAboutState.asStateFlow()

    private var loadJob: Job? = null
    private var profileJob: Job? = null
    private var securityJob: Job? = null
    private var localeJob: Job? = null
    private var aboutJob: Job? = null

    init { load() }

    fun retryLoad() = load()
    fun updateDisplayName(value: String) = mutableProfileState.update { it.copy(displayName = value, failure = null) }
    fun updateEmail(value: String) = mutableSecurityState.update { it.copy(email = value, failure = null) }
    fun updateEmailCurrentPassword(value: String) =
        mutableSecurityState.update { it.copy(emailCurrentPassword = value, failure = null) }
    fun updateSecurityCurrentPassword(value: String) = mutableSecurityState.update { it.copy(currentPassword = value, failure = null) }
    fun updateNewPassword(value: String) = mutableSecurityState.update { it.copy(newPassword = value, failure = null) }
    fun updatePasswordConfirmation(value: String) = mutableSecurityState.update { it.copy(confirmPassword = value, failure = null) }

    fun stageAvatar(avatar: SanitizedAvatar) = mutableProfileState.update { it.copy(pendingAvatar = avatar, failure = null) }

    fun saveName() = runProfileOperation(MeOperation.SaveName) { state -> client.updateName(state.displayName.trim()) }

    fun saveEmail() {
        val state = mutableSecurityState.value
        if (state.isSaving) return
        mutableSecurityState.update { it.copy(isSaving = true, failure = null) }
        securityJob?.cancel()
        securityJob = viewModelScope.launch {
            try {
                when (val result = client.updateEmail(state.email.trim(), state.emailCurrentPassword)) {
                    is PersonalSettingsContent -> {
                        val account = result.value.toViewState()
                        mutableSecurityState.update {
                            it.copy(email = account.email, emailCurrentPassword = "", isSaving = false)
                        }
                        mutableRootState.update { it.copy(account = account, failure = null) }
                        sideEffects.refreshSession()
                    }
                    is PersonalSettingsFailure -> handleSecurityFailure(MeOperation.SaveEmail, result.error)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableSecurityState.update {
                    it.copy(isSaving = false, failure = MeFailure(MeOperation.SaveEmail, "SETTINGS_OPERATION_FAILED"))
                }
            }
        }
    }

    fun uploadAvatar() {
        val avatar = mutableProfileState.value.pendingAvatar ?: return
        runProfileOperation(MeOperation.UploadAvatar) { client.uploadAvatar(avatar) }
    }

    fun deleteAvatar() = runProfileOperation(MeOperation.DeleteAvatar) { client.deleteAvatar() }

    fun savePassword() {
        val state = mutableSecurityState.value
        if (state.newPassword != state.confirmPassword) {
            mutableSecurityState.update {
                it.copy(failure = MeFailure(MeOperation.SavePassword, "PASSWORD_MISMATCH", mapOf(MeField.ConfirmPassword to "MISMATCH")))
            }
            return
        }
        mutableSecurityState.update { it.copy(isSaving = true, failure = null) }
        securityJob?.cancel()
        securityJob = viewModelScope.launch {
            try {
                sideEffects.purgeCurrentNamespace()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableSecurityState.update { it.copy(isSaving = false, failure = MeFailure(MeOperation.SavePassword, "LOCAL_PURGE_FAILED")) }
                return@launch
            }
            try {
                when (val result = client.updatePassword(state.currentPassword, state.newPassword)) {
                    is PersonalSettingsContent -> sideEffects.logoutAfterPasswordChange()
                    is PersonalSettingsFailure -> handleSecurityFailure(MeOperation.SavePassword, result.error)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableSecurityState.update {
                    it.copy(isSaving = false, failure = MeFailure(MeOperation.SavePassword, "SETTINGS_OPERATION_FAILED"))
                }
            }
        }
    }

    fun logout() {
        securityJob?.cancel()
        securityJob = viewModelScope.launch {
            try {
                sideEffects.logout()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableSecurityState.update {
                    it.copy(isSaving = false, failure = MeFailure(MeOperation.SavePassword, "LOGOUT_FAILED"))
                }
            }
        }
    }

    fun selectLocale(locale: PersonalSettingsLocale, onApplied: (PersonalSettingsLocale) -> Unit) {
        if (locale == mutableRootState.value.locale) return
        localeJob?.cancel()
        localeJob = viewModelScope.launch {
            try {
                when (val result = client.updateLocale(locale)) {
                    is PersonalSettingsContent -> {
                        mutableRootState.update { it.copy(locale = result.value.locale, failure = null) }
                        onApplied(result.value.locale)
                        sideEffects.refreshSession()
                    }
                    is PersonalSettingsFailure -> handleRootFailure(MeOperation.SaveLocale, result.error)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableRootState.update { it.copy(failure = MeFailure(MeOperation.SaveLocale, "SETTINGS_OPERATION_FAILED")) }
            }
        }
    }

    fun loadAbout() {
        if (mutableAboutState.value.isLoading) return
        mutableAboutState.update { it.copy(isLoading = true, failure = null) }
        aboutJob?.cancel()
        aboutJob = viewModelScope.launch {
            try {
                when (val result = client.loadServerAbout()) {
                    is PersonalSettingsContent -> mutableAboutState.update {
                        it.copy(isLoading = false, serverVersion = result.value.serverVersion)
                    }
                    is PersonalSettingsFailure -> {
                        if (result.error.kind == PersonalSettingsErrorKind.Unauthorized) sideEffects.requireReauthentication()
                        mutableAboutState.update {
                            it.copy(isLoading = false, failure = failure(MeOperation.LoadAbout, result.error))
                        }
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableAboutState.update {
                    it.copy(isLoading = false, failure = MeFailure(MeOperation.LoadAbout, "SETTINGS_OPERATION_FAILED"))
                }
            }
        }
    }

    private fun load() {
        mutableRootState.update { it.copy(isLoading = true, failure = null) }
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            try {
                when (val result = client.load()) {
                    is PersonalSettingsContent -> {
                        val account = result.value.account.toViewState()
                        val avatarBytes = when (val avatar = client.loadAvatar()) {
                            is PersonalSettingsContent -> avatar.value.bytes.takeUnless { avatar.value.notModified }
                            is PersonalSettingsFailure -> {
                                if (avatar.error.kind == PersonalSettingsErrorKind.Unauthorized) {
                                    sideEffects.requireReauthentication()
                                }
                                null
                            }
                        }
                        mutableRootState.update {
                            it.copy(isLoading = false, account = account, locale = result.value.preferences.locale)
                                .copy(avatarBytes = avatarBytes)
                        }
                        mutableProfileState.update { it.copy(displayName = account.displayName) }
                        mutableSecurityState.update { it.copy(email = account.email) }
                    }
                    is PersonalSettingsFailure -> handleRootFailure(MeOperation.Load, result.error)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableRootState.update {
                    it.copy(isLoading = false, failure = MeFailure(MeOperation.Load, "SETTINGS_OPERATION_FAILED"))
                }
            }
        }
    }

    private fun runProfileOperation(
        operation: MeOperation,
        block: suspend (ProfileEditorState) -> PersonalSettingsResult<PersonalAccount>,
    ) {
        val state = mutableProfileState.value
        if (state.isSaving) return
        mutableProfileState.update { it.copy(isSaving = true, failure = null) }
        profileJob?.cancel()
        profileJob = viewModelScope.launch {
            try {
                when (val result = block(state)) {
                    is PersonalSettingsContent -> {
                        val account = result.value.toViewState()
                        mutableProfileState.update {
                            it.copy(
                                displayName = account.displayName,
                                pendingAvatar = null,
                                avatarRevision = it.avatarRevision + 1,
                                isSaving = false,
                            )
                        }
                        mutableSecurityState.update { it.copy(email = account.email) }
                        val avatarBytes = when (operation) {
                            MeOperation.UploadAvatar -> state.pendingAvatar?.bytes
                            MeOperation.DeleteAvatar -> null
                            else -> mutableRootState.value.avatarBytes
                        }
                        mutableRootState.update { it.copy(account = account, avatarBytes = avatarBytes, failure = null) }
                        sideEffects.refreshSession()
                    }
                    is PersonalSettingsFailure -> handleProfileFailure(operation, result.error)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                mutableProfileState.update {
                    it.copy(isSaving = false, failure = MeFailure(operation, "SETTINGS_OPERATION_FAILED"))
                }
            }
        }
    }

    private fun handleRootFailure(operation: MeOperation, error: PersonalSettingsError) {
        if (error.kind == PersonalSettingsErrorKind.Unauthorized) sideEffects.requireReauthentication()
        mutableRootState.update { it.copy(isLoading = false, failure = failure(operation, error)) }
    }

    private fun handleProfileFailure(operation: MeOperation, error: PersonalSettingsError) {
        if (error.kind == PersonalSettingsErrorKind.Unauthorized) sideEffects.requireReauthentication()
        mutableProfileState.update { it.copy(isSaving = false, failure = failure(operation, error)) }
    }

    private fun handleSecurityFailure(operation: MeOperation, error: PersonalSettingsError) {
        if (error.kind == PersonalSettingsErrorKind.Unauthorized) sideEffects.requireReauthentication()
        mutableSecurityState.update { it.copy(isSaving = false, failure = failure(operation, error)) }
    }

    companion object {
        fun factory(
            client: SettingsClient,
            sideEffects: SettingsSideEffects,
            serverName: String,
            serverBaseUrl: String,
            appVersion: String,
            initialAccount: MeAccountViewState,
            initialLocale: PersonalSettingsLocale,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer {
                MeViewModel(
                    client,
                    sideEffects,
                    serverName,
                    serverBaseUrl,
                    appVersion,
                    initialAccount,
                    initialLocale,
                )
            }
        }
    }
}

private fun PersonalAccount.toViewState() = MeAccountViewState(id, displayName, email, avatarUrl)

private fun failure(operation: MeOperation, error: PersonalSettingsError): MeFailure = MeFailure(
    operation = operation,
    code = error.code,
    fieldCodes = error.fieldViolations.mapNotNull { violation ->
        val field = when (violation.field) {
            "name", "displayName" -> MeField.DisplayName
            "email" -> MeField.Email
            "currentPassword" -> MeField.CurrentPassword
            "newPassword" -> MeField.NewPassword
            "avatar", "file" -> MeField.Avatar
            else -> null
        }
        field?.let { it to violation.code }
    }.toMap(),
)
