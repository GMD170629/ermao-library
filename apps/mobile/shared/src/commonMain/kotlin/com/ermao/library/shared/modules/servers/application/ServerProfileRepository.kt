package com.ermao.library.shared.modules.servers.application

import com.ermao.library.shared.modules.servers.domain.ServerProfile
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class DuplicateServerIdentityException(
    val serverIdentity: String,
) : IllegalArgumentException("A server profile with this server identity already exists")

class UnknownServerProfileException(
    val profileId: String,
) : IllegalArgumentException("Unknown server profile")

interface ServerProfileRepository {
    suspend fun profiles(): List<ServerProfile>

    suspend fun activeProfile(): ServerProfile?

    suspend fun upsert(profile: ServerProfile)

    suspend fun activate(profileId: String)

    suspend fun remove(profileId: String)
}

class InMemoryServerProfileRepository : ServerProfileRepository {
    private val mutex = Mutex()
    private var stored = emptyList<ServerProfile>()

    override suspend fun profiles(): List<ServerProfile> = mutex.withLock { stored }

    override suspend fun activeProfile(): ServerProfile? = mutex.withLock {
        stored.singleOrNull(ServerProfile::isActive)
    }

    override suspend fun upsert(profile: ServerProfile) = mutex.withLock {
        ensureUniqueServerIdentity(stored, profile)
        val replacing = stored.filterNot { it.id == profile.id }
        stored = if (profile.isActive) {
            replacing.map { it.copy(isActive = false) } + profile
        } else {
            replacing + profile
        }
    }

    override suspend fun activate(profileId: String) = mutex.withLock {
        if (stored.none { it.id == profileId }) throw UnknownServerProfileException(profileId)
        stored = stored.map { it.copy(isActive = it.id == profileId) }
    }

    override suspend fun remove(profileId: String) = mutex.withLock {
        stored = stored.filterNot { it.id == profileId }
    }
}

internal fun ensureUniqueServerIdentity(
    profiles: List<ServerProfile>,
    candidate: ServerProfile,
) {
    if (profiles.any { it.id != candidate.id && it.serverIdentity == candidate.serverIdentity }) {
        throw DuplicateServerIdentityException(candidate.serverIdentity)
    }
}
