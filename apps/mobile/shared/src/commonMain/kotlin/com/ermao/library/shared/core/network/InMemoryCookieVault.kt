package com.ermao.library.shared.core.network

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class InMemoryCookieVault : CookieVault {
    private val mutex = Mutex()
    private val cookiesByProfile = mutableMapOf<String, List<PersistedCookie>>()

    override suspend fun load(profileId: String): List<PersistedCookie> = mutex.withLock {
        cookiesByProfile[profileId].orEmpty()
    }

    override suspend fun mutate(
        profileId: String,
        transform: (List<PersistedCookie>) -> List<PersistedCookie>,
    ): List<PersistedCookie> = CookieMutationCoordinator.withProfileLock(profileId) {
        mutex.withLock {
            transform(cookiesByProfile[profileId].orEmpty()).toList().also { cookies ->
                cookiesByProfile[profileId] = cookies
            }
        }
    }

    override suspend fun clear(profileId: String) {
        CookieMutationCoordinator.withProfileLock(profileId) {
            mutex.withLock {
                cookiesByProfile.remove(profileId)
            }
        }
    }
}
