package com.ermao.library.features.administrativesettings

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
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
class AdministrativeSettingsViewModelTest {
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
    fun allRetiredCapabilityAndChildRoutesAreRejectedByMobileAvailabilityGuard() {
        val retired = listOf(
            AdministrativeSettingsRoute.LibrarySources,
            AdministrativeSettingsRoute.LibrarySourceEdit(),
            AdministrativeSettingsRoute.ServerDirectory(purpose = ServerDirectoryPurpose.CreateLibrarySource),
            AdministrativeSettingsRoute.ImportTasks,
            AdministrativeSettingsRoute.ImportTaskDetail("task"),
            AdministrativeSettingsRoute.ImportScanJobs,
            AdministrativeSettingsRoute.ImportScanJob("scan"),
            AdministrativeSettingsRoute.ImportPreferences,
            AdministrativeSettingsRoute.OrganizeQueue,
            AdministrativeSettingsRoute.OrganizeCandidates,
            AdministrativeSettingsRoute.OrganizeRuns,
            AdministrativeSettingsRoute.RecognitionPolicy,
            AdministrativeSettingsRoute.LibraryOperations,
            AdministrativeSettingsRoute.CategoryGovernance(),
            AdministrativeSettingsRoute.MetadataProviders,
            AdministrativeSettingsRoute.MetadataProviderEdit("provider"),
            AdministrativeSettingsRoute.Backups,
            AdministrativeSettingsRoute.DetailOrder,
            AdministrativeSettingsRoute.Health(),
        )

        assertTrue(retired.all(AdministrativeSettingsRoute::isRetiredMobileRoute))
        assertFalse(AdministrativeSettingsRoute.Users.isRetiredMobileRoute())
        assertFalse(AdministrativeSettingsRoute.Opds.isRetiredMobileRoute())
        assertFalse(AdministrativeSettingsRoute.Logs.isRetiredMobileRoute())
    }

    @Test
    fun missingCapabilityNeverCallsRepository() = runTest(dispatcher) {
        val repository = RecordingRepository()
        val viewModel = viewModel(repository, capabilities = emptySet())

        viewModel.load(AdministrativeSettingsRoute.Opds)
        advanceUntilIdle()

        assertEquals(0, repository.loads.size)
        assertEquals(AdministrativePagePhase.PermissionDenied, viewModel.states.value[AdministrativeSettingsRoute.Opds]?.phase)
    }

    @Test
    fun unauthorizedMutationRequestsReauthenticationWithoutSuccessState() = runTest(dispatcher) {
        val repository = RecordingRepository().apply {
            commandResult = AdministrativeResult.Failure(
                AdministrativeFailure(AdministrativeErrorKind.Unauthorized, "SESSION_EXPIRED"),
            )
        }
        var reauthenticationCount = 0
        val viewModel = viewModel(repository, setOf(AdministrativeCapability.ManageOpds)) { reauthenticationCount += 1 }
        val route = AdministrativeSettingsRoute.Opds
        viewModel.execute(AdministrativeCommand.SaveOpds(true, "https://example.test"))
        advanceUntilIdle()

        assertEquals(1, reauthenticationCount)
        assertEquals(AdministrativePagePhase.Failure, viewModel.states.value[route]?.phase)
        assertEquals("SESSION_EXPIRED", viewModel.states.value[route]?.failure?.code)
    }

    @Test
    fun serverForbiddenLoadBecomesPermissionStateWithoutReauthentication() = runTest(dispatcher) {
        val repository = RecordingRepository().apply {
            loadResult = AdministrativeResult.Failure(
                AdministrativeFailure(AdministrativeErrorKind.Forbidden, "ADMIN_FORBIDDEN"),
            )
        }
        var reauthenticationCount = 0
        val route = AdministrativeSettingsRoute.Opds
        val viewModel = viewModel(repository, setOf(AdministrativeCapability.ManageOpds)) { reauthenticationCount += 1 }

        viewModel.load(route)
        advanceUntilIdle()

        assertEquals(0, reauthenticationCount)
        assertEquals(AdministrativePagePhase.PermissionDenied, viewModel.states.value[route]?.phase)
        assertEquals("ADMIN_FORBIDDEN", viewModel.states.value[route]?.failure?.code)
    }

