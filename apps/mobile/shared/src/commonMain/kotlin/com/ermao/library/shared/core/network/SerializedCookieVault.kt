package com.ermao.library.shared.core.network

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import com.ermao.library.shared.core.storage.PlatformStorageException

/** Platform secure stores persist only opaque encrypted-at-rest payloads through this Swift-friendly seam. */
interface SecureCookiePayloadStore {
    @Throws(PlatformStorageException::class)
    fun load(profileId: String): String?

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

    override suspend fun load(profileId: String): List<PersistedCookie> = storageOperation("load") {
        store.load(profileId)?.let {
            json.decodeFromString(ListSerializer(PersistedCookie.serializer()), it)
        }.orEmpty()
    }

    override suspend fun save(profileId: String, cookies: List<PersistedCookie>) {
        storageOperation("save") {
            store.save(profileId, json.encodeToString(ListSerializer(PersistedCookie.serializer()), cookies))
        }
    }

    override suspend fun clear(profileId: String) {
        storageOperation("clear") { store.clear(profileId) }
    }

    private fun <T> storageOperation(action: String, block: () -> T): T = try {
        block()
    } catch (error: PlatformStorageException) {
        throw error
    } catch (error: Throwable) {
        throw PlatformStorageException("Unable to $action secure session cookies", error)
    }
}
