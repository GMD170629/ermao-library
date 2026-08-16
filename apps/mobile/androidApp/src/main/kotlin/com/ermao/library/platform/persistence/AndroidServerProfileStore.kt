package com.ermao.library.platform.persistence

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.ermao.library.shared.modules.auth.application.VerifiedSessionRepository
import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord
import com.ermao.library.shared.modules.servers.application.ServerProfileRepository
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.flow.first
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/** Stage 0 legacy wire. Kept only for one-way migration from profiles_json_v1. */
@Serializable
data class AndroidStoredServerProfile(
    val id: String,
    val displayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val isActive: Boolean,
    val tlsMode: StoredTlsMode,
)

@Serializable
private data class StoredProfilesV2(
    val schemaVersion: Int = 2,
    val activeProfileId: String? = null,
    val profiles: List<StoredProfileV2> = emptyList(),
)

@Serializable
private data class StoredProfileV2(
    val id: String,
    val displayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val tlsMode: StoredTlsMode,
)

@Serializable
enum class StoredTlsMode { SystemTrust, InsecureSkipAllValidation }

class ProfileStorageException(cause: Throwable) : IllegalStateException(
    "Server profile storage is unreadable",
    cause,
)

private val Context.serverProfilesDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "server_profiles",
)

internal val legacyProfilesPayloadKey = stringPreferencesKey("profiles_json_v1")
internal val profilesV2PayloadKey = stringPreferencesKey("server_profiles_json_v2")

class AndroidServerProfileStore(
    context: Context,
    dataStoreOverride: DataStore<Preferences>? = null,
    private val json: Json = Json {
        ignoreUnknownKeys = false
        explicitNulls = false
        encodeDefaults = true
    },
) : ServerProfileRepository, VerifiedSessionRepository {
    private val dataStore = dataStoreOverride ?: context.applicationContext.serverProfilesDataStore

    override suspend fun profiles(): List<ServerProfile> {
        migrateLegacyProfilesIfNeeded()
        return decodeV2(dataStore.data.first()).toDomainProfiles()
    }

    override suspend fun activeProfile(): ServerProfile? = profiles().singleOrNull(ServerProfile::isActive)

    override suspend fun upsert(profile: ServerProfile) {
        validate(profile.toStoredV2())
        dataStore.edit { preferences ->
            val state = decodeForWrite(preferences)
            val profiles = state.profiles.filterNot { it.id == profile.id } + profile.toStoredV2()
            val activeId = if (profile.isActive) profile.id else state.activeProfileId
            saveV2(preferences, StoredProfilesV2(activeProfileId = activeId, profiles = profiles))
        }
    }

    override suspend fun activate(profileId: String) {
        require(profileId.isNotBlank()) { "profileId must not be blank" }
        dataStore.edit { preferences ->
            val state = decodeForWrite(preferences)
            require(state.profiles.any { it.id == profileId }) { "Unknown server profile" }
            saveV2(preferences, state.copy(activeProfileId = profileId))
        }
    }

    override suspend fun load(profileId: String): VerifiedSessionRecord? = dataStore.data.first()[VERIFIED_SESSIONS]
        ?.let(::decodeVerifiedSessions)
        ?.get(profileId)

    override suspend fun save(record: VerifiedSessionRecord) {
        dataStore.edit { preferences ->
            val existing = preferences[VERIFIED_SESSIONS]?.let(::decodeVerifiedSessions).orEmpty()
            preferences[VERIFIED_SESSIONS] = json.encodeToString(existing + (record.profileId to record))
        }
    }

    /** Removing a server profile also removes its verified session in the same DataStore transaction. */
    override suspend fun remove(profileId: String) {
        require(profileId.isNotBlank()) { "profileId must not be blank" }
        dataStore.edit { preferences ->
            val state = decodeForWrite(preferences)
            val remaining = state.profiles.filterNot { it.id == profileId }
            saveV2(
                preferences,
                state.copy(
                    activeProfileId = state.activeProfileId?.takeUnless { it == profileId },
                    profiles = remaining,
                ),
            )
            val sessions = preferences[VERIFIED_SESSIONS]?.let(::decodeVerifiedSessions).orEmpty() - profileId
            preferences[VERIFIED_SESSIONS] = json.encodeToString(sessions)
        }
    }

    /** Verified-session cleanup must never remove the owning server profile. */
    override suspend fun removeSession(profileId: String) {
        require(profileId.isNotBlank()) { "profileId must not be blank" }
        dataStore.edit { preferences ->
            val sessions = preferences[VERIFIED_SESSIONS]?.let(::decodeVerifiedSessions).orEmpty() - profileId
            preferences[VERIFIED_SESSIONS] = json.encodeToString(sessions)
        }
    }

    private suspend fun migrateLegacyProfilesIfNeeded() {
        dataStore.edit { preferences ->
            if (preferences[PROFILES_V2] != null || preferences[LEGACY_PROFILES] == null) return@edit
            saveV2(preferences, decodeLegacy(preferences))
        }
    }

    private fun decodeForWrite(preferences: Preferences): StoredProfilesV2 =
        if (preferences[PROFILES_V2] != null) decodeV2(preferences) else decodeLegacy(preferences)

    private fun decodeV2(preferences: Preferences): StoredProfilesV2 {
        val encoded = preferences[PROFILES_V2] ?: return StoredProfilesV2()
        return storageDecode {
            json.decodeFromString<StoredProfilesV2>(encoded).also(::validate)
        }
    }

    private fun decodeLegacy(preferences: Preferences): StoredProfilesV2 {
        val encoded = preferences[LEGACY_PROFILES] ?: return StoredProfilesV2()
        return storageDecode {
            val legacy = json.decodeFromString<List<AndroidStoredServerProfile>>(encoded)
            legacy.forEach(::validate)
            require(legacy.count(AndroidStoredServerProfile::isActive) <= 1) {
                "Multiple active server profiles"
            }
            StoredProfilesV2(
                activeProfileId = legacy.singleOrNull(AndroidStoredServerProfile::isActive)?.id,
                profiles = legacy.map { it.toStoredV2() },
            ).also(::validate)
        }
    }

    private fun saveV2(preferences: androidx.datastore.preferences.core.MutablePreferences, state: StoredProfilesV2) {
        validate(state)
        preferences[PROFILES_V2] = json.encodeToString(state)
        preferences.remove(LEGACY_PROFILES)
    }

    private fun decodeVerifiedSessions(payload: String): Map<String, VerifiedSessionRecord> = storageDecode {
        json.decodeFromString<Map<String, VerifiedSessionRecord>>(payload).also { records ->
            require(records.all { (profileId, record) -> profileId == record.profileId }) {
                "Verified-session profile key mismatch"
            }
        }
    }

    private fun validate(state: StoredProfilesV2) {
        require(state.schemaVersion == PROFILE_SCHEMA_VERSION) { "Unsupported profile schema" }
        require(state.profiles.map(StoredProfileV2::id).distinct().size == state.profiles.size) {
            "Duplicate profile id"
        }
        state.profiles.forEach(::validate)
        require(state.activeProfileId == null || state.profiles.any { it.id == state.activeProfileId }) {
            "Active profile does not exist"
        }
    }

    private fun validate(profile: StoredProfileV2) {
        require(profile.id.isNotBlank()) { "profile id must not be blank" }
        require(profile.displayName.isNotBlank()) { "profile display name must not be blank" }
        require(ServerBaseUrl.parse(profile.baseUrl) is ServerBaseUrlParseResult.Valid) {
            "profile base URL is invalid"
        }
        require(profile.serverIdentity.isNotBlank()) { "profile server identity must not be blank" }
    }

    private fun validate(profile: AndroidStoredServerProfile) = validate(profile.toStoredV2())

    private inline fun <T> storageDecode(block: () -> T): T = try {
        block()
    } catch (failure: IllegalArgumentException) {
        throw ProfileStorageException(failure)
    } catch (failure: SerializationException) {
        throw ProfileStorageException(failure)
    }

    private companion object {
        const val PROFILE_SCHEMA_VERSION = 2
        val LEGACY_PROFILES = legacyProfilesPayloadKey
        val PROFILES_V2 = profilesV2PayloadKey
        val VERIFIED_SESSIONS = stringPreferencesKey("verified_sessions_json_v1")
    }
}

