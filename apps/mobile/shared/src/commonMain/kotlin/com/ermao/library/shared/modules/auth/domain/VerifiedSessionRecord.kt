package com.ermao.library.shared.modules.auth.domain

import kotlinx.serialization.Serializable

@Serializable
data class VerifiedSessionRecord(
    val profileId: String,
    val serverIdentity: String,
    val userId: String,
    val email: String,
    val displayName: String,
    val authorizationVersion: Long,
    val isAdmin: Boolean,
    val canManageSystem: Boolean,
    val allLibraryScopes: Boolean,
    val canViewManualImports: Boolean,
    val libraryIds: List<String>,
    val lastValidatedAtEpochMillis: Long,
    val avatarUrl: String? = null,
    val locale: String? = null,
) {
    fun belongsToProfile(profileId: String): Boolean = this.profileId == profileId

    fun toIdentity(): SessionIdentity = SessionIdentity(
        userId = userId,
        email = email,
        displayName = displayName,
        avatarUrl = avatarUrl,
        locale = locale,
        namespace = PrivateDataNamespace(serverIdentity, userId, authorizationVersion),
    )

    fun toAuthorization(): Authorization = Authorization(
        isAdmin = isAdmin,
        canManageSystem = canManageSystem,
        allLibraryScopes = allLibraryScopes,
        libraryIds = libraryIds.toSet(),
        canViewManualImports = canViewManualImports,
        authorizationVersion = authorizationVersion,
    )

    companion object {
        fun from(
            profileId: String,
            identity: SessionIdentity,
            authorization: Authorization,
            validatedAtEpochMillis: Long,
        ): VerifiedSessionRecord = VerifiedSessionRecord(
            profileId = profileId,
            serverIdentity = identity.namespace.serverIdentity,
            userId = identity.userId,
            email = identity.email,
            displayName = identity.displayName,
            avatarUrl = identity.avatarUrl,
            locale = identity.locale,
            authorizationVersion = authorization.authorizationVersion,
            isAdmin = authorization.isAdmin,
            canManageSystem = authorization.canManageSystem,
            allLibraryScopes = authorization.allLibraryScopes,
            canViewManualImports = authorization.canViewManualImports,
            libraryIds = authorization.libraryIds.sorted(),
            lastValidatedAtEpochMillis = validatedAtEpochMillis,
        )
    }
}

fun interface EpochMillisClock {
    fun now(): Long
}

object SystemEpochMillisClock : EpochMillisClock {
    override fun now(): Long = platformEpochMillis()
}

internal expect fun platformEpochMillis(): Long
