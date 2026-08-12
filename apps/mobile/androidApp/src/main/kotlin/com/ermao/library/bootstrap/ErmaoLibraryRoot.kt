package com.ermao.library.bootstrap

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import com.ermao.library.R
import com.ermao.library.features.auth.LoginScreen
import com.ermao.library.features.auth.LoginEntryAlert
import com.ermao.library.features.auth.OfflineEmptyShell
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
import kotlin.math.ceil

@Composable
fun ErmaoLibraryRoot(
    state: MainUiState,
    actions: MainActions,
    modifier: Modifier = Modifier,
    contentRepository: ContentRepository,
    personalSettingsRepository: PersonalSettingsRepository? = null,
    administrativeSettingsRepository: AdministrativeSettingsRepository? = null,
    localeController: AppLocaleController? = null,
) {
    val shellStateHolder = rememberSaveableStateHolder()
    val accountLocale = when (val session = state.session) {
        is AppSession.Authenticated -> PersonalSettingsLocale.fromWireValue(session.identity.locale.orEmpty())
        is AppSession.OfflineGrace -> PersonalSettingsLocale.fromWireValue(session.identity.locale.orEmpty())
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
            canClose = state.session is AppSession.Authenticated || state.session is AppSession.OfflineGrace,
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
                entitlementExpiresAtEpochMillis = state.reauthEntitlementExpiresAt,
                form = state.loginForm,
                isAuthenticating = true,
                serverUnavailable = state.reauthServerUnavailable,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = {},
                onEnterOffline = actions.onEnterOffline,
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
                entitlementExpiresAtEpochMillis = state.reauthEntitlementExpiresAt,
                form = state.loginForm.copy(invalidCredentials = session.failureCode == INVALID_CREDENTIALS),
                isAuthenticating = false,
                serverUnavailable = state.reauthServerUnavailable,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = { actions.onLogin(state.reauthUserEmail ?: session.email) },
                onEnterOffline = actions.onEnterOffline,
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
                localeController != null
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
        is AppSession.SessionUnavailable -> ReauthenticateScreen(
            profile = session.profile,
            userDisplayName = state.reauthUserName ?: session.lastKnownIdentity?.displayName,
            userEmail = state.reauthUserEmail ?: session.lastKnownIdentity?.email,
            entitlementExpiresAtEpochMillis = state.reauthEntitlementExpiresAt
                ?: session.entitlementExpiresAtEpochMillis,
            form = state.loginForm,
            isAuthenticating = false,
            serverUnavailable = true,
            onPasswordChanged = actions.onLoginPasswordChanged,
            onLogin = { actions.onLogin(state.reauthUserEmail ?: session.lastKnownIdentity?.email) },
            onEnterOffline = actions.onEnterOffline,
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.SessionExpired -> ReauthenticateScreen(
            profile = session.profile,
            userDisplayName = state.reauthUserName ?: session.lastKnownIdentity?.displayName,
            userEmail = state.reauthUserEmail ?: session.lastKnownIdentity?.email,
            entitlementExpiresAtEpochMillis = state.reauthEntitlementExpiresAt
                ?: session.entitlementExpiresAtEpochMillis,
            form = state.loginForm,
            isAuthenticating = false,
            serverUnavailable = false,
            onPasswordChanged = actions.onLoginPasswordChanged,
            onLogin = { actions.onLogin(state.reauthUserEmail ?: session.lastKnownIdentity?.email) },
            onEnterOffline = actions.onEnterOffline,
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.OfflineGrace -> OfflineEmptyShell(
            profile = session.profile,
            userEmail = session.identity.email,
            onRetryAuthentication = actions.onRetrySession,
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.IncompatibleServer -> LoginEntry(
            state, actions,
            LoginEntryAlert.IncompatibleServer.takeIf { state.operationErrorCode != null },
            modifier,
        )
    }
}

private const val INVALID_CREDENTIALS = "INVALID_CREDENTIALS"

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
    val onEnterOffline: () -> Unit,
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
        isAuthenticating = state.operationInProgress || state.session is AppSession.CheckingServer ||
            state.session is AppSession.Authenticating,
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
        offlineDaysRemaining = (state.session as? AppSession.SessionUnavailable)
            ?.entitlementExpiresAtEpochMillis
            ?.let {
                ceil((it - System.currentTimeMillis()).coerceAtLeast(0).toDouble() / MILLIS_PER_DAY).toInt()
            },
        onEnterOffline = actions.onEnterOffline,
        canClose = canClose,
        onClose = actions.onCloseServerCenter,
        modifier = modifier,
    )
}

private const val MILLIS_PER_DAY = 86_400_000.0
