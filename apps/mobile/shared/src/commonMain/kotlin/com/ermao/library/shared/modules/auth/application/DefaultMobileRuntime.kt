package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.network.CookieVault
import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.modules.auth.NavigationDirective
import com.ermao.library.shared.modules.auth.Observation
import com.ermao.library.shared.modules.auth.RuntimeOperationResult
import com.ermao.library.shared.modules.auth.SessionObserver
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.EpochMillisClock
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.auth.domain.SystemEpochMillisClock
import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord
import com.ermao.library.shared.modules.servers.ProfileIdGenerator
import com.ermao.library.shared.modules.servers.RandomProfileIdGenerator
import com.ermao.library.shared.modules.servers.application.DuplicateServerIdentityException
import com.ermao.library.shared.modules.servers.application.ServerProbe
import com.ermao.library.shared.modules.servers.application.ServerProbeResult
import com.ermao.library.shared.modules.servers.application.ServerProfileRepository
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.servers.domain.toSnapshot
import kotlinx.coroutines.CancellationException

/**
 * Platform facade for the bootstrap gate. Business work is delegated to the server probe,
 * authentication gateway and repositories; no transport wire crosses here.
 */
class DefaultMobileRuntime(
    private val profileRepository: ServerProfileRepository,
    private val cookieVault: CookieVault,
    private val verifiedSessionRepository: VerifiedSessionRepository,
    private val serverProbe: ServerProbe,
    private val authGateway: AuthGateway,
    private val clock: EpochMillisClock = SystemEpochMillisClock,
    private val profileIdGenerator: ProfileIdGenerator = RandomProfileIdGenerator(),
) : MobileRuntime {
    private val observers = mutableSetOf<SessionObserver>()
    private var lastConnectionDraft: ServerConnectionDraft? = null
    private var cachedProfiles = emptyList<ServerProfile>()

    override var currentSession: AppSession = AppSession.NoServer
        private set

    override val serverProfiles: List<ServerProfileSnapshot>
        get() = cachedProfiles.map(ServerProfile::toSnapshot)

    override fun observeSession(observer: SessionObserver): Observation {
        observers += observer
        observer.onSessionChanged(currentSession)
        return Observation { observers -= observer }
    }

    override suspend fun start(): RuntimeOperationResult = storageGuard {
        reloadProfiles()
        val profile = cachedProfiles.singleOrNull(ServerProfile::isActive)
        if (profile == null) {
            transition(AppSession.NoServer)
            success("NO_ACTIVE_SERVER", NavigationDirective.ShowServerProfiles)
        } else restoreSavedProfile(profile)
    }

    override suspend fun connectServer(command: ServerConnectionDraft): RuntimeOperationResult {
        lastConnectionDraft = command
        val sessionBeforeConnect = currentSession
        val parsed = ServerBaseUrl.parse(command.rawBaseUrl) as? ServerBaseUrlParseResult.Valid
            ?: return failConnection(command, invalidServerAddress())
        val provisional = ServerProfile(
            id = profileIdGenerator.generate(),
            displayName = command.displayName.trim().ifEmpty { parsed.baseUrl.origin },
            baseUrl = parsed.baseUrl,
            serverIdentity = "pending",
            isActive = false,
            tlsMode = command.tlsMode,
        )
        transition(AppSession.CheckingServer(command))
        return when (val probe = serverProbe.probe(provisional)) {
            is ServerProbeResult.Failure -> handleProbeFailure(command, probe.error)
            is ServerProbeResult.Compatible -> storageGuard {
                if (cachedProfiles.any { it.serverIdentity == probe.serverIdentity }) {
                    transition(AppSession.ServerConnectionFailed(command, com.ermao.library.shared.modules.auth.domain.ServerConnectionFailureCode.ProtocolViolation))
                    return@storageGuard failure(AppError(AppErrorKind.Conflict, "SERVER_ALREADY_SAVED"))
                }
                val profile = provisional.copy(serverIdentity = probe.serverIdentity, isActive = true)
                val previousActiveId = cachedProfiles.singleOrNull(ServerProfile::isActive)?.id
                when (val resolution = preflightGate(profile)) {
                    is GateResolution.Failed -> {
                        transition(AppSession.ServerConnectionFailed(command, com.ermao.library.shared.modules.auth.domain.ServerConnectionFailureCode.Unavailable))
                        failure(resolution.error)
                    }
                    else -> commitNewProfile(profile, resolution, previousActiveId, sessionBeforeConnect)
                }
            }
        }
    }

    override suspend fun editServer(
        profileId: String,
        command: ServerConnectionDraft,
    ): RuntimeOperationResult {
        val existing = findProfile(profileId) ?: return unknownProfile(profileId)
        val parsed = ServerBaseUrl.parse(command.rawBaseUrl) as? ServerBaseUrlParseResult.Valid
            ?: return failure(invalidServerAddress())
        val candidate = existing.copy(
            displayName = command.displayName.trim().ifEmpty { parsed.baseUrl.origin },
            baseUrl = parsed.baseUrl,
            tlsMode = command.tlsMode,
        )
        return when (val probe = serverProbe.probe(candidate)) {
            is ServerProbeResult.Failure -> failure(probe.error)
            is ServerProbeResult.Compatible -> {
                if (probe.serverIdentity != existing.serverIdentity) {
                    return failure(AppError(AppErrorKind.Conflict, "SERVER_IDENTITY_CHANGED"))
                }
                storageGuard {
                    try {
                        profileRepository.upsert(candidate)
                        if (candidate.baseUrl != existing.baseUrl) {
                            cookieVault.clear(profileId)
                            verifiedSessionRepository.removeSession(profileId)
                        }
                        reloadProfiles()
                        if (candidate.isActive) restore(candidate)
                        else success("SERVER_UPDATED")
                    } catch (cancelled: CancellationException) {
                        profileRepository.upsert(existing)
                        reloadProfiles()
                        throw cancelled
                    } catch (error: Exception) {
                        profileRepository.upsert(existing)
                        reloadProfiles()
                        throw error
                    }
                }
            }
        }
    }

    override suspend fun switchServer(profileId: String): RuntimeOperationResult {
        val target = findProfile(profileId) ?: return unknownProfile(profileId)
        if (target.isActive) return success("SERVER_ALREADY_ACTIVE")
        val previousSession = currentSession
        val candidate = target.copy(isActive = false)
        return when (val probe = serverProbe.probe(candidate)) {
            is ServerProbeResult.Failure -> {
                transition(previousSession)
                failure(probe.error)
            }
            is ServerProbeResult.Compatible -> {
                if (probe.serverIdentity != target.serverIdentity) {
                    transition(previousSession)
                    return failure(AppError(AppErrorKind.ProtocolViolation, "SERVER_IDENTITY_CHANGED"))
                }
                when (val resolution = preflightGate(target)) {
                    is GateResolution.Failed -> {
                        transition(previousSession)
                        failure(resolution.error)
                    }
                    else -> commitServerSwitch(
                        target = target,
                        resolution = resolution,
                        previousSession = previousSession,
                    )
                }
            }
        }
    }

    override suspend fun removeServer(profileId: String): RuntimeOperationResult {
        val profile = findProfile(profileId) ?: return unknownProfile(profileId)
        return storageGuard {
            cookieVault.clear(profileId)
            verifiedSessionRepository.removeSession(profileId)
            profileRepository.remove(profileId)
            reloadProfiles()
            if (profile.isActive) transition(AppSession.NoServer)
            success("SERVER_REMOVED", NavigationDirective.ShowServerProfiles)
        }
    }

    override suspend fun restoreSystemTrust(profileId: String): RuntimeOperationResult {
        val profile = findProfile(profileId) ?: return unknownProfile(profileId)
        val updated = profile.copy(tlsMode = TlsMode.SystemTrust)
        return storageGuard {
            profileRepository.upsert(updated)
            cookieVault.clear(profileId)
            verifiedSessionRepository.removeSession(profileId)
            reloadProfiles()
            if (updated.isActive) restore(updated)
            else success("SYSTEM_TRUST_RESTORED")
        }
    }

    override suspend fun acceptInsecureTls(): RuntimeOperationResult {
        val draft = (currentSession as? AppSession.TlsRisk)?.draft
            ?: return failure(AppError(AppErrorKind.InvalidRequest, "TLS_CONFIRMATION_NOT_PENDING"))
        val existing = cachedProfiles.singleOrNull(ServerProfile::isActive)?.takeIf {
            it.baseUrl.value == draft.rawBaseUrl
        }
        val insecureDraft = draft.copy(tlsMode = TlsMode.InsecureSkipAllValidation)
        return if (existing == null) connectServer(insecureDraft) else editServer(existing.id, insecureDraft)
    }

    override suspend fun retry(): RuntimeOperationResult {
        val draft = when (val session = currentSession) {
            is AppSession.ServerConnectionFailed -> session.draft
            is AppSession.IncompatibleServer -> session.draft
            is AppSession.TlsRisk -> session.draft
            else -> lastConnectionDraft
        }
        if (draft != null && currentProfile() == null) return connectServer(draft)
        return refreshCurrentSession()
    }

    override suspend fun login(email: String, password: String): RuntimeOperationResult {
        val profile = currentProfile() ?: return noActiveServer()
        val previousIdentity = lastKnownIdentity()
        transition(AppSession.Authenticating(profile))
        return when (val result = authGateway.login(profile, email.trim(), password)) {
            is ApiResult.Success -> verifyAfterAuthentication(profile, previousIdentity)
            is ApiResult.Failure -> handleLoginFailure(profile, email.trim(), result.error)
        }
    }

    override suspend fun loginToServer(
        baseUrl: String,
        email: String,
        password: String,
    ): RuntimeOperationResult = loginToServer(
        baseUrl = baseUrl,
        email = email,
        password = password,
        tlsMode = TlsMode.SystemTrust,
    )

    override suspend fun loginToServerAcceptingInsecureTls(
        baseUrl: String,
        email: String,
        password: String,
    ): RuntimeOperationResult = loginToServer(
        baseUrl = baseUrl,
        email = email,
        password = password,
        tlsMode = TlsMode.InsecureSkipAllValidation,
    )

    override suspend fun setupInitialAdmin(
        name: String,
        email: String,
        password: String,
        locale: String,
    ): RuntimeOperationResult {
        val profile = currentProfile() ?: return noActiveServer()
        val sessionBeforeSetup = currentSession
        val normalizedName = name.trim()
        val validation = validateSetup(normalizedName, email, password, locale)
        if (validation != null) return failure(validation)
        transition(AppSession.SettingUp(profile))
        return when (
            val result = authGateway.setupInitialAdmin(
                profile,
                normalizedName,
                email.trim(),
                password,
                locale,
            )
        ) {
            is ApiResult.Success -> verifyAndCommitAfterSetup(profile, sessionBeforeSetup)
            is ApiResult.Failure -> if (result.error.kind == AppErrorKind.Conflict) {
                when (val status = authGateway.setupStatus(profile)) {
                    is ApiResult.Success -> if (status.value) {
                        transition(AppSession.SignedOut(profile))
                        success("SETUP_ALREADY_COMPLETED")
                    } else {
                        transition(AppSession.SetupFailed(profile, result.error.code))
                        failure(result.error)
                    }
                    is ApiResult.Failure -> {
                        transition(AppSession.SetupFailed(profile, status.error.code))
                        failure(status.error)
                    }
                }
            } else {
                transition(AppSession.SetupFailed(profile, result.error.code))
                failure(result.error)
            }
        }
    }

    override suspend fun refreshCurrentSession(): RuntimeOperationResult {
        val profile = currentProfile() ?: return noActiveServer()
        return when (val result = authGateway.verifyCurrentSession(profile)) {
            is ApiResult.Success -> authenticate(profile, result.value, lastKnownIdentity())
            is ApiResult.Failure -> handleSessionFailure(profile, result.error)
        }
    }

    override suspend fun logout(): RuntimeOperationResult {
        val profile = currentProfile() ?: return noActiveServer()
        try {
            verifiedSessionRepository.removeSession(profile.id)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            return storageFailure(error.message ?: "Unable to clear the verified session")
        }
        transition(AppSession.SignedOut(profile))
        var remote: ApiResult<Unit>? = null
        var cookieFailure: Exception? = null
        try {
            remote = authGateway.logout(profile)
        } finally {
            try {
                cookieVault.clear(profile.id)
            } catch (error: Exception) {
                cookieFailure = error
            }
        }
        return when {
            cookieFailure != null -> storageFailure(
                cookieFailure.message ?: "Unable to clear local session cookie",
            )
            remote is ApiResult.Failure -> success(
                "LOGGED_OUT_REMOTE_UNCONFIRMED",
                NavigationDirective.HidePrivateShell,
            )
            else -> success("LOGGED_OUT", NavigationDirective.HidePrivateShell)
        }
    }

    override fun close() {
        observers.clear()
    }

    private suspend fun restoreSavedProfile(profile: ServerProfile): RuntimeOperationResult {
        val record = verifiedSessionRepository.load(profile.id)
        if (record == null || !record.matches(profile.id, profile.serverIdentity)) {
            if (record != null) {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
            }
            return restore(profile)
        }

        val restoredIdentity = record.toIdentity()
        transition(AppSession.Authenticated(profile, restoredIdentity, record.toAuthorization()))
        val draft = profile.toDraft()
        return when (val probe = serverProbe.probe(profile)) {
            is ServerProbeResult.Failure -> success(
                "SESSION_RESTORED_VALIDATION_DEFERRED",
                NavigationDirective.RestoreSelectedTab,
            )
            is ServerProbeResult.Compatible -> if (probe.serverIdentity != profile.serverIdentity) {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.IncompatibleServer(draft, "SERVER_IDENTITY_CHANGED"))
                failure(AppError(AppErrorKind.ProtocolViolation, "SERVER_IDENTITY_CHANGED"))
            } else {
                when (val resolution = preflightGate(profile)) {
                    is GateResolution.Failed -> success(
                        "SESSION_RESTORED_VALIDATION_DEFERRED",
                        NavigationDirective.RestoreSelectedTab,
                    )
                    GateResolution.SetupRequired -> success(
                        "SESSION_RESTORED_VALIDATION_DEFERRED",
                        NavigationDirective.RestoreSelectedTab,
                    )
                    else -> {
                        applyGateResolution(profile, resolution)
                        when (resolution) {
                            is GateResolution.Authenticated -> success(
                                "AUTHENTICATED",
                                resolution.navigationDirective,
                            )
                            GateResolution.SetupRequired -> error("Handled above")
                            is GateResolution.SignedOut -> failure(resolution.error)
                            is GateResolution.AccountDisabled -> success(
                                "ACCOUNT_DISABLED",
                                NavigationDirective.HidePrivateShell,
                            )
                            is GateResolution.Failed -> error("Handled above")
                        }
                    }
                }
            }
        }
    }

    private suspend fun restore(profile: ServerProfile): RuntimeOperationResult {
        val draft = profile.toDraft()
        transition(AppSession.CheckingServer(draft))
        return when (val probe = serverProbe.probe(profile)) {
            is ServerProbeResult.Failure -> handleSavedProbeFailure(profile, draft, probe.error)
            is ServerProbeResult.Compatible -> if (probe.serverIdentity != profile.serverIdentity) {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.IncompatibleServer(draft, "SERVER_IDENTITY_CHANGED"))
                failure(AppError(AppErrorKind.ProtocolViolation, "SERVER_IDENTITY_CHANGED"))
            } else {
                resolveGate(profile, activateBeforeTransition = false)
            }
        }
    }

    private suspend fun loginToServer(
        baseUrl: String,
        email: String,
        password: String,
        tlsMode: TlsMode,
    ): RuntimeOperationResult {
        reloadProfiles()
        val parsed = ServerBaseUrl.parse(baseUrl) as? ServerBaseUrlParseResult.Valid
            ?: return failConnection(
                ServerConnectionDraft("", baseUrl, tlsMode),
                invalidServerAddress(),
            )
        val normalizedEmail = email.trim()
        val draft = ServerConnectionDraft(
            displayName = parsed.baseUrl.hostName,
            rawBaseUrl = parsed.baseUrl.value,
            tlsMode = tlsMode,
        )
        lastConnectionDraft = draft
        val previousSession = currentSession
        val previousActiveId = cachedProfiles.singleOrNull(ServerProfile::isActive)?.id
        val matchingByAddress = cachedProfiles.firstOrNull { it.baseUrl == parsed.baseUrl }
        val provisional = matchingByAddress?.copy(tlsMode = tlsMode) ?: ServerProfile(
            id = profileIdGenerator.generate(),
            displayName = parsed.baseUrl.hostName,
            baseUrl = parsed.baseUrl,
            serverIdentity = "pending",
            isActive = false,
            tlsMode = tlsMode,
        )
        transition(AppSession.CheckingServer(draft))
        return when (val probe = serverProbe.probe(provisional)) {
            is ServerProbeResult.Failure -> handleProbeFailure(draft, probe.error)
            is ServerProbeResult.Compatible -> {
                if (matchingByAddress != null && matchingByAddress.serverIdentity != probe.serverIdentity) {
                    transition(AppSession.IncompatibleServer(draft, "SERVER_IDENTITY_CHANGED"))
                    return failure(AppError(AppErrorKind.ProtocolViolation, "SERVER_IDENTITY_CHANGED"))
                }
                val existingProfile = matchingByAddress
                    ?: cachedProfiles.firstOrNull { it.serverIdentity == probe.serverIdentity }
                val candidate = (existingProfile ?: provisional).copy(
                    displayName = parsed.baseUrl.hostName,
                    baseUrl = parsed.baseUrl,
                    serverIdentity = probe.serverIdentity,
                    isActive = true,
                    tlsMode = tlsMode,
                )
                when (val setup = authGateway.setupStatus(candidate)) {
                    is ApiResult.Failure -> handleProbeFailure(draft, setup.error)
                    is ApiResult.Success -> if (!setup.value) {
                        transition(AppSession.SetupRequired(candidate))
                        success("SETUP_REQUIRED")
                    } else {
                        authenticateAndCommitProfile(
                            candidate = candidate,
                            existingProfile = existingProfile,
                            email = normalizedEmail,
                            password = password,
                            previousActiveId = previousActiveId,
                            previousSession = previousSession,
                        )
                    }
                }
            }
        }
    }

    private suspend fun authenticateAndCommitProfile(
        candidate: ServerProfile,
        existingProfile: ServerProfile?,
        email: String,
        password: String,
        previousActiveId: String?,
        previousSession: AppSession,
    ): RuntimeOperationResult {
        transition(AppSession.Authenticating(candidate))
        return when (val loginResult = authGateway.login(candidate, email, password)) {
            is ApiResult.Failure -> {
                cookieVault.clear(candidate.id)
                transitionLoginFailure(candidate, email, loginResult.error)
                failure(loginResult.error)
            }
            is ApiResult.Success -> when (val verified = authGateway.verifyCurrentSession(candidate)) {
                is ApiResult.Failure -> {
                    cookieVault.clear(candidate.id)
                    transitionLoginFailure(candidate, email, verified.error)
                    failure(verified.error)
                }
                is ApiResult.Success -> storageGuard {
                    try {
                        profileRepository.upsert(candidate)
                        reloadProfiles()
                        authenticate(activeProfile(candidate.id), verified.value, lastKnownIdentity())
                    } catch (cancelled: CancellationException) {
                        compensateProfileCommit(candidate.id, existingProfile, previousActiveId, previousSession)
                        throw cancelled
                    } catch (error: Exception) {
                        compensateProfileCommit(candidate.id, existingProfile, previousActiveId, previousSession)
                        throw error
                    }
                }
            }
        }
    }

    private suspend fun transitionLoginFailure(
        candidate: ServerProfile,
        email: String,
        error: AppError,
    ) {
        when {
            error.kind == AppErrorKind.Unauthorized -> transition(
                AppSession.LoginFailed(candidate, email, "INVALID_CREDENTIALS"),
            )
            error.code == "ACCOUNT_DISABLED" -> transition(
                AppSession.AccountDisabled(candidate, email),
            )
            else -> transition(AppSession.LoginFailed(candidate, email, error.code))
        }
    }

    private suspend fun verifyAndCommitAfterSetup(
        profile: ServerProfile,
        previousSession: AppSession,
    ): RuntimeOperationResult = when (val verified = authGateway.verifyCurrentSession(profile)) {
        is ApiResult.Failure -> {
            transition(AppSession.SetupFailed(profile, verified.error.code))
            failure(verified.error)
        }
        is ApiResult.Success -> {
            val existingProfile = cachedProfiles.firstOrNull { it.id == profile.id }
            val previousActiveId = cachedProfiles.singleOrNull(ServerProfile::isActive)?.id
            storageGuard {
                try {
                    profileRepository.upsert(profile.copy(isActive = true))
                    reloadProfiles()
                    authenticate(activeProfile(profile.id), verified.value, previousIdentity = null)
                } catch (cancelled: CancellationException) {
                    compensateProfileCommit(profile.id, existingProfile, previousActiveId, previousSession)
                    throw cancelled
                } catch (error: Exception) {
                    compensateProfileCommit(profile.id, existingProfile, previousActiveId, previousSession)
                    throw error
                }
            }
        }
    }

    private suspend fun resolveGate(
        profile: ServerProfile,
        activateBeforeTransition: Boolean,
    ): RuntimeOperationResult = when (val resolution = preflightGate(profile)) {
        is GateResolution.Failed -> handleSessionFailure(profile, resolution.error)
        else -> {
            if (activateBeforeTransition) profileRepository.activate(profile.id)
            applyGateResolution(profile, resolution)
            when (resolution) {
                is GateResolution.Authenticated -> success("AUTHENTICATED", resolution.navigationDirective)
                GateResolution.SetupRequired -> success("SETUP_REQUIRED")
                is GateResolution.SignedOut -> failure(resolution.error)
                is GateResolution.AccountDisabled -> success("ACCOUNT_DISABLED", NavigationDirective.HidePrivateShell)
                is GateResolution.Failed -> error("Handled above")
            }
        }
    }

    private suspend fun commitNewProfile(
        profile: ServerProfile,
        resolution: GateResolution,
        previousActiveId: String?,
        previousSession: AppSession,
    ): RuntimeOperationResult = storageGuard {
        try {
            profileRepository.upsert(profile)
            reloadProfiles()
            applyGateResolution(activeProfile(profile.id), resolution)
            when (resolution) {
                is GateResolution.Authenticated -> success("AUTHENTICATED", resolution.navigationDirective)
                GateResolution.SetupRequired -> success("SETUP_REQUIRED")
                is GateResolution.SignedOut -> failure(resolution.error)
                is GateResolution.AccountDisabled -> success("ACCOUNT_DISABLED", NavigationDirective.HidePrivateShell)
                is GateResolution.Failed -> error("A failed gate cannot be committed")
            }
        } catch (cancelled: CancellationException) {
            compensateNewProfile(profile.id, previousActiveId, previousSession)
            throw cancelled
        } catch (error: Exception) {
            compensateNewProfile(profile.id, previousActiveId, previousSession)
            throw error
        }
    }

    private suspend fun commitServerSwitch(
        target: ServerProfile,
        resolution: GateResolution,
        previousSession: AppSession,
    ): RuntimeOperationResult {
        val previousActiveId = cachedProfiles.singleOrNull(ServerProfile::isActive)?.id
        return storageGuard {
            try {
                profileRepository.activate(target.id)
                reloadProfiles()
                applyGateResolution(activeProfile(target.id), resolution)
                success("SERVER_SWITCHED", NavigationDirective.ResetAllStacksHome)
            } catch (cancelled: CancellationException) {
                compensateActivation(previousActiveId, previousSession)
                throw cancelled
            } catch (error: Exception) {
                compensateActivation(previousActiveId, previousSession)
                throw error
            }
        }
    }

    private suspend fun compensateNewProfile(
        newProfileId: String,
        previousActiveId: String?,
        previousSession: AppSession,
    ) {
        runCatching { cookieVault.clear(newProfileId) }
        runCatching { verifiedSessionRepository.removeSession(newProfileId) }
        runCatching { profileRepository.remove(newProfileId) }
        if (previousActiveId != null) runCatching { profileRepository.activate(previousActiveId) }
        reloadProfiles()
        transition(previousSession)
    }

    private suspend fun compensateProfileCommit(
        candidateId: String,
        existingProfile: ServerProfile?,
        previousActiveId: String?,
        previousSession: AppSession,
    ) {
        runCatching { cookieVault.clear(candidateId) }
        runCatching { verifiedSessionRepository.removeSession(candidateId) }
        if (existingProfile == null) {
            runCatching { profileRepository.remove(candidateId) }
        } else {
            runCatching { profileRepository.upsert(existingProfile) }
        }
        if (previousActiveId != null && previousActiveId != candidateId) {
            runCatching { profileRepository.activate(previousActiveId) }
        }
        reloadProfiles()
        transition(previousSession)
    }

    private suspend fun compensateActivation(
        previousActiveId: String?,
        previousSession: AppSession,
    ) {
        if (previousActiveId != null) profileRepository.activate(previousActiveId)
        reloadProfiles()
        transition(previousSession)
    }

    private suspend fun preflightGate(profile: ServerProfile): GateResolution =
        when (val setup = authGateway.setupStatus(profile)) {
            is ApiResult.Failure -> GateResolution.Failed(setup.error)
            is ApiResult.Success -> if (!setup.value) {
                GateResolution.SetupRequired
            } else {
                when (val me = authGateway.verifyCurrentSession(profile)) {
                    is ApiResult.Success -> GateResolution.Authenticated(me.value, NavigationDirective.ResetAllStacksHome)
                    is ApiResult.Failure -> when {
                        me.error.kind == AppErrorKind.Unauthorized -> GateResolution.SignedOut(me.error)
                        me.error.code == "ACCOUNT_DISABLED" -> GateResolution.AccountDisabled(lastKnownIdentity()?.email)
                        else -> GateResolution.Failed(me.error)
                    }
                }
            }
        }

    private suspend fun applyGateResolution(profile: ServerProfile, resolution: GateResolution) {
        when (resolution) {
            GateResolution.SetupRequired -> {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.SetupRequired(profile))
            }
            is GateResolution.SignedOut -> {
                val previousIdentity = lastKnownIdentity()
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.SessionExpired(profile, previousIdentity))
            }
            is GateResolution.Authenticated -> authenticate(profile, resolution.session, lastKnownIdentity())
            is GateResolution.AccountDisabled -> {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.AccountDisabled(profile, resolution.email.orEmpty()))
            }
            is GateResolution.Failed -> Unit
        }
    }

    private suspend fun verifyAfterAuthentication(
        profile: ServerProfile,
        previousIdentity: SessionIdentity?,
    ): RuntimeOperationResult = when (val verified = authGateway.verifyCurrentSession(profile)) {
        is ApiResult.Success -> authenticate(profile, verified.value, previousIdentity)
        is ApiResult.Failure -> handleSessionFailure(profile, verified.error)
    }

    private suspend fun authenticate(
        profile: ServerProfile,
        verified: VerifiedSession,
        previousIdentity: SessionIdentity?,
    ): RuntimeOperationResult {
        val now = clock.now()
        verifiedSessionRepository.save(
            VerifiedSessionRecord.from(
                profileId = profile.id,
                identity = verified.identity,
                authorization = verified.authorization,
                validatedAtEpochMillis = now,
            ),
        )
        transition(AppSession.Authenticated(profile, verified.identity, verified.authorization))
        val directive = when {
            previousIdentity == null -> NavigationDirective.ResetAllStacksHome
            previousIdentity.namespace == verified.identity.namespace -> NavigationDirective.RestoreSelectedTab
            previousIdentity.namespace.serverIdentity == verified.identity.namespace.serverIdentity &&
                previousIdentity.namespace.userId == verified.identity.namespace.userId ->
                NavigationDirective.RevalidatePrivateShell
            else -> NavigationDirective.ResetAllStacksHome
        }
        return success("AUTHENTICATED", directive)
    }

    private suspend fun handleLoginFailure(
        profile: ServerProfile,
        email: String,
        error: AppError,
    ): RuntimeOperationResult {
        when {
            error.code == "SETUP_REQUIRED" -> transition(AppSession.SetupRequired(profile))
            error.kind == AppErrorKind.Unauthorized -> transition(
                AppSession.LoginFailed(profile, email, "INVALID_CREDENTIALS"),
            )
            error.code == "ACCOUNT_DISABLED" -> {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.AccountDisabled(profile, email))
            }
            else -> transition(AppSession.LoginFailed(profile, email, error.code))
        }
        return failure(error)
    }

    private suspend fun handleSessionFailure(
        profile: ServerProfile,
        error: AppError,
    ): RuntimeOperationResult {
        val previousIdentity = lastKnownIdentity()
        when {
            error.code == "ACCOUNT_DISABLED" -> {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.AccountDisabled(profile, previousIdentity?.email.orEmpty()))
            }
            error.kind == AppErrorKind.Unauthorized -> {
                verifiedSessionRepository.removeSession(profile.id)
                cookieVault.clear(profile.id)
                transition(AppSession.SessionExpired(profile, previousIdentity))
            }
            currentSession !is AppSession.Authenticated -> transition(AppSession.SignedOut(profile))
        }
        return failure(error)
    }

    private suspend fun handleSavedProbeFailure(
        profile: ServerProfile,
        draft: ServerConnectionDraft,
        error: AppError,
    ): RuntimeOperationResult = when {
        error.kind == AppErrorKind.TlsFailure && profile.tlsMode == TlsMode.SystemTrust -> {
            transition(AppSession.TlsRisk(draft, "TLS_SYSTEM_TRUST_FAILED"))
            failure(error)
        }
        error.kind == AppErrorKind.ProtocolViolation -> {
            transition(AppSession.IncompatibleServer(draft, error.code))
            failure(error)
        }
        else -> handleSessionFailure(profile, error)
    }

    private fun handleProbeFailure(
        draft: ServerConnectionDraft,
        error: AppError,
    ): RuntimeOperationResult {
        if (error.kind == AppErrorKind.TlsFailure && draft.tlsMode == TlsMode.SystemTrust) {
            transition(AppSession.TlsRisk(draft, "TLS_SYSTEM_TRUST_FAILED"))
        } else if (error.kind == AppErrorKind.ProtocolViolation) {
            transition(AppSession.IncompatibleServer(draft, error.code))
        } else {
            transition(AppSession.ServerConnectionFailed(draft, com.ermao.library.shared.modules.auth.domain.ServerConnectionFailureCode.Unavailable))
        }
        return failure(error)
    }

    private fun validateSetup(
        name: String,
        email: String,
        password: String,
        locale: String,
    ): AppError? {
        val violations = buildMap {
            if (name.isBlank()) put("name", listOf("REQUIRED"))
            else if (name.length > 40) put("name", listOf("TOO_LONG"))
            if (email.isBlank()) put("email", listOf("REQUIRED"))
            if (password.length < 10) put("password", listOf("TOO_SHORT"))
            else if (password.length > 128) put("password", listOf("TOO_LONG"))
            if (locale !in setOf("zh-CN", "en-US")) put("locale", listOf("UNSUPPORTED"))
        }
        return violations.takeIf { it.isNotEmpty() }?.let {
            AppError(AppErrorKind.Validation, "VALIDATION", fieldErrors = it)
        }
    }

    private suspend fun reloadProfiles() {
        cachedProfiles = profileRepository.profiles().sortedWith(
            compareByDescending<ServerProfile> { it.isActive }.thenBy { it.displayName.lowercase() },
        )
    }

    private suspend fun findProfile(profileId: String): ServerProfile? {
        if (cachedProfiles.isEmpty()) reloadProfiles()
        return cachedProfiles.firstOrNull { it.id == profileId }
    }

    private fun activeProfile(profileId: String): ServerProfile =
        cachedProfiles.first { it.id == profileId }.copy(isActive = true)

    private fun currentProfile(): ServerProfile? = when (val session = currentSession) {
        is AppSession.SetupRequired -> session.profile
        is AppSession.SettingUp -> session.profile
        is AppSession.SetupFailed -> session.profile
        is AppSession.SignedOut -> session.profile
        is AppSession.Authenticating -> session.profile
        is AppSession.LoginFailed -> session.profile
        is AppSession.AccountDisabled -> session.profile
        is AppSession.Authenticated -> session.profile
        is AppSession.SessionExpired -> session.profile
        else -> cachedProfiles.singleOrNull(ServerProfile::isActive)
    }

    private fun lastKnownIdentity(): SessionIdentity? = when (val session = currentSession) {
        is AppSession.Authenticated -> session.identity
        is AppSession.SessionExpired -> session.lastKnownIdentity
        else -> null
    }

    private fun transition(session: AppSession) {
        currentSession = session
        observers.toList().forEach { it.onSessionChanged(session) }
    }

    private suspend fun storageGuard(block: suspend () -> RuntimeOperationResult): RuntimeOperationResult = try {
        block()
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (duplicate: DuplicateServerIdentityException) {
        failure(AppError(AppErrorKind.Conflict, "SERVER_ALREADY_SAVED"))
    } catch (error: Exception) {
        storageFailure(error.message ?: "Mobile storage failure")
    }

    private fun failConnection(draft: ServerConnectionDraft, error: AppError): RuntimeOperationResult {
        transition(AppSession.ServerConnectionFailed(draft, com.ermao.library.shared.modules.auth.domain.ServerConnectionFailureCode.InvalidAddress))
        return failure(error)
    }

    private fun noActiveServer() = failure(AppError(AppErrorKind.InvalidRequest, "NO_ACTIVE_SERVER"))

    private fun unknownProfile(profileId: String) = failure(
        AppError(AppErrorKind.NotFoundOrUnavailable, "SERVER_PROFILE_NOT_FOUND", parameters = mapOf("profileId" to profileId)),
    )

    private fun invalidServerAddress() = AppError(AppErrorKind.InvalidRequest, "INVALID_SERVER_ADDRESS")

    private fun storageFailure(message: String) = failure(
        AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE", message),
    )

    private fun success(
        code: String,
        directive: NavigationDirective = NavigationDirective.KeepCurrentStacks,
    ) = RuntimeOperationResult.Success(code, directive)

    private fun failure(error: AppError) = RuntimeOperationResult.Failure(error)

    private fun ServerProfile.toDraft() = ServerConnectionDraft(displayName, baseUrl.value, tlsMode)

    private sealed interface GateResolution {
        data object SetupRequired : GateResolution
        data class SignedOut(val error: AppError) : GateResolution
        data class Authenticated(
            val session: VerifiedSession,
            val navigationDirective: NavigationDirective,
        ) : GateResolution
        data class AccountDisabled(val email: String?) : GateResolution
        data class Failed(val error: AppError) : GateResolution
    }
}
