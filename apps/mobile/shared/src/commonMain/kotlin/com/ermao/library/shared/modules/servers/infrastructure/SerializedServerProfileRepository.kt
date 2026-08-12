package com.ermao.library.shared.modules.servers.infrastructure

import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.servers.application.ServerProfileRepository
import com.ermao.library.shared.modules.servers.application.UnknownServerProfileException
import com.ermao.library.shared.modules.servers.application.ensureUniqueServerIdentity
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

interface ServerProfilePayloadStore {
    @Throws(PlatformStorageException::class)
    fun loadProfilesPayload(): PlatformStoragePayload

    @Throws(PlatformStorageException::class)
    fun saveProfiles(payload: String)
}

class ServerProfileStorageException(
    val reasonCode: String,
    cause: Throwable? = null,
) : IllegalStateException("Server profile storage is invalid: $reasonCode", cause)

class SerializedServerProfileRepository(
    private val store: ServerProfilePayloadStore,
) : ServerProfileRepository {
    private val mutex = Mutex()
    private val json = Json {
        explicitNulls = false
        ignoreUnknownKeys = false
    }

    override suspend fun profiles(): List<ServerProfile> = mutex.withLock {
        loadAndMigrate().profiles
    }

    override suspend fun activeProfile(): ServerProfile? = mutex.withLock {
        loadAndMigrate().profiles.singleOrNull(ServerProfile::isActive)
    }

    override suspend fun upsert(profile: ServerProfile) = mutex.withLock {
        val aggregate = loadAndMigrate()
        ensureValidProfile(profile)
        ensureUniqueServerIdentity(aggregate.profiles, profile)
        val replacing = aggregate.profiles.filterNot { it.id == profile.id }
        val updatedProfiles = replacing + profile.copy(isActive = profile.isActive)
        save(
            StoredAggregate(
                activeProfileId = if (profile.isActive) {
                    profile.id
                } else {
                    aggregate.activeProfileId.takeUnless { it == profile.id }
                },
                profiles = updatedProfiles,
            ),
        )
    }

    override suspend fun activate(profileId: String) = mutex.withLock {
        val aggregate = loadAndMigrate()
        if (aggregate.profiles.none { it.id == profileId }) {
            throw UnknownServerProfileException(profileId)
        }
        save(aggregate.copy(activeProfileId = profileId))
    }

    override suspend fun remove(profileId: String) = mutex.withLock {
        val aggregate = loadAndMigrate()
        save(
            StoredAggregate(
                activeProfileId = aggregate.activeProfileId.takeUnless { it == profileId },
                profiles = aggregate.profiles.filterNot { it.id == profileId },
            ),
        )
    }

    private fun loadAndMigrate(): StoredAggregate {
        val payload = store.loadProfilesPayload().value ?: return StoredAggregate(null, emptyList())
        val root = try {
            json.parseToJsonElement(payload)
        } catch (error: SerializationException) {
            throw ServerProfileStorageException("MALFORMED_JSON", error)
        }
        return when (root) {
            is JsonArray -> decodeLegacy(root).also(::save)
            is JsonObject -> decodeVersioned(root)
            else -> throw ServerProfileStorageException("INVALID_ROOT")
        }
    }

    private fun decodeLegacy(root: JsonArray): StoredAggregate {
        val wires = decodeOrFail<List<LegacyServerProfileWire>>(root.toString())
        if (wires.count(LegacyServerProfileWire::isActive) > 1) {
            throw ServerProfileStorageException("MULTIPLE_ACTIVE_PROFILES")
        }
        val profiles = wires.map { it.toDomain(it.isActive) }
        validateStoredProfiles(profiles)
        return StoredAggregate(
            activeProfileId = profiles.singleOrNull(ServerProfile::isActive)?.id,
            profiles = profiles,
        )
    }

    private fun decodeVersioned(root: JsonObject): StoredAggregate {
        val version = (root["schemaVersion"] as? JsonPrimitive)?.intOrNull
            ?: throw ServerProfileStorageException("SCHEMA_VERSION_MISSING")
        if (version != CURRENT_SCHEMA_VERSION) {
            throw ServerProfileStorageException("UNSUPPORTED_SCHEMA_VERSION")
        }
        val wire = decodeOrFail<ServerProfilesAggregateWire>(root.toString())
        val profiles = wire.profiles.map { it.toDomain(it.id == wire.activeProfileId) }
        validateStoredProfiles(profiles)
        if (wire.activeProfileId != null && profiles.none { it.id == wire.activeProfileId }) {
            throw ServerProfileStorageException("ACTIVE_PROFILE_MISSING")
        }
        return StoredAggregate(wire.activeProfileId, profiles)
    }

    private fun validateStoredProfiles(profiles: List<ServerProfile>) {
        if (profiles.map(ServerProfile::id).distinct().size != profiles.size) {
            throw ServerProfileStorageException("DUPLICATE_PROFILE_ID")
        }
        if (profiles.map(ServerProfile::serverIdentity).distinct().size != profiles.size) {
            throw ServerProfileStorageException("DUPLICATE_SERVER_IDENTITY")
        }
        profiles.forEach(::ensureValidProfile)
    }

    private fun ensureValidProfile(profile: ServerProfile) {
        if (profile.id.isBlank()) throw ServerProfileStorageException("BLANK_PROFILE_ID")
        if (profile.displayName.isBlank()) throw ServerProfileStorageException("BLANK_DISPLAY_NAME")
        if (profile.serverIdentity.isBlank()) {
            throw ServerProfileStorageException("BLANK_SERVER_IDENTITY")
        }
    }

    private fun save(aggregate: StoredAggregate) {
        validateStoredProfiles(aggregate.profiles)
        if (aggregate.activeProfileId != null && aggregate.profiles.none { it.id == aggregate.activeProfileId }) {
            throw ServerProfileStorageException("ACTIVE_PROFILE_MISSING")
        }
        store.saveProfiles(
            json.encodeToString(
                ServerProfilesAggregateWire(
                    schemaVersion = CURRENT_SCHEMA_VERSION,
                    activeProfileId = aggregate.activeProfileId,
                    profiles = aggregate.profiles.map(ServerProfileWire::fromDomain),
                ),
            ),
        )
    }

    private inline fun <reified T> decodeOrFail(payload: String): T = try {
        json.decodeFromString<T>(payload)
    } catch (error: SerializationException) {
        throw ServerProfileStorageException("INVALID_PAYLOAD", error)
    }

    private data class StoredAggregate(
        val activeProfileId: String?,
        val profiles: List<ServerProfile>,
    )

    private companion object {
        const val CURRENT_SCHEMA_VERSION = 2
    }
}

