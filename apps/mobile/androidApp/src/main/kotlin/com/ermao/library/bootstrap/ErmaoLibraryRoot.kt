package com.ermao.library.bootstrap

import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import com.ermao.library.R
import com.ermao.library.features.auth.LoginScreen
import com.ermao.library.features.auth.OfflineEmptyShell
import com.ermao.library.features.auth.ReauthenticateScreen
import com.ermao.library.features.auth.SetupScreen
import com.ermao.library.features.servers.BlockingServerStateScreen
import com.ermao.library.features.servers.EmptyServerGate
import com.ermao.library.features.servers.ServerCenterScreen
import com.ermao.library.features.servers.ServerEditorScreen
import com.ermao.library.features.servers.TlsRiskScreen
import com.ermao.library.features.shell.MainShell
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.servers.domain.TlsMode

@Composable
fun ErmaoLibraryRoot(state: MainUiState, actions: MainActions, modifier: Modifier = Modifier) {
    if (state.showServerEditor) {
        val editingProfile = state.editingProfileId?.let { id -> state.serverProfiles.firstOrNull { it.id == id } }
        ServerEditorScreen(
            form = state.serverForm,
            isChecking = state.operationInProgress,
            connectionFailed = state.operationErrorCode != null,
            unexpectedFailure = state.operationErrorCode == "RUNTIME_FAILURE",
            isEditing = state.serverEditorMode == ServerEditorMode.Edit,
            insecureTls = editingProfile?.tlsMode == TlsMode.InsecureSkipAllValidation,
            onDisplayNameChanged = actions.onServerDisplayNameChanged,
            onBaseUrlChanged = actions.onServerBaseUrlChanged,
            onSubmit = actions.onSaveServer,
            onBack = actions.onCloseServerEditor,
            modifier = modifier,
        )
        return
    }

    if (state.showServerCenter) {
        ServerCenterScreen(
            profiles = state.serverProfiles,
            selectedProfileId = state.selectedProfileId,
            operationInProgress = state.operationInProgress,
            operationErrorCode = state.operationErrorCode,
            canClose = state.session !is AppSession.NoServer,
            onClose = actions.onCloseServerCenter,
            onAdd = actions.onAddServer,
            onSelect = actions.onSelectServer,
            onCloseDetail = actions.onCloseServerDetail,
            onEdit = actions.onEditSavedServer,
            onSwitch = actions.onSwitchServer,
            onRemove = actions.onRemoveServer,
            onRestoreSystemTrust = actions.onRestoreSystemTrust,
            modifier = modifier,
        )
        return
    }

    val locale = LocalConfiguration.current.locales[0]?.language
        ?.let { if (it == "zh") "zh-CN" else "en-US" }
        ?: "en-US"

    when (val session = state.session) {
        AppSession.NoServer -> EmptyServerGate(onAddServer = actions.onAddServer, modifier = modifier)
        is AppSession.CheckingServer -> ServerEditorScreen(
            form = state.serverForm,
            isChecking = true,
            connectionFailed = false,
            unexpectedFailure = false,
            onDisplayNameChanged = actions.onServerDisplayNameChanged,
            onBaseUrlChanged = actions.onServerBaseUrlChanged,
            onSubmit = actions.onSaveServer,
            onBack = actions.onCloseServerEditor,
            modifier = modifier,
        )
        is AppSession.ServerConnectionFailed -> ServerEditorScreen(
            form = state.serverForm,
            isChecking = false,
            connectionFailed = true,
            unexpectedFailure = state.operationErrorCode == "RUNTIME_FAILURE",
            onDisplayNameChanged = actions.onServerDisplayNameChanged,
            onBaseUrlChanged = actions.onServerBaseUrlChanged,
            onSubmit = actions.onRetryServerConnection,
            onBack = actions.onOpenServerCenter,
            modifier = modifier,
        )
        is AppSession.TlsRisk -> TlsRiskScreen(
            serverDisplayName = session.draft.displayName,
            serverAddress = session.draft.rawBaseUrl,
            onBackToEdit = actions.onReopenConnectionDraft,
            onPermanentlyIgnore = actions.onPermanentlyIgnoreTls,
            modifier = modifier,
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
        is AppSession.SignedOut -> LoginScreen(
            profile = session.profile,
            form = state.loginForm,
            isAuthenticating = false,
            sessionMessage = null,
            unexpectedFailure = state.operationErrorCode == "RUNTIME_FAILURE",
            onEmailChanged = actions.onLoginEmailChanged,
            onPasswordChanged = actions.onLoginPasswordChanged,
            onLogin = { actions.onLogin(null) },
            onSwitchServer = actions.onOpenServerCenter,
            modifier = modifier,
        )
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
            LoginScreen(
                profile = session.profile,
                form = state.loginForm,
                isAuthenticating = true,
                sessionMessage = null,
                unexpectedFailure = false,
                onEmailChanged = actions.onLoginEmailChanged,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = {},
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
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
            LoginScreen(
                profile = session.profile,
                form = state.loginForm.copy(invalidCredentials = session.failureCode == INVALID_CREDENTIALS),
                isAuthenticating = false,
                sessionMessage = if (session.failureCode == INVALID_CREDENTIALS) null else stringResource(R.string.login_temporarily_unavailable),
                unexpectedFailure = false,
                onEmailChanged = actions.onLoginEmailChanged,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = { actions.onLogin(null) },
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
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
            MainShell(
                session = session,
                onOpenServers = actions.onOpenServerCenter,
                onLogout = actions.onLogout,
                modifier = modifier,
            )
        }
        is AppSession.SessionUnavailable -> session.lastKnownIdentity?.let { identity ->
            ReauthenticateScreen(
                profile = session.profile,
                userDisplayName = identity.displayName,
                userEmail = identity.email,
                entitlementExpiresAtEpochMillis = session.entitlementExpiresAtEpochMillis,
                form = state.loginForm,
                isAuthenticating = false,
                serverUnavailable = true,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = { actions.onLogin(identity.email) },
                onEnterOffline = actions.onEnterOffline,
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
        } ?: run {
            BlockingServerStateScreen(
                title = stringResource(R.string.session_unavailable_title),
                message = stringResource(R.string.session_unavailable_message),
                primaryLabel = stringResource(R.string.server_retry_action),
                onPrimary = actions.onRetrySession,
                secondaryLabel = stringResource(R.string.server_choose_other_action),
                onSecondary = actions.onOpenServerCenter,
                modifier = modifier,
            )
        }
        is AppSession.SessionExpired -> session.lastKnownIdentity?.let { identity ->
            ReauthenticateScreen(
                profile = session.profile,
                userDisplayName = identity.displayName,
                userEmail = identity.email,
                entitlementExpiresAtEpochMillis = session.entitlementExpiresAtEpochMillis,
                form = state.loginForm,
                isAuthenticating = false,
                serverUnavailable = false,
                onPasswordChanged = actions.onLoginPasswordChanged,
                onLogin = { actions.onLogin(identity.email) },
                onEnterOffline = actions.onEnterOffline,
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
        } ?: LoginScreen(
            profile = session.profile,
            form = state.loginForm,
            isAuthenticating = false,
            sessionMessage = stringResource(R.string.session_expired_message),
            unexpectedFailure = false,
            onEmailChanged = actions.onLoginEmailChanged,
            onPasswordChanged = actions.onLoginPasswordChanged,
            onLogin = { actions.onLogin(null) },
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
        is AppSession.IncompatibleServer -> BlockingServerStateScreen(
            title = stringResource(R.string.server_incompatible_title),
            message = stringResource(R.string.server_incompatible_message),
            primaryLabel = stringResource(R.string.server_choose_other_action),
            onPrimary = actions.onOpenServerCenter,
            secondaryLabel = stringResource(R.string.server_retry_action),
            onSecondary = actions.onRetryServerConnection,
            modifier = modifier,
        )
    }
}

private const val INVALID_CREDENTIALS = "INVALID_CREDENTIALS"

data class MainActions(
    val onServerDisplayNameChanged: (String) -> Unit,
    val onServerBaseUrlChanged: (String) -> Unit,
    val onSaveServer: () -> Unit,
    val onRetryServerConnection: () -> Unit,
    val onPermanentlyIgnoreTls: () -> Unit,
    val onAddServer: () -> Unit,
    val onReopenConnectionDraft: () -> Unit,
    val onCloseServerEditor: () -> Unit,
    val onOpenServerCenter: () -> Unit,
    val onCloseServerCenter: () -> Unit,
    val onSelectServer: (String) -> Unit,
    val onCloseServerDetail: () -> Unit,
    val onEditSavedServer: (String) -> Unit,
    val onSwitchServer: (String) -> Unit,
    val onRemoveServer: (String) -> Unit,
    val onRestoreSystemTrust: (String) -> Unit,
    val onLoginEmailChanged: (String) -> Unit,
    val onLoginPasswordChanged: (String) -> Unit,
    val onLogin: (String?) -> Unit,
    val onSetupNameChanged: (String) -> Unit,
    val onSetupEmailChanged: (String) -> Unit,
    val onSetupPasswordChanged: (String) -> Unit,
    val onSetupConfirmationChanged: (String) -> Unit,
    val onSetup: (String) -> Unit,
    val onRetrySession: () -> Unit,
    val onEnterOffline: () -> Unit,
    val onLogout: () -> Unit,
)
