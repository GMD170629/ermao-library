package com.ermao.library

import android.content.Context
import android.content.res.Configuration
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.performClick
import androidx.core.content.ContextCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.bootstrap.ErmaoLibraryRoot
import com.ermao.library.bootstrap.LoginFormState
import com.ermao.library.bootstrap.MainActions
import com.ermao.library.bootstrap.MainUiState
import com.ermao.library.features.shell.MainShell
import com.ermao.library.shared.createAndroidContentRepository
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.Authorization
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.createAndroidPersonalSettingsRepository
import com.ermao.library.shared.createAndroidAdministrativeSettingsRepository
import com.ermao.library.features.me.platform.AndroidXAppLocaleController
import com.ermao.library.ui.theme.WarmPageTheme
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidShellSmokeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun noProfileShowsInlineServerAndLoginFields() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(session = AppSession.NoServer),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(InstrumentationRegistry.getInstrumentation().targetContext),
                )
            }
        }

        composeRule.onNodeWithTag("login-server-address").assertIsDisplayed()
        composeRule.onNodeWithTag("login-submit").assertIsDisplayed()
        composeRule.onAllNodesWithTag("login-entry-close").assertCountEquals(0)
    }

    @Test
    fun loginCheckKeepsVisibleIndeterminateFeedbackAndPreventsAnotherSubmission() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(
                        session = AppSession.CheckingServer(
                            ServerConnectionDraft("127.0.0.1", "http://127.0.0.1:3000"),
                        ),
                        loginForm = LoginFormState(
                            serverAddress = "http://127.0.0.1:3000",
                            email = "reader@example.com",
                            password = "password",
                        ),
                        operationInProgress = true,
                    ),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                )
            }
        }

        composeRule.onNodeWithTag("login-submit").assertIsDisplayed().assertIsNotEnabled()
        composeRule.onNodeWithTag("primary-action-loading").assertIsDisplayed()
    }

    @Test
    fun startupServerProbeLeavesTheLoginFormUsable() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(
                        session = AppSession.CheckingServer(
                            ServerConnectionDraft("127.0.0.1", "http://127.0.0.1:3000"),
                        ),
                        loginForm = LoginFormState(
                            serverAddress = "http://127.0.0.1:3000",
                            email = "reader@example.com",
                            password = "password",
                        ),
                    ),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                )
            }
        }

        composeRule.onNodeWithTag("login-submit").assertIsDisplayed().assertIsEnabled()
    }

    @Test
    fun authenticatedServerManagementReusesLoginEntryAndCanReturnToShell() {
        val session = authenticatedSession()
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(
                        session = session,
                        serverProfiles = listOf(session.profile.toSnapshot()),
                        showServerCenter = true,
                    ),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(InstrumentationRegistry.getInstrumentation().targetContext),
                )
            }
        }

        composeRule.onNodeWithTag("login-server-address").assertIsDisplayed()
        composeRule.onNodeWithTag("login-entry-close").assertIsDisplayed()
    }

    @Test
    fun eachRootTabOwnsAVisibleNavigationDestination() {
        val application = InstrumentationRegistry.getInstrumentation()
            .targetContext
            .applicationContext as ErmaoLibraryApplication
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                MainShell(
                    session = authenticatedSession(),
                    contentRepository = application.contentRepository,
                    personalSettingsRepository = createAndroidPersonalSettingsRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                    administrativeSettingsRepository = createAndroidAdministrativeSettingsRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                    workManagementRepository = application.workManagementRepository,
                    downloadCatalog = application.downloadCatalog,
                    downloadFiles = application.downloadFiles,
                    sharedDownloadCatalog = application.sharedDownloadCatalog,
                    localeController = AndroidXAppLocaleController(),
                    onSessionUnauthorized = {},
                    onRefreshSession = {},
                    onPurgeCurrentNamespace = {},
                    onLogout = {},
                )
            }
        }

        composeRule.onNodeWithTag("tab-home").assertIsDisplayed()
        listOf(
            "library",
            "shelves",
            "me",
            "home",
        ).forEach { tab ->
            composeRule.onNodeWithTag("tab-select-$tab").performClick()
            composeRule.onNodeWithTag("tab-$tab").assertIsDisplayed()
        }
    }

    @Test
    fun lightDarkAndSupportedLocalesResolveFromResources() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val lightContext = context.withNightMode(Configuration.UI_MODE_NIGHT_NO)
        val darkContext = context.withNightMode(Configuration.UI_MODE_NIGHT_YES)
        val englishContext = context.withLocale(Locale.forLanguageTag("en-US"))
        val chineseContext = context.withLocale(Locale.forLanguageTag("zh-CN"))

        assertNotEquals(
            ContextCompat.getColor(lightContext, R.color.window_background),
            ContextCompat.getColor(darkContext, R.color.window_background),
        )
        assertEquals("Home", englishContext.getString(R.string.tab_home))
        assertEquals("首页", chineseContext.getString(R.string.tab_home))
    }
}

private val noOpMainActions = MainActions(
    onOpenServerCenter = {},
    onCloseServerCenter = {},
    onLoginEmailChanged = {},
    onLoginPasswordChanged = {},
    onLoginServerAddressChanged = {},
    onLogin = {},
    onLoginEntry = {},
    onSelectLoginServer = {},
    onDeleteLoginServer = {},
    onAcceptLoginUnsafeTls = {},
    onDismissOperationError = {},
    onSetupNameChanged = {},
    onSetupEmailChanged = {},
    onSetupPasswordChanged = {},
    onSetupConfirmationChanged = {},
    onSetup = {},
    onRetrySession = {},
    onRequireReauthentication = {},
    onRefreshSessionAwaiting = {},
    onPurgeCurrentNamespace = {},
    onLogoutAwaiting = {},
    onLogout = {},
)

private fun authenticatedSession(): AppSession.Authenticated {
    val parsed = ServerBaseUrl.parse("https://books.example.com")
    check(parsed is ServerBaseUrlParseResult.Valid)
    val profile = ServerProfile(
        id = "profile-test",
        displayName = "Home Library",
        baseUrl = parsed.baseUrl,
        serverIdentity = "server-test",
        isActive = true,
        tlsMode = TlsMode.SystemTrust,
    )
    val identity = SessionIdentity(
        userId = "user-test",
        email = "reader@example.com",
        displayName = "Reader",
        namespace = PrivateDataNamespace("server-test", "user-test", 1),
    )
    return AppSession.Authenticated(
        profile,
        identity,
        Authorization(false, false, true, emptySet(), false, 1),
    )
}

private fun Context.withLocale(locale: Locale): Context = createConfigurationContext(
    Configuration(resources.configuration).apply { setLocale(locale) },
)

private fun ServerProfile.toSnapshot() = com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot(
    id = id,
    displayName = displayName,
    baseUrl = baseUrl.value,
    serverIdentity = serverIdentity,
    isActive = isActive,
    tlsMode = tlsMode,
)

private fun Context.withNightMode(nightMode: Int): Context = createConfigurationContext(
    Configuration(resources.configuration).apply {
        uiMode = (uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or nightMode
    },
)
