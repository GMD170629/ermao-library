package com.ermao.library.features.administrativesettings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class AdministrativeSettingsViewModel(
    private val repository: AdministrativeSettingsRepository,
    private val context: AdministrativeSettingsContext,
    private val sideEffects: AdministrativeSettingsSideEffects,
) : ViewModel() {
    private val mutableStates = MutableStateFlow<Map<AdministrativeSettingsRoute, AdministrativeScreenState>>(emptyMap())
    val states: StateFlow<Map<AdministrativeSettingsRoute, AdministrativeScreenState>> = mutableStates.asStateFlow()

    private val mutableEffects = MutableSharedFlow<AdministrativeSettingsEffect>(extraBufferCapacity = 8)
    val effects: SharedFlow<AdministrativeSettingsEffect> = mutableEffects.asSharedFlow()

    private val loadJobs = mutableMapOf<AdministrativeSettingsRoute, Job>()
    private val mutationJobs = mutableMapOf<AdministrativeSettingsRoute, Job>()
    private val generations = mutableMapOf<AdministrativeSettingsRoute, Long>()
    private val generationSource = AtomicLong(0L)

    fun load(route: AdministrativeSettingsRoute, force: Boolean = false) {
        if (route.isRetiredMobileRoute()) {
            update(route) { AdministrativeScreenState(phase = AdministrativePagePhase.PermissionDenied) }
            return
        }
        if (!context.capabilities.contains(route.requiredCapability())) {
            update(route) { AdministrativeScreenState(phase = AdministrativePagePhase.PermissionDenied) }
            return
        }
        val current = states.value[route]
        if (!force && current?.phase in setOf(AdministrativePagePhase.Loading, AdministrativePagePhase.Content)) return
        loadJobs.remove(route)?.cancel()
        val generation = nextGeneration(route)
        update(route) { (current ?: AdministrativeScreenState()).copy(phase = AdministrativePagePhase.Loading, failure = null) }
        loadJobs[route] = viewModelScope.launch {
            try {
                when (val result = repository.load(context, route)) {
                    is AdministrativeResult.Content -> {
                        if (!isCurrent(route, generation)) return@launch
                        if (result.value.supports(route)) {
                            update(route) {
                                AdministrativeScreenState(
                                    phase = AdministrativePagePhase.Content,
                                    snapshot = result.value,
                                    mutationInFlight = it.mutationInFlight,
                                )
                            }
                        } else {
                            setFailure(route, invalidPayloadFailure())
                        }
                    }
                    is AdministrativeResult.Failure -> {
                        if (isCurrent(route, generation)) setFailure(route, result.error)
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (isCurrent(route, generation)) setFailure(route, transportFailure())
            } finally {
                if (loadJobs[route] === coroutineContext[Job]) loadJobs.remove(route)
            }
        }
    }

    fun poll(route: AdministrativeSettingsRoute, intervalMilliseconds: Long = 2_000L) {
        if (!route.supportsPolling() || loadJobs[route]?.isActive == true) return
        loadJobs[route] = viewModelScope.launch {
            while (true) {
                val generation = nextGeneration(route)
                when (val result = repository.load(context, route)) {
                    is AdministrativeResult.Content -> if (isCurrent(route, generation) && result.value.supports(route)) {
                        update(route) { AdministrativeScreenState(AdministrativePagePhase.Content, result.value) }
                        if (!result.value.pollingActive()) break
                    }
                    is AdministrativeResult.Failure -> if (isCurrent(route, generation)) {
                        setFailure(route, result.error, retainContent = true)
                        break
                    }
                }
                delay(intervalMilliseconds)
            }
        }
    }

    fun execute(command: AdministrativeCommand) {
        val route = command.ownerRoute
        if (route.isRetiredMobileRoute()) {
            setFailure(route, forbiddenFailure())
            return
        }
        if (!context.capabilities.contains(command.requiredCapability())) {
            setFailure(route, forbiddenFailure())
            return
        }
        if (states.value[route]?.mutationInFlight == true) return
        mutationJobs.remove(route)?.cancel()
        val generation = nextGeneration(route)
        update(route) { (it.takeUnless { state -> state.phase == AdministrativePagePhase.Idle } ?: AdministrativeScreenState()).copy(mutationInFlight = true, failure = null) }
        mutationJobs[route] = viewModelScope.launch {
            try {
                when (val result = repository.execute(context, command)) {
                    is AdministrativeResult.Content -> {
                        if (!isCurrent(route, generation)) return@launch
                        update(route) { it.copy(mutationInFlight = false, failure = null) }
                        mutableEffects.emit(AdministrativeSettingsEffect.OperationSucceeded(command.operation))
                        result.value.exportFile?.let { mutableEffects.emit(AdministrativeSettingsEffect.ExportReady(it)) }
                        val routes = result.value.invalidatedRoutes + route
                        routes.forEach { invalidated ->
                            if (invalidated != route) invalidate(invalidated)
                        }
                        load(route, force = true)
                    }
                    is AdministrativeResult.Failure -> {
                        if (!isCurrent(route, generation)) return@launch
                        setFailure(route, result.error, retainContent = true)
                        mutableEffects.emit(AdministrativeSettingsEffect.OperationFailed(command.operation, result.error))
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (!isCurrent(route, generation)) return@launch
                val failure = transportFailure()
                setFailure(route, failure, retainContent = true)
                mutableEffects.emit(AdministrativeSettingsEffect.OperationFailed(command.operation, failure))
            } finally {
                if (mutationJobs[route] === coroutineContext[Job]) mutationJobs.remove(route)
            }
        }
    }

    fun cancel(route: AdministrativeSettingsRoute) {
        loadJobs.remove(route)?.cancel()
        mutationJobs.remove(route)?.cancel()
        nextGeneration(route)
        update(route) { state ->
            state.copy(
                phase = if (state.snapshot == null) AdministrativePagePhase.Idle else AdministrativePagePhase.Content,
                mutationInFlight = false,
                failure = null,
            )
        }
    }

    fun invalidate(route: AdministrativeSettingsRoute) {
        loadJobs.remove(route)?.cancel()
        mutationJobs.remove(route)?.cancel()
        nextGeneration(route)
        mutableStates.update { it - route }
    }

    private fun nextGeneration(route: AdministrativeSettingsRoute): Long = generationSource.incrementAndGet().also {
        generations[route] = it
    }

    private fun isCurrent(route: AdministrativeSettingsRoute, generation: Long): Boolean = generations[route] == generation

    private fun setFailure(
        route: AdministrativeSettingsRoute,
        failure: AdministrativeFailure,
        retainContent: Boolean = false,
    ) {
        if (failure.kind == AdministrativeErrorKind.Unauthorized) sideEffects.requireReauthentication()
        update(route) { current ->
            val content = if (retainContent) current.snapshot else null
            AdministrativeScreenState(
                phase = if (failure.kind == AdministrativeErrorKind.Forbidden) {
                    AdministrativePagePhase.PermissionDenied
                } else {
                    AdministrativePagePhase.Failure
                },
                snapshot = content,
                failure = failure,
                mutationInFlight = false,
            )
        }
    }

    private fun update(
        route: AdministrativeSettingsRoute,
        transform: (AdministrativeScreenState) -> AdministrativeScreenState,
    ) {
        mutableStates.update { current ->
            current + (route to transform(current[route] ?: AdministrativeScreenState()))
        }
    }

    companion object {
        fun factory(
            repository: AdministrativeSettingsRepository,
            context: AdministrativeSettingsContext,
            sideEffects: AdministrativeSettingsSideEffects,
        ): ViewModelProvider.Factory = viewModelFactory {
            initializer { AdministrativeSettingsViewModel(repository, context, sideEffects) }
        }
    }
}

private fun AdministrativePageSnapshot.supports(route: AdministrativeSettingsRoute): Boolean = when (route) {
    AdministrativeSettingsRoute.Root -> this is ManagementSnapshot
    is AdministrativeSettingsRoute.EmailKindle -> this is EmailKindleSnapshot
    AdministrativeSettingsRoute.KindleQueue -> this is KindleQueueSnapshot
    AdministrativeSettingsRoute.Users -> this is UsersSnapshot
    is AdministrativeSettingsRoute.UserEdit -> this is UserEditorSnapshot
    is AdministrativeSettingsRoute.UserAccess -> this is UserAccessSnapshot
    AdministrativeSettingsRoute.LibrarySources -> this is LibrarySourcesSnapshot
    is AdministrativeSettingsRoute.LibrarySourceEdit -> this is LibrarySourceEditorSnapshot
    is AdministrativeSettingsRoute.ServerDirectory -> this is ServerDirectorySnapshot
    AdministrativeSettingsRoute.ImportTasks -> this is ImportTasksSnapshot
    is AdministrativeSettingsRoute.ImportTaskDetail -> this is ImportTaskDetailSnapshot
    AdministrativeSettingsRoute.ImportScanJobs -> this is ImportScanJobsSnapshot
    is AdministrativeSettingsRoute.ImportScanJob -> this is ImportScanJobSnapshot
    AdministrativeSettingsRoute.ImportPreferences -> this is ImportPreferencesSnapshot
    AdministrativeSettingsRoute.OrganizeQueue -> this is OrganizeQueueSnapshot
    AdministrativeSettingsRoute.OrganizeCandidates -> this is OrganizeCandidatesSnapshot
    AdministrativeSettingsRoute.OrganizeRuns -> this is OrganizeRunsSnapshot
    AdministrativeSettingsRoute.RecognitionPolicy -> this is RecognitionPolicySnapshot
    AdministrativeSettingsRoute.LibraryOperations -> this is LibraryOperationsSnapshot
    is AdministrativeSettingsRoute.CategoryGovernance -> this is CategoryGovernanceSnapshot
    AdministrativeSettingsRoute.MetadataProviders -> this is MetadataProvidersSnapshot
    is AdministrativeSettingsRoute.MetadataProviderEdit -> this is MetadataProviderEditorSnapshot
    AdministrativeSettingsRoute.Opds -> this is OpdsSnapshot
    AdministrativeSettingsRoute.Backups -> this is BackupsSnapshot
    AdministrativeSettingsRoute.DetailOrder -> this is DetailOrderSnapshot
    is AdministrativeSettingsRoute.Health -> this is HealthSnapshot
    AdministrativeSettingsRoute.Logs -> this is LogsSnapshot
}

private fun AdministrativeSettingsRoute.supportsPolling(): Boolean =
    this is AdministrativeSettingsRoute.ImportScanJob || this is AdministrativeSettingsRoute.Health

private fun AdministrativePageSnapshot.pollingActive(): Boolean = when (this) {
    is ImportScanJobSnapshot -> job.active
    is HealthSnapshot -> status == HealthStatus.Checking
    else -> false
}

private fun forbiddenFailure() = AdministrativeFailure(AdministrativeErrorKind.Forbidden, "ADMINISTRATIVE_FORBIDDEN")
private fun invalidPayloadFailure() = AdministrativeFailure(AdministrativeErrorKind.Unknown, "ADMINISTRATIVE_INVALID_PAYLOAD")
private fun transportFailure() = AdministrativeFailure(AdministrativeErrorKind.Unavailable, "ADMINISTRATIVE_UNAVAILABLE", retryable = true)
