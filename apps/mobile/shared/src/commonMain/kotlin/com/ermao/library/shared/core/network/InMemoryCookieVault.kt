package com.ermao.library.shared.core.network

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class InMemoryCookieVault : CookieVault {
    private val mutex = Mutex()
    private val cookiesByProfile = mutableMapOf<String, List<PersistedCookie>>()

    override suspend fun load(profileId: String): List<PersistedCookie> = mutex.withLock {
        cookiesByProfile[profileId].orEmpty()
    }

    override suspend fun save(profileId: String, cookies: List<PersistedCookie>) {
        mutex.withLock {
            cookiesByProfile[profileId] = cookies.toList()
        }
    }

    override suspend fun clear(profileId: String) {
        mutex.withLock {
            cookiesByProfile.remove(profileId)
        }
    }
}
