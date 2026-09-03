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
