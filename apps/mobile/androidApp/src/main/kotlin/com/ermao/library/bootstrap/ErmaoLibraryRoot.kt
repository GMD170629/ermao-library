package com.ermao.library.bootstrap

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ermao.library.R
import com.ermao.library.features.auth.LoginScreen
import com.ermao.library.features.auth.LoginEntryAlert
import com.ermao.library.features.auth.ReauthenticateScreen
import com.ermao.library.features.auth.SetupScreen
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.features.servers.BlockingServerStateScreen
import com.ermao.library.features.shell.MainShell
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.features.me.platform.AppLocaleController
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository

@Composable
fun ErmaoLibraryRoot(
    state: MainUiState,
    actions: MainActions,
    modifier: Modifier = Modifier,
    contentRepository: ContentRepository,
    personalSettingsRepository: PersonalSettingsRepository? = null,
    administrativeSettingsRepository: AdministrativeSettingsRepository? = null,
    workManagementRepository: WorkManagementRepository? = null,
    downloadCatalog: AndroidDownloadCatalog? = null,
    downloadFiles: AtomicDownloadFileSink? = null,
    sharedDownloadCatalog: DownloadCatalogRepository? = null,
    localeController: AppLocaleController? = null,
) {
    val shellStateHolder = rememberSaveableStateHolder()
    val accountLocale = when (val session = state.session) {
        is AppSession.Authenticated -> PersonalSettingsLocale.fromWireValue(session.identity.locale.orEmpty())
        else -> null
    }
    LaunchedEffect(accountLocale) {
        if (accountLocale == null) {
            localeController?.restoreSystemLanguage()
        } else {
            localeController?.apply(accountLocale)
        }
    }

    if (state.showServerCenter) {
        LoginEntry(
            state = state,
            actions = actions,
            alert = null,
            modifier = modifier,
            canClose = state.session is AppSession.Authenticated,
        )
        return
    }

    val locale = LocalConfiguration.current.locales[0]?.language
        ?.let { if (it == "zh") "zh-CN" else "en-US" }
        ?: "en-US"

    when (val session = state.session) {
        AppSession.NoServer -> LoginEntry(state, actions, null, modifier)
        is AppSession.CheckingServer -> LoginEntry(state, actions, null, modifier)
        is AppSession.ServerConnectionFailed -> LoginEntry(
            state, actions,
            LoginEntryAlert.ServerUnavailable.takeIf { state.operationErrorCode != null },
            modifier,
        )
        is AppSession.TlsRisk -> LoginEntry(
            state, actions,
            LoginEntryAlert.UnsafeSsl.takeIf { state.operationErrorCode != null },
            modifier,
        )
        is AppSession.SetupRequired -> SetupScreen(
            profile = session.profile,
            form = state.setupForm,
            isSubmitting = false,
            operationErrorCode = state.operationErrorCode,
            onNameChanged = actions.onSetupNameChanged,
            onEmailChanged = actions.onSetupEmailChanged,
            onPasswordChanged = actions.onSetupPasswordChanged,
            onConfirmationChanged = actions.onSetupConfirmationChanged,
            onSubmit = { actions.onSetup(locale) },
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.SettingUp -> SetupScreen(
            profile = session.profile,
            form = state.setupForm,
            isSubmitting = true,
            operationErrorCode = null,
            onNameChanged = actions.onSetupNameChanged,
            onEmailChanged = actions.onSetupEmailChanged,
            onPasswordChanged = actions.onSetupPasswordChanged,
            onConfirmationChanged = actions.onSetupConfirmationChanged,
            onSubmit = {},
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.SetupFailed -> SetupScreen(
            profile = session.profile,
            form = state.setupForm,
            isSubmitting = false,
            operationErrorCode = state.operationErrorCode ?: session.failureCode,
            onNameChanged = actions.onSetupNameChanged,
            onEmailChanged = actions.onSetupEmailChanged,
            onPasswordChanged = actions.onSetupPasswordChanged,
            onConfirmationChanged = actions.onSetupConfirmationChanged,
            onSubmit = { actions.onSetup(locale) },
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.SignedOut -> LoginEntry(state, actions, null, modifier)
        is AppSession.Authenticating -> if (state.isReauthenticating) {
            ReauthenticateScreen(
                profile = session.profile,
                userDisplayName = state.reauthUserName,
                userEmail = state.reauthUserEmail,
                form = state.loginForm,
                isAuthenticating = true,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = {},
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
        } else {
            LoginEntry(state, actions, null, modifier)
        }
        is AppSession.LoginFailed -> if (state.isReauthenticating) {
            ReauthenticateScreen(
                profile = session.profile,
                userDisplayName = state.reauthUserName,
                userEmail = state.reauthUserEmail ?: session.email,
                form = state.loginForm.copy(invalidCredentials = session.failureCode == INVALID_CREDENTIALS),
                isAuthenticating = false,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = { actions.onLogin(state.reauthUserEmail ?: session.email) },
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
        } else {
            LoginEntry(
                state.copy(loginForm = state.loginForm.copy(invalidCredentials = session.failureCode == INVALID_CREDENTIALS)),
                actions,
                LoginEntryAlert.ServerUnavailable.takeIf {
                    state.operationErrorKind in setOf(
                        com.ermao.library.shared.core.network.AppErrorKind.NetworkUnavailable,
                        com.ermao.library.shared.core.network.AppErrorKind.Timeout,
                        com.ermao.library.shared.core.network.AppErrorKind.ServiceUnavailable,
                        com.ermao.library.shared.core.network.AppErrorKind.NotFoundOrUnavailable,
                        com.ermao.library.shared.core.network.AppErrorKind.ServerFailure,
                    )
                },
                modifier,
            )
        }
        is AppSession.AccountDisabled -> BlockingServerStateScreen(
            title = stringResource(R.string.account_disabled_title),
            message = stringResource(R.string.account_disabled_message, session.email, session.profile.displayName, session.profile.baseUrl.value),
            primaryLabel = stringResource(R.string.server_choose_other_action),
            onPrimary = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.Authenticated -> key(state.shellEpoch) {
            if (
                personalSettingsRepository != null &&
                administrativeSettingsRepository != null &&
                workManagementRepository != null &&
                localeController != null &&
                downloadCatalog != null &&
                downloadFiles != null &&
                sharedDownloadCatalog != null
            ) {
                val shellStateKey = listOf(
                    session.identity.namespace.serverIdentity,
                    session.identity.namespace.userId,
                    session.identity.namespace.authorizationVersion,
                    state.shellEpoch,
                ).joinToString("|")
                shellStateHolder.SaveableStateProvider(shellStateKey) {
                    MainShell(
                        session = session,
                        contentRepository = contentRepository,
                        personalSettingsRepository = personalSettingsRepository,
                        administrativeSettingsRepository = administrativeSettingsRepository,
                        workManagementRepository = workManagementRepository,
                        downloadCatalog = downloadCatalog,
                        downloadFiles = downloadFiles,
                        sharedDownloadCatalog = sharedDownloadCatalog,
                        localeController = localeController,
                        onSessionUnauthorized = actions.onRequireReauthentication,
                        onRefreshSession = actions.onRefreshSessionAwaiting,
                        onPurgeCurrentNamespace = actions.onPurgeCurrentNamespace,
                        onLogout = actions.onLogoutAwaiting,
                        modifier = modifier,
                    )
                }
            }
        }
        is AppSession.SessionExpired -> ReauthenticateScreen(
            profile = session.profile,
            userDisplayName = state.reauthUserName ?: session.lastKnownIdentity?.displayName,
            userEmail = state.reauthUserEmail ?: session.lastKnownIdentity?.email,
            form = state.loginForm,
            isAuthenticating = false,
            onPasswordChanged = actions.onLoginPasswordChanged,
            onLogin = { actions.onLogin(state.reauthUserEmail ?: session.lastKnownIdentity?.email) },
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.IncompatibleServer -> LoginEntry(
            state, actions,
            LoginEntryAlert.IncompatibleServer.takeIf {
                shouldShowIncompatibleServerAlert(state.operationErrorCode, session.reasonCode)
            },
            modifier,
        )
    }
}

private const val INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
private const val SERVER_IDENTITY_CHANGED = "SERVER_IDENTITY_CHANGED"

internal fun shouldShowIncompatibleServerAlert(
    operationErrorCode: String?,
    reasonCode: String,
): Boolean = operationErrorCode != null && reasonCode != SERVER_IDENTITY_CHANGED

data class MainActions(
    val onOpenServerCenter: () -> Unit,
    val onCloseServerCenter: () -> Unit,
    val onLoginEmailChanged: (String) -> Unit,
    val onLoginPasswordChanged: (String) -> Unit,
    val onLoginServerAddressChanged: (String) -> Unit,
    val onLogin: (String?) -> Unit,
    val onLoginEntry: () -> Unit,
    val onSelectLoginServer: (String) -> Unit,
    val onDeleteLoginServer: () -> Unit,
    val onAcceptLoginUnsafeTls: () -> Unit,
    val onDismissOperationError: () -> Unit,
    val onSetupNameChanged: (String) -> Unit,
    val onSetupEmailChanged: (String) -> Unit,
    val onSetupPasswordChanged: (String) -> Unit,
    val onSetupConfirmationChanged: (String) -> Unit,
    val onSetup: (String) -> Unit,
    val onRetrySession: () -> Unit,
    val onRequireReauthentication: () -> Unit,
    val onRefreshSessionAwaiting: suspend () -> Unit,
    val onPurgeCurrentNamespace: suspend () -> Unit,
    val onLogoutAwaiting: suspend (purgeNamespace: Boolean) -> Unit,
    val onLogout: () -> Unit,
)

@Composable
private fun LoginEntry(
    state: MainUiState,
    actions: MainActions,
    alert: LoginEntryAlert?,
    modifier: Modifier,
    canClose: Boolean = false,
) {
    LoginScreen(
        profiles = state.serverProfiles,
        currentProfileId = state.loginProfileId,
        savedAccountEmails = state.savedAccountEmails,
        form = state.loginForm,
        isAuthenticating = state.operationInProgress,
        alert = alert,
        unexpectedFailure = state.operationErrorCode == "RUNTIME_FAILURE",
        onServerAddressChanged = actions.onLoginServerAddressChanged,
        onEmailChanged = actions.onLoginEmailChanged,
        onPasswordChanged = actions.onLoginPasswordChanged,
        onLogin = actions.onLoginEntry,
        onSelectServer = actions.onSelectLoginServer,
        onDeleteCurrentServer = actions.onDeleteLoginServer,
        onDismissAlert = actions.onDismissOperationError,
        onRetry = actions.onLoginEntry,
        onAcceptUnsafeSsl = actions.onAcceptLoginUnsafeTls,
        canClose = canClose,
        onClose = actions.onCloseServerCenter,
        modifier = modifier,
    )
}