    @Test
    fun supersededLoadCannotOverwriteNewerSnapshot() = runTest(dispatcher) {
        val first = CompletableDeferred<AdministrativeResult<AdministrativePageSnapshot>>()
        val second = CompletableDeferred<AdministrativeResult<AdministrativePageSnapshot>>()
        val route = AdministrativeSettingsRoute.Opds
        val repository = object : AdministrativeSettingsRepository {
            var count = 0
            override suspend fun load(
                context: AdministrativeSettingsContext,
                route: AdministrativeSettingsRoute,
            ): AdministrativeResult<AdministrativePageSnapshot> = if (count++ == 0) first.await() else second.await()

            override suspend fun execute(
                context: AdministrativeSettingsContext,
                command: AdministrativeCommand,
            ): AdministrativeResult<AdministrativeCommandReceipt> = error("not used")
        }
        val viewModel = viewModel(repository, setOf(AdministrativeCapability.ManageOpds))
        viewModel.load(route)
        advanceUntilIdle()
        viewModel.load(route, force = true)
        advanceUntilIdle()

        second.complete(AdministrativeResult.Content(about("new")))
        advanceUntilIdle()
        first.complete(AdministrativeResult.Content(about("old")))
        advanceUntilIdle()

        assertEquals("new", (viewModel.states.value[route]?.snapshot as OpdsSnapshot).publicBaseUrl)
    }

    @Test
    fun cancelledMutationDoesNotReportSuccessOrRetainBusyState() = runTest(dispatcher) {
        val pending = CompletableDeferred<AdministrativeResult<AdministrativeCommandReceipt>>()
        val repository = object : AdministrativeSettingsRepository {
            override suspend fun load(
                context: AdministrativeSettingsContext,
                route: AdministrativeSettingsRoute,
            ) = AdministrativeResult.Content(opds("loaded"))

            override suspend fun execute(
                context: AdministrativeSettingsContext,
                command: AdministrativeCommand,
            ) = pending.await()
        }
        val route = AdministrativeSettingsRoute.Opds
        val viewModel = viewModel(repository, setOf(AdministrativeCapability.ManageOpds))
        viewModel.load(route)
        advanceUntilIdle()
        viewModel.execute(AdministrativeCommand.SaveOpds(true, "https://example.test"))
        advanceUntilIdle()

        viewModel.cancel(route)
        advanceUntilIdle()
        pending.complete(AdministrativeResult.Content(AdministrativeCommandReceipt(setOf(route))))
        advanceUntilIdle()

        assertFalse(viewModel.states.value.getValue(route).mutationInFlight)
        assertNull(viewModel.states.value.getValue(route).failure)
    }

    @Test
    fun failedOpdsSaveKeepsTheLastSavedCatalogAndCanBeRetried() = runTest(dispatcher) {
        val saved = opds("https://saved.example/base")
        val repository = RecordingRepository().apply {
            loadResult = AdministrativeResult.Content(saved)
            commandResult = AdministrativeResult.Failure(
                AdministrativeFailure(AdministrativeErrorKind.Unavailable, "NETWORK_ERROR"),
            )
        }
        val viewModel = viewModel(repository, setOf(AdministrativeCapability.ManageOpds))
        val route = AdministrativeSettingsRoute.Opds
        viewModel.load(route)
        advanceUntilIdle()
        viewModel.execute(AdministrativeCommand.SaveOpds(true, "https://new.example/base"))
        advanceUntilIdle()
        assertEquals(saved, viewModel.states.value.getValue(route).snapshot)
        assertFalse(viewModel.states.value.getValue(route).mutationInFlight)
        val updated = opds("https://new.example/base")
        repository.commandResult = AdministrativeResult.Content(AdministrativeCommandReceipt(emptySet()))
        repository.loadResult = AdministrativeResult.Content(updated)
        viewModel.execute(AdministrativeCommand.SaveOpds(true, "https://new.example/base"))
        advanceUntilIdle()
        assertEquals(updated, viewModel.states.value.getValue(route).snapshot)
        assertNull(viewModel.states.value.getValue(route).failure)
    }

    @Test
    fun opdsUsesTheUpdateResponseWithoutASecondRead() = runTest(dispatcher) {
        val saved = opds("https://books.example/base")
        val disabled = saved.copy(enabled = false, running = false, catalogUrl = "")
        val repository = RecordingRepository().apply {
            loadResult = AdministrativeResult.Content(saved)
            commandResult = AdministrativeResult.Content(AdministrativeCommandReceipt(emptySet(), updatedSnapshot = disabled))
        }
        val viewModel = viewModel(repository, setOf(AdministrativeCapability.ManageOpds))
        viewModel.load(AdministrativeSettingsRoute.Opds)
        advanceUntilIdle()
        viewModel.execute(AdministrativeCommand.SaveOpds(false, saved.publicBaseUrl))
        advanceUntilIdle()
        assertEquals(disabled, viewModel.states.value.getValue(AdministrativeSettingsRoute.Opds).snapshot)
        assertEquals(1, repository.loads.size)
    }

