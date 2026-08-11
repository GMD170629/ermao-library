package com.ermao.library

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ermao.library.bootstrap.ErmaoLibraryRoot
import com.ermao.library.bootstrap.MainActions
import com.ermao.library.bootstrap.MainViewModel
import com.ermao.library.ui.theme.WarmPageTheme

class MainActivity : ComponentActivity() {
    private var hasStarted = false
    private val mainViewModel: MainViewModel by viewModels {
        MainViewModel.factory((application as ErmaoLibraryApplication).mobileRuntime)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            WarmPageTheme {
                val uiState by mainViewModel.uiState.collectAsStateWithLifecycle()
                ErmaoLibraryRoot(
                    state = uiState,
                    actions = MainActions(
                        onServerDisplayNameChanged = mainViewModel::updateServerDisplayName,
                        onServerBaseUrlChanged = mainViewModel::updateServerBaseUrl,
                        onSaveServer = mainViewModel::saveServer,
                        onRetryServerConnection = mainViewModel::retryServerConnection,
                        onPermanentlyIgnoreTls = mainViewModel::permanentlyIgnoreTlsAndConnect,
                        onAddServer = mainViewModel::openAddServer,
                        onReopenConnectionDraft = mainViewModel::reopenConnectionDraft,
                        onCloseServerEditor = mainViewModel::closeServerEditor,
                        onOpenServerCenter = mainViewModel::openServerCenter,
                        onCloseServerCenter = mainViewModel::closeServerCenter,
                        onSelectServer = mainViewModel::selectServerProfile,
                        onCloseServerDetail = mainViewModel::closeServerDetail,
                        onEditSavedServer = mainViewModel::openEditServer,
                        onSwitchServer = mainViewModel::switchServer,
                        onRemoveServer = mainViewModel::removeServer,
                        onRestoreSystemTrust = mainViewModel::restoreSystemTrust,
                        onLoginEmailChanged = mainViewModel::updateLoginEmail,
                        onLoginPasswordChanged = mainViewModel::updateLoginPassword,
                        onLogin = mainViewModel::login,
                        onSetupNameChanged = mainViewModel::updateSetupName,
                        onSetupEmailChanged = mainViewModel::updateSetupEmail,
                        onSetupPasswordChanged = mainViewModel::updateSetupPassword,
                        onSetupConfirmationChanged = mainViewModel::updateSetupConfirmation,
                        onSetup = mainViewModel::setupInitialAdmin,
                        onRetrySession = mainViewModel::retrySession,
                        onEnterOffline = mainViewModel::enterOfflineMode,
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