private fun StoredProfilesV2.toDomainProfiles(): List<ServerProfile> = profiles.map { stored ->
    val parsed = ServerBaseUrl.parse(stored.baseUrl)
    check(parsed is ServerBaseUrlParseResult.Valid) { "Stored server base URL is invalid" }
    ServerProfile(
        id = stored.id,
        displayName = stored.displayName,
        baseUrl = parsed.baseUrl,
        serverIdentity = stored.serverIdentity,
        isActive = stored.id == activeProfileId,
        tlsMode = stored.tlsMode.toDomain(),
    )
}

private fun ServerProfile.toStoredV2() = StoredProfileV2(
    id = id,
    displayName = displayName,
    baseUrl = baseUrl.value,
    serverIdentity = serverIdentity,
    tlsMode = tlsMode.toStored(),
)

private fun AndroidStoredServerProfile.toStoredV2() = StoredProfileV2(
    id = id,
    displayName = displayName,
    baseUrl = baseUrl,
    serverIdentity = serverIdentity,
    tlsMode = tlsMode,
)

private fun StoredTlsMode.toDomain() = when (this) {
    StoredTlsMode.SystemTrust -> TlsMode.SystemTrust
    StoredTlsMode.InsecureSkipAllValidation -> TlsMode.InsecureSkipAllValidation
}

private fun TlsMode.toStored() = when (this) {
    TlsMode.SystemTrust -> StoredTlsMode.SystemTrust
    TlsMode.InsecureSkipAllValidation -> StoredTlsMode.InsecureSkipAllValidation
}