    @Test
    fun passwordResetRetainsEditorAndSaveInvalidatesBothListAndEditor() = runTest(dispatcher) {
        val user = AdministrativeUser("target", "Reader", "reader@example.com", UserRole.Member, true, AdministrativeLocale.ZhCn)
        val snapshot = UserEditorSnapshot(user, false, true, setOf("library-1"))
        val repository = RecordingRepository().apply { loadResult = AdministrativeResult.Content(snapshot) }
        val model = viewModel(repository, setOf(AdministrativeCapability.ManageUsers))
        val route = AdministrativeSettingsRoute.UserEdit(user.id)
        model.load(route)
        advanceUntilIdle()
        model.execute(AdministrativeCommand.ResetUserPassword(user.id, "1234567890"))
        advanceUntilIdle()
        assertEquals(1, repository.loads.size)
        assertEquals(snapshot, model.states.value.getValue(route).snapshot)
        repository.commandResult = AdministrativeResult.Failure(AdministrativeFailure(AdministrativeErrorKind.Conflict, "EMAIL_IN_USE"))
        val draft = UserDraft(user.id, "Changed", user.email, user.role, true, null, false, true, setOf("library-1"), user.locale)
        model.execute(AdministrativeCommand.SaveUser(draft))
        advanceUntilIdle()
        assertEquals(snapshot, model.states.value.getValue(route).snapshot)
        assertEquals("EMAIL_IN_USE", model.states.value.getValue(route).failure?.code)
        repository.commandResult = AdministrativeResult.Content(AdministrativeCommandReceipt(setOf(AdministrativeSettingsRoute.Users)))
        model.execute(AdministrativeCommand.SaveUser(draft))
        advanceUntilIdle()
        assertNull(model.states.value[route])
        assertNull(model.states.value[AdministrativeSettingsRoute.Users])
    }

    @Test
    fun nativeUserDraftPreservesManualAndLibraryGrants() {
        val draft = UserDraft(null, "Reader", "reader@example.com", UserRole.Member, true, "1234567890",
            true, true, setOf("library-1", "library-2"), AdministrativeLocale.ZhCn)
        val shared = draft.sharedDraft()
        assertTrue(shared.isValid(true))
        assertTrue(shared.forCreation().canViewManualImports)
        assertEquals(listOf("library-1", "library-2"), shared.forCreation().libraryIds)
        assertEquals(shared.forCreation().libraryIds, shared.forUpdate().libraryIds)
    }

    private fun viewModel(
        repository: AdministrativeSettingsRepository,
        capabilities: Set<AdministrativeCapability>,
        reauthenticate: () -> Unit = {},
    ) = AdministrativeSettingsViewModel(
        repository,
        AdministrativeSettingsContext("profile-1", "server-1", "user-1", AdministrativeLocale.EnUs, capabilities),
        AdministrativeSettingsSideEffects(reauthenticate),
    )

    private inner class RecordingRepository : AdministrativeSettingsRepository {
        val loads = mutableListOf<AdministrativeSettingsRoute>()
        var commandResult: AdministrativeResult<AdministrativeCommandReceipt> =
            AdministrativeResult.Content(AdministrativeCommandReceipt(emptySet()))
        var loadResult: AdministrativeResult<AdministrativePageSnapshot> = AdministrativeResult.Content(about("1.0"))

        override suspend fun load(
            context: AdministrativeSettingsContext,
            route: AdministrativeSettingsRoute,
        ): AdministrativeResult<AdministrativePageSnapshot> {
            loads += route
            return loadResult
        }

        override suspend fun execute(
            context: AdministrativeSettingsContext,
            command: AdministrativeCommand,
        ): AdministrativeResult<AdministrativeCommandReceipt> = commandResult
    }

    private fun about(version: String) = opds(version)

    private fun opds(version: String) = OpdsSnapshot(
        enabled = true,
        running = true,
        publicBaseUrl = version,
        catalogUrl = "$version/opds",
    )
}
