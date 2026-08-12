package com.ermao.library.shared.core.network

import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.core.storage.PlatformStoragePayload
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/** Platform secure stores persist only opaque encrypted-at-rest payloads through this Swift-friendly seam. */
interface SecureCookiePayloadStore {
    @Throws(PlatformStorageException::class)
    fun loadCookiePayload(profileId: String): PlatformStoragePayload

    @Throws(PlatformStorageException::class)
    fun save(profileId: String, payload: String)

    @Throws(PlatformStorageException::class)
    fun clear(profileId: String)
}

class SerializedCookieVault(
    private val store: SecureCookiePayloadStore,
) : CookieVault {
    private val json = Json {
        ignoreUnknownKeys = false
        explicitNulls = false
    }

    override suspend fun load(profileId: String): List<PersistedCookie> =
        CookieMutationCoordinator.withProfileLock(profileId) { loadUncoordinated(profileId) }

    override suspend fun mutate(
        profileId: String,
        transform: (List<PersistedCookie>) -> List<PersistedCookie>,
    ): List<PersistedCookie> =
        CookieMutationCoordinator.withProfileLock(profileId) {
            transform(loadUncoordinated(profileId)).toList().also { cookies ->
                saveUncoordinated(profileId, cookies)
            }
        }

    override suspend fun clear(profileId: String) {
        CookieMutationCoordinator.withProfileLock(profileId) {
            storageOperation("clear") { store.clear(profileId) }
        }
    }

    private fun loadUncoordinated(profileId: String): List<PersistedCookie> = storageOperation("load") {
        store.loadCookiePayload(profileId).value?.let {
            json.decodeFromString(ListSerializer(PersistedCookie.serializer()), it)
        }.orEmpty()
    }

    private fun saveUncoordinated(
        profileId: String,
        cookies: List<PersistedCookie>,
    ) {
        storageOperation("save") {
            store.save(profileId, json.encodeToString(ListSerializer(PersistedCookie.serializer()), cookies))
        }
    }

    private fun <T> storageOperation(action: String, block: () -> T): T = try {
        block()
    } catch (error: PlatformStorageException) {
        throw error
    } catch (error: Throwable) {
        throw PlatformStorageException("Unable to $action secure session cookies", error)
    }
}