@Serializable
private data class ServerProfilesAggregateWire(
    val schemaVersion: Int,
    val activeProfileId: String? = null,
    val profiles: List<ServerProfileWire>,
)

@Serializable
private data class ServerProfileWire(
    val id: String,
    val displayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val tlsMode: TlsMode,
) {
    fun toDomain(isActive: Boolean): ServerProfile = ServerProfile(
        id = id,
        displayName = displayName,
        baseUrl = parseBaseUrl(baseUrl),
        serverIdentity = serverIdentity,
        isActive = isActive,
        tlsMode = tlsMode,
    )

    companion object {
        fun fromDomain(profile: ServerProfile): ServerProfileWire = ServerProfileWire(
            id = profile.id,
            displayName = profile.displayName,
            baseUrl = profile.baseUrl.value,
            serverIdentity = profile.serverIdentity,
            tlsMode = profile.tlsMode,
        )
    }
}

@Serializable
private data class LegacyServerProfileWire(
    val id: String,
    val displayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val isActive: Boolean,
    val tlsMode: TlsMode,
) {
    fun toDomain(isActive: Boolean): ServerProfile = ServerProfile(
        id = id,
        displayName = displayName,
        baseUrl = parseBaseUrl(baseUrl),
        serverIdentity = serverIdentity,
        isActive = isActive,
        tlsMode = tlsMode,
    )
}

private fun parseBaseUrl(rawValue: String): ServerBaseUrl =
    (ServerBaseUrl.parse(rawValue) as? ServerBaseUrlParseResult.Valid)?.baseUrl
        ?: throw ServerProfileStorageException("INVALID_BASE_URL")
