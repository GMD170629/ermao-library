package com.ermao.library.bootstrap

import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.platform.persistence.LoginCredentialStore
import com.ermao.library.platform.persistence.NoOpLoginCredentialStore
import com.ermao.library.platform.persistence.SavedLoginCredential
import com.ermao.library.features.me.platform.AppLocaleController
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.auth.Observation
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.SessionObserver
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.Authorization
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MainViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun invalidServerInputStaysAtBoundaryAndDoesNotCallRuntime() = runTest(dispatcher) {
        val runtime = FakeMobileRuntime(AppSession.NoServer)
        val viewModel = viewModel(runtime)

        viewModel.updateServerDisplayName("Home")
        viewModel.updateServerBaseUrl("books.example.com")
        viewModel.saveServer()
        advanceUntilIdle()

        assertEquals(ServerFormError.InvalidBaseUrl, viewModel.uiState.value.serverForm.baseUrlError)
        assertNull(runtime.lastConnectionDraft)
    }

    @Test
    fun validServerInputIsNormalizedBySharedValueObjectBeforeRuntimeCall() = runTest(dispatcher) {
        val runtime = FakeMobileRuntime(AppSession.NoServer)
        val viewModel = viewModel(runtime)

        viewModel.updateServerDisplayName(" Home ")
        viewModel.updateServerBaseUrl(" https://Books.Example.com/base/ ")
        viewModel.saveServer()
        advanceUntilIdle()

        assertEquals("Home", runtime.lastConnectionDraft?.displayName)
        assertEquals("https://Books.Example.com/base/", runtime.lastConnectionDraft?.rawBaseUrl)
        assertEquals(TlsMode.SystemTrust, runtime.lastConnectionDraft?.tlsMode)
    }

    @Test
    fun tlsConfirmationResubmitsOnlyTheTlsMode() = runTest(dispatcher) {
        val draft = ServerConnectionDraft("Home", "https://books.example.com/base")
        val runtime = FakeMobileRuntime(AppSession.TlsRisk(draft, "TLS_FAILURE"))
        val viewModel = viewModel(runtime)

        viewModel.permanentlyIgnoreTlsAndConnect()
        advanceUntilIdle()

        assertEquals(1, runtime.acceptInsecureTlsCalls)
    }

    @Test
    fun setupValidationRejectsShortAndMismatchedPasswordsBeforeRuntime() = runTest(dispatcher) {
        val runtime = FakeMobileRuntime(AppSession.NoServer)
        val viewModel = viewModel(runtime)
        viewModel.updateSetupName("Admin")
        viewModel.updateSetupEmail("admin@example.com")
        viewModel.updateSetupPassword("short")
        viewModel.updateSetupConfirmation("different")

        viewModel.setupInitialAdmin("en-US")
        advanceUntilIdle()

        assertEquals(SetupFieldError.PasswordTooShort, viewModel.uiState.value.setupForm.passwordError)
        assertEquals(SetupFieldError.PasswordMismatch, viewModel.uiState.value.setupForm.confirmationError)
        assertEquals(0, runtime.setupCalls)
    }

    @Test
    fun provisionalSetupProfileRemainsUsableBeforeItIsPersisted() = runTest(dispatcher) {
        val provisional = profile("setup", "https://setup.example", active = true)
        val runtime = FakeMobileRuntime(AppSession.SetupRequired(provisional))

        val viewModel = viewModel(runtime)
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.session is AppSession.SetupRequired)
        assertTrue(viewModel.uiState.value.serverProfiles.isEmpty())
    }

    @Test
    fun successfulSetupStoresCapturedCredentialForNewActiveProfile() = runTest(dispatcher) {
        val provisional = profile("setup", "https://setup.example", active = true)
        val runtime = FakeMobileRuntime(AppSession.SetupRequired(provisional)).apply {
            authenticatedAfterSetup = authenticated(provisional)
        }
        val credentials = FakeCredentialStore()
        val viewModel = viewModel(runtime, credentials)
        viewModel.updateSetupName("Admin")
        viewModel.updateSetupEmail(" admin@example.com ")
        viewModel.updateSetupPassword("setup-password")
        viewModel.updateSetupConfirmation("setup-password")

        viewModel.setupInitialAdmin("en-US")
        advanceUntilIdle()

        assertEquals(
            SavedLoginCredential("admin@example.com", "setup-password"),
            credentials.load(provisional.id),
        )
    }

    @Test
    fun setupCredentialStorageFailureIsReportedWithoutUndoingAuthentication() = runTest(dispatcher) {
        val provisional = profile("setup", "https://setup.example", active = true)
        val runtime = FakeMobileRuntime(AppSession.SetupRequired(provisional)).apply {
            authenticatedAfterSetup = authenticated(provisional)
        }
        val credentials = FakeCredentialStore().apply { failSave = true }
        val viewModel = viewModel(runtime, credentials)
        viewModel.updateSetupName("Admin")
        viewModel.updateSetupEmail("admin@example.com")
        viewModel.updateSetupPassword("setup-password")
        viewModel.updateSetupConfirmation("setup-password")

        viewModel.setupInitialAdmin("en-US")
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.session is AppSession.Authenticated)
        assertEquals("CREDENTIAL_STORAGE_FAILED", viewModel.uiState.value.operationErrorCode)
        assertEquals(AppErrorKind.StorageFailure, viewModel.uiState.value.operationErrorKind)
    }

    @Test
    fun savedServerAndCredentialPrefillTheLoginEntry() = runTest(dispatcher) {
        val profile = profile("home", "https://books.example/library", active = true)
        val credentials = FakeCredentialStore().apply {
            save(profile.id, SavedLoginCredential("reader@example.com", "safe-password"))
        }
        val runtime = FakeMobileRuntime(AppSession.SignedOut(profile), listOf(profile.toSnapshot()))

        val viewModel = viewModel(runtime, credentials)
        advanceUntilIdle()

        assertEquals(profile.id, viewModel.uiState.value.loginProfileId)
        assertEquals("https://books.example/library", viewModel.uiState.value.loginForm.serverAddress)
        assertEquals("reader@example.com", viewModel.uiState.value.loginForm.email)
        assertEquals("safe-password", viewModel.uiState.value.loginForm.password)
    }

    @Test
    fun openingServerManagementReusesLoginEntryAndRefillsActiveProfile() = runTest(dispatcher) {
        val profile = profile("home", "https://home.example", active = true)
        val credentials = FakeCredentialStore().apply {
            save(profile.id, SavedLoginCredential("reader@example.com", "saved-password"))
        }
        val runtime = FakeMobileRuntime(authenticated(profile), listOf(profile.toSnapshot()))
        val viewModel = viewModel(runtime, credentials)

        viewModel.openServerCenter()
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.showServerCenter)
        assertEquals(profile.id, viewModel.uiState.value.loginProfileId)
        assertEquals(profile.baseUrl.value, viewModel.uiState.value.loginForm.serverAddress)
        assertEquals("reader@example.com", viewModel.uiState.value.loginForm.email)
        assertEquals("saved-password", viewModel.uiState.value.loginForm.password)
    }

    @Test
    fun entryLoginUsesAtomicRuntimeIntentAndKeepsUnauthorizedPasswordForCorrection() = runTest(dispatcher) {
        val runtime = FakeMobileRuntime(AppSession.NoServer).apply {
            loginToServerResult = RuntimeOperationResult.Failure(
                AppError(AppErrorKind.Unauthorized, "INVALID_CREDENTIALS"),
            )
        }
        val viewModel = viewModel(runtime)
        viewModel.updateLoginServerAddress("https://Books.Example.com/library/")
        viewModel.updateLoginEmail(" reader@example.com ")
        viewModel.updateLoginPassword("attempted-password")

        viewModel.loginFromEntry()
        advanceUntilIdle()

        assertEquals("https://books.example.com/library", runtime.loginToServerAddress)
        assertEquals("reader@example.com", runtime.loginToServerEmail)
        assertEquals("attempted-password", runtime.loginToServerPassword)
        assertTrue(viewModel.uiState.value.loginForm.invalidCredentials)
        assertEquals("attempted-password", viewModel.uiState.value.loginForm.password)
    }

    @Test
    fun entryLoginKeepsLoadingStateResponsiveAndIgnoresDuplicateSubmission() = runTest(dispatcher) {
        val loginGate = CompletableDeferred<Unit>()
        val runtime = FakeMobileRuntime(AppSession.NoServer).apply { this.loginGate = loginGate }
        val viewModel = viewModel(runtime)
        advanceUntilIdle()
        viewModel.updateLoginServerAddress("https://books.example.com")
        viewModel.updateLoginEmail("reader@example.com")
        viewModel.updateLoginPassword("password")

        viewModel.loginFromEntry()
        runCurrent()

        assertTrue(viewModel.uiState.value.operationInProgress)
        viewModel.loginFromEntry()
        runCurrent()
        assertEquals(1, runtime.loginToServerCalls)

        loginGate.complete(Unit)
        advanceUntilIdle()
        assertFalse(viewModel.uiState.value.operationInProgress)
    }

    @Test
    fun entryLoginCancelsStartupSessionRestoreBeforeSubmitting() = runTest(dispatcher) {
        val startupGate = CompletableDeferred<Unit>()
        val runtime = FakeMobileRuntime(AppSession.NoServer).apply { startGate = startupGate }
        val viewModel = viewModel(runtime)
        runCurrent()
        viewModel.updateLoginServerAddress("https://books.example.com")
        viewModel.updateLoginEmail("reader@example.com")
        viewModel.updateLoginPassword("password")

        viewModel.loginFromEntry()
        advanceUntilIdle()

        assertEquals(1, runtime.startCalls)
        assertFalse(startupGate.isCompleted)
        assertEquals(1, runtime.loginToServerCalls)
        assertFalse(viewModel.uiState.value.operationInProgress)
    }

    @Test
    fun selectingAnotherServerOnlyRefillsTheForm() = runTest(dispatcher) {
        val current = profile("home", "https://home.example", active = true)
        val other = profile("office", "https://office.example", active = false)
        val credentials = FakeCredentialStore().apply {
            save(other.id, SavedLoginCredential("office@example.com", "office-password"))
        }
        val runtime = FakeMobileRuntime(
            AppSession.SignedOut(current),
            listOf(current.toSnapshot(), other.toSnapshot()),
        )
        val viewModel = viewModel(runtime, credentials)

        viewModel.selectLoginServer(other.id)
        advanceUntilIdle()

        assertEquals(other.id, viewModel.uiState.value.loginProfileId)
        assertEquals(other.baseUrl.value, viewModel.uiState.value.loginForm.serverAddress)
        assertEquals("office@example.com", viewModel.uiState.value.loginForm.email)
        assertEquals("office@example.com", viewModel.uiState.value.savedAccountEmails[other.id])
        assertEquals(0, runtime.switchServerCalls)
    }

    @Test
    fun successfulEntryLoginStoresCredentialForTheActivatedProfile() = runTest(dispatcher) {
        val profile = profile("home", "https://home.example", active = true)
        val runtime = FakeMobileRuntime(AppSession.NoServer, listOf(profile.toSnapshot())).apply {
            authenticatedAfterLogin = authenticated(profile)
        }
        val credentials = FakeCredentialStore()
        val viewModel = viewModel(runtime, credentials)
        viewModel.updateLoginServerAddress(profile.baseUrl.value)
        viewModel.updateLoginEmail("reader@example.com")
        viewModel.updateLoginPassword("saved-password")

        viewModel.loginFromEntry()
        advanceUntilIdle()

        assertEquals(
            SavedLoginCredential("reader@example.com", "saved-password"),
            credentials.load(profile.id),
        )
    }

    @Test
    fun deletingDisplayedServerRemovesCredentialAndClearsFields() = runTest(dispatcher) {
        val profile = profile("home", "https://home.example", active = true)
        val credentials = FakeCredentialStore().apply {
            save(profile.id, SavedLoginCredential("reader@example.com", "saved-password"))
        }
        val runtime = FakeMobileRuntime(AppSession.SignedOut(profile), listOf(profile.toSnapshot()))
        val viewModel = viewModel(runtime, credentials)

        viewModel.deleteDisplayedServer()
        advanceUntilIdle()

        assertEquals(profile.id, runtime.removedProfileId)
        assertNull(credentials.load(profile.id))
        assertEquals(LoginFormState(), viewModel.uiState.value.loginForm)
        assertNull(viewModel.uiState.value.loginProfileId)
    }

    @Test
    fun credentialRemovalFailureIsReportedAfterServerAndFieldsAreRemoved() = runTest(dispatcher) {
        val profile = profile("home", "https://home.example", active = true)
        val credentials = FakeCredentialStore().apply {
            save(profile.id, SavedLoginCredential("reader@example.com", "saved-password"))
            failRemoval = true
        }
        val runtime = FakeMobileRuntime(AppSession.SignedOut(profile), listOf(profile.toSnapshot()))
        val viewModel = viewModel(runtime, credentials)

        viewModel.deleteDisplayedServer()
        advanceUntilIdle()

        assertEquals("CREDENTIAL_STORAGE_FAILED", viewModel.uiState.value.operationErrorCode)
        assertEquals(AppErrorKind.StorageFailure, viewModel.uiState.value.operationErrorKind)
        assertEquals(LoginFormState(), viewModel.uiState.value.loginForm)
    }

    @Test
    fun settingsUnauthorizedUsesReauthenticationStateWithCapturedIdentity() = runTest(dispatcher) {
        val profile = profile("home", "https://home.example", active = true)
        val authenticated = authenticated(profile)
        val runtime = FakeMobileRuntime(authenticated).apply {
            sessionAfterRefresh = AppSession.SessionExpired(profile, authenticated.identity)
        }
        val viewModel = viewModel(runtime)

        viewModel.requireReauthentication()
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.isReauthenticating)
        assertEquals("Reader", viewModel.uiState.value.reauthUserName)
        assertEquals("reader@example.com", viewModel.uiState.value.reauthUserEmail)
        assertTrue(viewModel.uiState.value.session is AppSession.SessionExpired)
    }

    @Test
    fun failedLogoutDoesNotRestoreSystemLanguageForAuthenticatedSession() = runTest(dispatcher) {
        val profile = profile("home", "https://home.example", active = true)
        val runtime = FakeMobileRuntime(authenticated(profile)).apply {
            logoutResult = RuntimeOperationResult.Failure(AppError(AppErrorKind.StorageFailure, "LOGOUT_FAILED"))
        }
        val localeController = RecordingLocaleController()
        val viewModel = viewModel(runtime, localeController = localeController)
        advanceUntilIdle()

        runCatching { viewModel.logoutAwaitingCompletion(purgeNamespace = false) }

        assertFalse(localeController.didRestoreSystemLanguage)
        assertTrue(runtime.currentSession is AppSession.Authenticated)
    }

    private fun viewModel(
        runtime: MobileRuntime,
        credentialStore: LoginCredentialStore = NoOpLoginCredentialStore,
        localeController: AppLocaleController? = null,
    ) = MainViewModel(
        runtime = runtime,
        credentialStore = credentialStore,
        localeController = localeController,
        runtimeDispatcher = dispatcher,
    )

    private class FakeMobileRuntime(
        initialSession: AppSession,
        initialProfiles: List<ServerProfileSnapshot> = emptyList(),
    ) : MobileRuntime {
        private var observer: SessionObserver? = null
        override var currentSession: AppSession = initialSession
            private set
        private var profiles: List<ServerProfileSnapshot> = initialProfiles
        override val serverProfiles: List<ServerProfileSnapshot>
            get() = profiles
        var lastConnectionDraft: ServerConnectionDraft? = null
            private set
        var acceptInsecureTlsCalls: Int = 0
            private set
        var setupCalls: Int = 0
            private set
        var loginToServerResult: RuntimeOperationResult = RuntimeOperationResult.Success()
        var loginToServerAddress: String? = null
        var loginToServerEmail: String? = null
        var loginToServerPassword: String? = null
        var loginToServerCalls = 0
        var loginGate: CompletableDeferred<Unit>? = null
        var startCalls = 0
        var startGate: CompletableDeferred<Unit>? = null
        var switchServerCalls = 0
        var removedProfileId: String? = null
        var authenticatedAfterLogin: AppSession.Authenticated? = null
        var authenticatedAfterSetup: AppSession.Authenticated? = null
        var sessionAfterRefresh: AppSession? = null
        var logoutResult: RuntimeOperationResult = RuntimeOperationResult.Success()

        override fun observeSession(observer: SessionObserver): Observation {
            this.observer = observer
            return Observation { this.observer = null }
        }

        override suspend fun start(): RuntimeOperationResult {
            startCalls += 1
            startGate?.await()
            return RuntimeOperationResult.Success()
        }

        override suspend fun connectServer(command: ServerConnectionDraft): RuntimeOperationResult {
            lastConnectionDraft = command
            return RuntimeOperationResult.Success()
        }

        override suspend fun editServer(
            profileId: String,
            command: ServerConnectionDraft,
        ): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun switchServer(profileId: String): RuntimeOperationResult {
            switchServerCalls += 1
            return RuntimeOperationResult.Success()
        }

        override suspend fun removeServer(profileId: String): RuntimeOperationResult {
            removedProfileId = profileId
            return RuntimeOperationResult.Success()
        }

        override suspend fun restoreSystemTrust(profileId: String): RuntimeOperationResult =
            RuntimeOperationResult.Success()

        override suspend fun acceptInsecureTls(): RuntimeOperationResult {
            acceptInsecureTlsCalls += 1
            return RuntimeOperationResult.Success()
        }

        override suspend fun retry(): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun login(email: String, password: String): RuntimeOperationResult =
            RuntimeOperationResult.Success()

        override suspend fun loginToServer(
            baseUrl: String,
            email: String,
            password: String,
        ): RuntimeOperationResult {
            loginToServerCalls += 1
            loginToServerAddress = baseUrl
            loginToServerEmail = email
            loginToServerPassword = password
            loginGate?.await()
            authenticatedAfterLogin?.let {
                currentSession = it
                observer?.onSessionChanged(it)
            }
            return loginToServerResult
        }

        override suspend fun loginToServerAcceptingInsecureTls(
            baseUrl: String,
            email: String,
            password: String,
        ): RuntimeOperationResult = loginToServer(baseUrl, email, password)

        override suspend fun setupInitialAdmin(
            name: String,
            email: String,
            password: String,
            locale: String,
        ): RuntimeOperationResult {
            setupCalls += 1
            authenticatedAfterSetup?.let {
                profiles = listOf(it.profile.toSnapshot())
                currentSession = it
                observer?.onSessionChanged(it)
            }
            return RuntimeOperationResult.Success()
        }

        override suspend fun refreshCurrentSession(): RuntimeOperationResult {
            sessionAfterRefresh?.let {
                currentSession = it
                observer?.onSessionChanged(it)
            }
            return RuntimeOperationResult.Success()
        }


        override suspend fun logout(): RuntimeOperationResult = logoutResult

        override fun close() = Unit
    }

    private class RecordingLocaleController : AppLocaleController {
        var didRestoreSystemLanguage = false
        override fun apply(locale: PersonalSettingsLocale) = Unit
        override fun restoreSystemLanguage() {
            didRestoreSystemLanguage = true
        }
    }

    private class FakeCredentialStore : LoginCredentialStore {
        private val credentials = mutableMapOf<String, SavedLoginCredential>()
        var failRemoval = false
        var failSave = false
        override fun load(profileId: String): SavedLoginCredential? = credentials[profileId]
        override fun save(profileId: String, credential: SavedLoginCredential) {
            if (failSave) error("storage failure")
            credentials[profileId] = credential
        }
        override fun remove(profileId: String) {
            if (failRemoval) error("storage failure")
            credentials.remove(profileId)
        }
    }
}

private fun profile(id: String, address: String, active: Boolean): ServerProfile {
    val baseUrl = (ServerBaseUrl.parse(address) as ServerBaseUrlParseResult.Valid).baseUrl
    return ServerProfile(id, id, baseUrl, "identity-$id", active, TlsMode.SystemTrust)
}

private fun ServerProfile.toSnapshot() = ServerProfileSnapshot(
    id = id,
    displayName = displayName,
    baseUrl = baseUrl.value,
    serverIdentity = serverIdentity,
    isActive = isActive,
    tlsMode = tlsMode,
)

private fun authenticated(profile: ServerProfile) = AppSession.Authenticated(
    profile = profile,
    identity = SessionIdentity(
        userId = "reader",
        email = "reader@example.com",
        displayName = "Reader",
        namespace = PrivateDataNamespace(profile.serverIdentity, "reader", 1),
    ),
    authorization = Authorization(
        isAdmin = false,
        canManageSystem = false,
        allLibraryScopes = true,
        libraryIds = emptySet(),
        canViewManualImports = false,
        authorizationVersion = 1,
    ),
)
