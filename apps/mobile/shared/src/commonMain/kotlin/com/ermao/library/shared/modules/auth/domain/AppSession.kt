package com.ermao.library.shared.modules.auth.domain

import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft

sealed interface AppSession {
    data object NoServer : AppSession

    data class CheckingServer(val draft: ServerConnectionDraft) : AppSession

    data class ServerConnectionFailed(
        val draft: ServerConnectionDraft,
        val failureCode: ServerConnectionFailureCode,
    ) : AppSession

    data class TlsRisk(
        val draft: ServerConnectionDraft,
        val reasonCode: String,
    ) : AppSession

    data class SetupRequired(val profile: ServerProfile) : AppSession

    data class SettingUp(val profile: ServerProfile) : AppSession

    data class SetupFailed(
        val profile: ServerProfile,
        val failureCode: String,
    ) : AppSession

    data class SignedOut(val profile: ServerProfile) : AppSession

    data class Authenticating(val profile: ServerProfile) : AppSession

    data class LoginFailed(
        val profile: ServerProfile,
        val email: String,
        val failureCode: String,
    ) : AppSession

    data class AccountDisabled(
        val profile: ServerProfile,
        val email: String,
    ) : AppSession

    data class Authenticated(
        val profile: ServerProfile,
        val identity: SessionIdentity,
        val authorization: Authorization,
    ) : AppSession

    data class SessionExpired(
        val profile: ServerProfile,
        val lastKnownIdentity: SessionIdentity? = null,
    ) : AppSession

    data class IncompatibleServer(
        val draft: ServerConnectionDraft,
        val reasonCode: String,
    ) : AppSession
}

enum class AppSessionKind {
    NoServer,
    CheckingServer,
    ServerConnectionFailed,
    TlsRisk,
    SetupRequired,
    SettingUp,
    SetupFailed,
    SignedOut,
    Authenticating,
    LoginFailed,
    AccountDisabled,
    Authenticated,
    SessionExpired,
    IncompatibleServer,
}

/** A deliberately flat and immutable projection that is stable for Swift. */
data class AppSessionSnapshot(
    val kind: AppSessionKind,
    val profileId: String? = null,
    val profileDisplayName: String? = null,
    val profileBaseUrl: String? = null,
    val profileServerIdentity: String? = null,
    val profileTlsMode: com.ermao.library.shared.modules.servers.domain.TlsMode? = null,
    val draftDisplayName: String? = null,
    val draftBaseUrl: String? = null,
    val reasonCode: String? = null,
    val userId: String? = null,
    val userEmail: String? = null,
    val userDisplayName: String? = null,
    val userAvatarUrl: String? = null,
    val userLocale: String? = null,
    val isAdmin: Boolean = false,
    val canManageSystem: Boolean = false,
    val allLibraryScopes: Boolean = false,
    val canViewManualImports: Boolean = false,
    val authorizationVersion: Long? = null,
    val libraryIds: List<String> = emptyList(),
)

fun AppSession.toSnapshot(): AppSessionSnapshot = when (this) {
    AppSession.NoServer -> AppSessionSnapshot(AppSessionKind.NoServer)
    is AppSession.CheckingServer -> draftSnapshot(AppSessionKind.CheckingServer, draft)
    is AppSession.ServerConnectionFailed -> draftSnapshot(
        AppSessionKind.ServerConnectionFailed,
        draft,
        failureCode.stableCode,
    )
    is AppSession.TlsRisk -> draftSnapshot(AppSessionKind.TlsRisk, draft, reasonCode)
    is AppSession.IncompatibleServer -> draftSnapshot(AppSessionKind.IncompatibleServer, draft, reasonCode)
    is AppSession.SetupRequired -> profileSnapshot(AppSessionKind.SetupRequired, profile)
    is AppSession.SettingUp -> profileSnapshot(AppSessionKind.SettingUp, profile)
    is AppSession.SetupFailed -> profileSnapshot(AppSessionKind.SetupFailed, profile).copy(
        reasonCode = failureCode,
    )
    is AppSession.SignedOut -> profileSnapshot(AppSessionKind.SignedOut, profile)
    is AppSession.Authenticating -> profileSnapshot(AppSessionKind.Authenticating, profile)
    is AppSession.LoginFailed -> profileSnapshot(AppSessionKind.LoginFailed, profile).copy(
        userEmail = email,
        reasonCode = failureCode,
    )
    is AppSession.AccountDisabled -> profileSnapshot(AppSessionKind.AccountDisabled, profile).copy(
        userEmail = email,
        reasonCode = "ACCOUNT_DISABLED",
    )
    is AppSession.Authenticated -> authenticatedSnapshot(
        AppSessionKind.Authenticated,
        profile,
        identity,
        authorization,
    )
    is AppSession.SessionExpired -> profileSnapshot(
        AppSessionKind.SessionExpired,
        profile,
        lastKnownIdentity,
    )
}

private fun draftSnapshot(
    kind: AppSessionKind,
    draft: ServerConnectionDraft,
    reasonCode: String? = null,
) = AppSessionSnapshot(
    kind = kind,
    draftDisplayName = draft.displayName,
    draftBaseUrl = draft.rawBaseUrl,
    reasonCode = reasonCode,
)

private fun profileSnapshot(
    kind: AppSessionKind,
    profile: ServerProfile,
    identity: SessionIdentity? = null,
) = AppSessionSnapshot(
    kind = kind,
    profileId = profile.id,
    profileDisplayName = profile.displayName,
    profileBaseUrl = profile.baseUrl.value,
    profileServerIdentity = profile.serverIdentity,
    profileTlsMode = profile.tlsMode,
    userId = identity?.userId,
    userEmail = identity?.email,
    userDisplayName = identity?.displayName,
    userAvatarUrl = identity?.avatarUrl,
    userLocale = identity?.locale,
)

private fun authenticatedSnapshot(
    kind: AppSessionKind,
    profile: ServerProfile,
    identity: SessionIdentity,
    authorization: Authorization?,
) = profileSnapshot(kind, profile, identity).copy(
    isAdmin = authorization?.isAdmin == true,
    canManageSystem = authorization?.canManageSystem == true,
    allLibraryScopes = authorization?.allLibraryScopes == true,
    canViewManualImports = authorization?.canViewManualImports == true,
    authorizationVersion = authorization?.authorizationVersion
        ?: identity.namespace.authorizationVersion,
    libraryIds = authorization?.libraryIds?.sorted().orEmpty(),
)

private val ServerConnectionFailureCode.stableCode: String
    get() = when (this) {
        ServerConnectionFailureCode.InvalidAddress -> "INVALID_ADDRESS"
        ServerConnectionFailureCode.Unavailable -> "UNAVAILABLE"
        ServerConnectionFailureCode.ProtocolViolation -> "PROTOCOL_VIOLATION"
        ServerConnectionFailureCode.UnsupportedServer -> "UNSUPPORTED_SERVER"
    }

enum class ServerConnectionFailureCode {
    InvalidAddress,
    Unavailable,
    ProtocolViolation,
    UnsupportedServer,
}

data class SessionIdentity(
    val userId: String,
    val email: String,
    val displayName: String,
    val namespace: PrivateDataNamespace,
    val avatarUrl: String? = null,
    val locale: String? = null,
)

data class PrivateDataNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
)
