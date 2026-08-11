package com.ermao.library.bootstrap

import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.modules.auth.Observation
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.SessionObserver
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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
        val viewModel = MainViewModel(runtime)

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
        val viewModel = MainViewModel(runtime)

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
        val viewModel = MainViewModel(runtime)

        viewModel.permanentlyIgnoreTlsAndConnect()
        advanceUntilIdle()

        assertEquals(1, runtime.acceptInsecureTlsCalls)
    }

    @Test
    fun setupValidationRejectsShortAndMismatchedPasswordsBeforeRuntime() = runTest(dispatcher) {
        val runtime = FakeMobileRuntime(AppSession.NoServer)
        val viewModel = MainViewModel(runtime)
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

    private class FakeMobileRuntime(
        initialSession: AppSession,
    ) : MobileRuntime {
        private var observer: SessionObserver? = null
        override var currentSession: AppSession = initialSession
            private set
        override val serverProfiles: List<ServerProfileSnapshot> = emptyList()
        var lastConnectionDraft: ServerConnectionDraft? = null
            private set
        var acceptInsecureTlsCalls: Int = 0
            private set
        var setupCalls: Int = 0
            private set

        override fun observeSession(observer: SessionObserver): Observation {
            this.observer = observer
            return Observation { this.observer = null }
        }

        override suspend fun start(): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun connectServer(command: ServerConnectionDraft): RuntimeOperationResult {
            lastConnectionDraft = command
            return RuntimeOperationResult.Success()
        }

        override suspend fun editServer(
            profileId: String,
            command: ServerConnectionDraft,
        ): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun switchServer(profileId: String): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun removeServer(profileId: String): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun restoreSystemTrust(profileId: String): RuntimeOperationResult =
            RuntimeOperationResult.Success()

        override suspend fun acceptInsecureTls(): RuntimeOperationResult {
            acceptInsecureTlsCalls += 1
            return RuntimeOperationResult.Success()
        }

        override suspend fun retry(): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun login(email: String, password: String): RuntimeOperationResult =
            RuntimeOperationResult.Success()

        override suspend fun setupInitialAdmin(
            name: String,
            email: String,
            password: String,
            locale: String,
        ): RuntimeOperationResult {
            setupCalls += 1
            return RuntimeOperationResult.Success()
        }

        override suspend fun refreshCurrentSession(): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun enterOfflineMode(): RuntimeOperationResult = RuntimeOperationResult.Success()

        override suspend fun logout(): RuntimeOperationResult = RuntimeOperationResult.Success()

        override fun close() = Unit
    }
}
