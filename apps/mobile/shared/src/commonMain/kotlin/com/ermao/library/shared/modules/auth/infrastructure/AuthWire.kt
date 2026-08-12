package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.modules.auth.domain.Authorization
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName

@Serializable
internal data class SetupStatusWire(val initialized: Boolean)

@Serializable
internal data class LoginRequestWire(val email: String, val password: String)

@Serializable
internal data class SetupRequestWire(
    val name: String,
    val email: String,
    val password: String,
    val locale: String,
)

@Serializable
internal data class LoggedOutWire(val loggedOut: Boolean)

@Serializable
internal data class SessionWire(
    val user: AuthUserWire,
    val authorization: AuthorizationWire,
    val preferences: UserPreferencesWire,
)

@Serializable
internal data class SetupSessionWire(
    val initialized: Boolean,
    val user: AuthUserWire,
    val authorization: AuthorizationWire,
    val preferences: UserPreferencesWire,
) {
    fun session(): SessionWire = SessionWire(user, authorization, preferences)
}

@Serializable
internal data class UserPreferencesWire(
    val locale: String,
    @SerialName("library.view") val libraryView: String? = null,
    @SerialName("library.sort") val librarySort: String? = null,
    @SerialName("library.sortDirection") val librarySortDirection: String? = null,
    @SerialName("audio.playbackRate") val audioPlaybackRate: Double? = null,
    @SerialName("kindle.email") val kindleEmail: String? = null,
)

@Serializable
internal data class AuthUserWire(
    val id: String,
    val email: String,
    val name: String,
    val role: String,
    val status: String,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val authzVersion: Long,
    val avatarUrl: String? = null,
    val locale: String? = null,
)

@Serializable
internal data class AuthorizationWire(
    val isAdmin: Boolean,
    val canManageSystem: Boolean,
    val allLibraryScopes: Boolean,
    val monitorFolderIds: List<String>,
    val canViewManualImports: Boolean,
    val authzVersion: Long,
)

internal fun SessionWire.toDomain(profile: ServerProfile): Pair<SessionIdentity, Authorization>? {
    val locale = preferences.locale.takeIf { it in SUPPORTED_SESSION_LOCALES } ?: return null
    if (user.locale != null && user.locale != locale) return null
    val identity = SessionIdentity(
        userId = user.id,
        email = user.email,
        displayName = user.name,
        avatarUrl = user.avatarUrl,
        locale = locale,
        namespace = PrivateDataNamespace(
            serverIdentity = profile.serverIdentity,
            userId = user.id,
            authorizationVersion = authorization.authzVersion,
        ),
    )
    val permissions = Authorization(
        isAdmin = authorization.isAdmin,
        canManageSystem = authorization.canManageSystem,
        allLibraryScopes = authorization.allLibraryScopes,
        monitorFolderIds = authorization.monitorFolderIds.toSet(),
        canViewManualImports = authorization.canViewManualImports,
        authorizationVersion = authorization.authzVersion,
    )
    return identity to permissions
}

private val SUPPORTED_SESSION_LOCALES = setOf("zh-CN", "en-US")
