package com.ermao.library

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ermao.library.bootstrap.ErmaoLibraryRoot
import com.ermao.library.bootstrap.MainActions
import com.ermao.library.bootstrap.MainViewModel
import com.ermao.library.ui.theme.WarmPageTheme
import com.ermao.library.features.me.platform.AndroidXAppLocaleController

class MainActivity : AppCompatActivity() {
    private var hasStarted = false
    private val localeController = AndroidXAppLocaleController()
    private val mainViewModel: MainViewModel by viewModels {
        val app = application as ErmaoLibraryApplication
        MainViewModel.factory(
            runtime = app.mobileRuntime,
            credentialStore = app.loginCredentialStore,
            appContext = app,
            localeController = localeController,
            initialLoginForm = localLoginDefaults(),
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            WarmPageTheme {
                val uiState by mainViewModel.uiState.collectAsStateWithLifecycle()
                ErmaoLibraryRoot(
                    state = uiState,
                    contentRepository = (application as ErmaoLibraryApplication).contentRepository,
                    personalSettingsRepository = (application as ErmaoLibraryApplication).personalSettingsRepository,
                    administrativeSettingsRepository = (application as ErmaoLibraryApplication).administrativeSettingsRepository,
                    workManagementRepository = (application as ErmaoLibraryApplication).workManagementRepository,
                    downloadCatalog = (application as ErmaoLibraryApplication).downloadCatalog,
                    downloadFiles = (application as ErmaoLibraryApplication).downloadFiles,
                    sharedDownloadCatalog = (application as ErmaoLibraryApplication).sharedDownloadCatalog,
                    localeController = localeController,
                    actions = MainActions(
                        onOpenServerCenter = mainViewModel::openServerCenter,
                        onCloseServerCenter = mainViewModel::closeServerCenter,
                        onLoginEmailChanged = mainViewModel::updateLoginEmail,
                        onLoginPasswordChanged = mainViewModel::updateLoginPassword,
                        onLoginServerAddressChanged = mainViewModel::updateLoginServerAddress,
                        onLogin = mainViewModel::login,
                        onLoginEntry = mainViewModel::loginFromEntry,
                        onSelectLoginServer = mainViewModel::selectLoginServer,
                        onDeleteLoginServer = mainViewModel::deleteDisplayedServer,
                        onAcceptLoginUnsafeTls = mainViewModel::acceptUnsafeTlsAndLogin,
                        onDismissOperationError = mainViewModel::dismissOperationError,
                        onSetupNameChanged = mainViewModel::updateSetupName,
                        onSetupEmailChanged = mainViewModel::updateSetupEmail,
                        onSetupPasswordChanged = mainViewModel::updateSetupPassword,
                        onSetupConfirmationChanged = mainViewModel::updateSetupConfirmation,
                        onSetup = mainViewModel::setupInitialAdmin,
                        onRetrySession = mainViewModel::retrySession,
                        onRequireReauthentication = mainViewModel::requireReauthentication,
                        onRefreshSessionAwaiting = mainViewModel::refreshSessionAwaitingCompletion,
                        onPurgeCurrentNamespace = mainViewModel::purgeCurrentNamespace,
                        onLogoutAwaiting = mainViewModel::logoutAwaitingCompletion,
                        onLogout = mainViewModel::logout,
                    ),
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()
        if (hasStarted) mainViewModel.onForegrounded() else hasStarted = true
    }
}
