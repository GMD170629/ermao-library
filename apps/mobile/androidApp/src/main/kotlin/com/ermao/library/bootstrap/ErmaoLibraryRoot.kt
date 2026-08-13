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
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.features.downloads.application.DownloadCenterViewModel
import com.ermao.library.features.downloads.application.DownloadedWorkViewModel
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.ui.DownloadCenterScreen
import com.ermao.library.features.downloads.ui.DownloadedWorkScreen
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlin.math.ceil

@Composable
fun ErmaoLibraryRoot(
    state: MainUiState,
    actions: MainActions,
    modifier: Modifier = Modifier,
    contentRepository: ContentRepository,
    personalSettingsRepository: PersonalSettingsRepository? = null,
    administrativeSettingsRepository: AdministrativeSettingsRepository? = null,
    downloadCatalog: AndroidDownloadCatalog? = null,
    downloadFiles: AtomicDownloadFileSink? = null,
    sharedDownloadCatalog: DownloadCatalogRepository? = null,
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
        is AppSession.OfflineGrace -> if (downloadCatalog != null && downloadFiles != null) {
            OfflineDownloadsShell(
                session = session,
                downloadCatalog = downloadCatalog,
                downloadFiles = downloadFiles,
                onRetryAuthentication = actions.onRetrySession,
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
        } else {
            OfflineEmptyShell(
                profile = session.profile,
                userEmail = session.identity.email,
                onRetryAuthentication = actions.onRetrySession,
                onSwitchServer = actions.onOpenServerCenter,
                modifier = modifier,
            )
        }
        is AppSession.IncompatibleServer -> LoginEntry(
            state, actions,
            LoginEntryAlert.IncompatibleServer.takeIf { state.operationErrorCode != null },
            modifier,
        )
    }
}

@Composable
private fun OfflineDownloadsShell(
    session: AppSession.OfflineGrace,
    downloadCatalog: AndroidDownloadCatalog,
    downloadFiles: AtomicDownloadFileSink,
    onRetryAuthentication: () -> Unit,
    onSwitchServer: () -> Unit,
    modifier: Modifier,
) {
    val namespace = AndroidDownloadNamespace(
        session.identity.namespace.serverIdentity,
        session.identity.namespace.userId,
        session.identity.namespace.authorizationVersion,
    )
    val namespaceKey = "${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"
    val appContext = LocalContext.current.applicationContext
    var selectedWorkId by rememberSaveable(namespaceKey) { mutableStateOf<String?>(null) }
    var showReaderUnavailable by rememberSaveable(namespaceKey) { mutableStateOf(false) }
    if (showReaderUnavailable) {
        BlockingServerStateScreen(
            title = stringResource(R.string.reader_not_implemented_title),
            message = stringResource(R.string.reader_not_implemented_message),
            primaryLabel = stringResource(R.string.navigate_back),
            onPrimary = { showReaderUnavailable = false },
            modifier = modifier,
        )
        return
    }
    val workId = selectedWorkId
    if (workId != null) {
        val workViewModel: DownloadedWorkViewModel = viewModel(
            key = "offline-download-work-$namespaceKey-$workId",
            factory = DownloadedWorkViewModel.factory(downloadCatalog, namespace, workId) { record ->
                downloadFiles.isVerifiedLocalArtifact(record.localReference, record.expectedBytes)
            },
        )
        val workState by workViewModel.uiState.collectAsStateWithLifecycle()
        DownloadedWorkScreen(
            state = workState,
            onBack = { selectedWorkId = null },
            onOpenVolume = { record ->
                if (record.readerType.equals("reflowable", true) && record.format.equals("EPUB", true)) {
                    appContext.startActivity(
                        com.ermao.library.features.reader.presentation.ReaderActivity.createManagedDownloadIntent(
                            context = appContext,
                            profileId = session.profile.id,
                            workId = record.workId,
                            volumeId = record.volumeId,
                            displayTitle = record.workTitle,
                            localReference = checkNotNull(record.localReference),
                            serverContentFingerprint = record.contentFingerprint,
                            expectedBytes = record.expectedBytes,
                        ),
                    )
                } else {
                    showReaderUnavailable = true
                }
            },
            modifier = modifier,
        )
        return
    }
    val centerViewModel: DownloadCenterViewModel = viewModel(
        key = "offline-downloads-$namespaceKey",
        factory = DownloadCenterViewModel.factory(downloadCatalog, namespace) { record ->
            downloadFiles.isVerifiedLocalArtifact(record.localReference, record.expectedBytes)
        },
    )
    val centerState by centerViewModel.uiState.collectAsStateWithLifecycle()
    DownloadCenterScreen(
        state = centerState,
        onBack = {},
        onQueryChanged = centerViewModel::updateQuery,
        onClearQuery = centerViewModel::clearQuery,
        onOpenWork = { selectedWorkId = it },
        onRetry = centerViewModel::retry,
        onCancelDownload = {},
        onRetryDownload = {},
        onRemoveDownload = {},
        modifier = modifier,
        showBackNavigation = false,
        allowManagementActions = false,
        offlineActions = {
            val theme = WarmPageThemeValues
            Column(
                Modifier.fillMaxWidth().padding(horizontal = theme.spacing.three),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                Text(stringResource(R.string.offline_scope_message), color = theme.colors.textSecondary)
                Row {
                    TextButton(onClick = onRetryAuthentication) {
                        Text(stringResource(R.string.offline_retry_authentication))
                    }
                    TextButton(onClick = onSwitchServer) {
                        Text(stringResource(R.string.server_choose_other_action))
                    }
                }
            }
        },
    )
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
