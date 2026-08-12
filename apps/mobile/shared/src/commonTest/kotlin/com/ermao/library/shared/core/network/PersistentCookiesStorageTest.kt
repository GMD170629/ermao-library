package com.ermao.library.shared.core.network

import com.ermao.library.shared.core.storage.PlatformStoragePayload
import io.ktor.http.Cookie
import io.ktor.http.Url
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking

class PersistentCookiesStorageTest {
    @Test
    fun restoresHostOnlyCookiesAgainstTheirOriginalHostAndIsolatesProfiles() = runBlocking {
        val vault = InMemoryCookieVault()
        val origin = Url("https://books.example/library/api/auth/login")
        val now = currentEpochMillis()
        val first = PersistentCookiesStorage("profile-a", vault) { now }
        first.addCookie(origin, Cookie("session", "secret", path = "/library", maxAge = 60))

        val restored = PersistentCookiesStorage("profile-a", vault) { now + 1_000 }
        assertEquals("secret", restored.get(Url("https://books.example/library/api/auth/me")).single().value)
        assertTrue(restored.get(Url("https://other.example/library/api/auth/me")).isEmpty())
        assertTrue(restored.get(Url("https://books.example/outside")).isEmpty())
        assertTrue(PersistentCookiesStorage("profile-b", vault) { now + 1_000 }.get(origin).isEmpty())
    }

    @Test
    fun maxAgeUsesAnAbsoluteExpiryAcrossRestarts() = runBlocking {
        val vault = InMemoryCookieVault()
        val origin = Url("https://books.example/api/auth/login")
        val now = currentEpochMillis()
        PersistentCookiesStorage("profile", vault) { now }
            .addCookie(origin, Cookie("session", "secret", maxAge = 10))

        assertTrue(PersistentCookiesStorage("profile", vault) { now + 10_001 }.get(origin).isEmpty())
    }

    @Test
    fun domainCookieCanReachASubdomainButNotAnUnrelatedDomain() = runBlocking {
        val vault = InMemoryCookieVault()
        val storage = PersistentCookiesStorage("profile", vault) { currentEpochMillis() }
        storage.addCookie(
            Url("https://example.com/api"),
            Cookie("locale", "zh-CN", domain = ".example.com", path = "/"),
        )
        assertEquals(1, storage.get(Url("https://books.example.com/api")).size)
        assertTrue(storage.get(Url("https://example.net/api")).isEmpty())
    }

    @Test
    fun separatelyComposedClientsAtomicallyMergeConcurrentCookieUpdates() = runBlocking {
        val store = MemoryCookiePayloadStore()
        val firstVault = SerializedCookieVault(store)
        val secondVault = SerializedCookieVault(store)
        val origin = Url("https://books.example/api/auth/me")
        val now = currentEpochMillis()
        val sessionClient = PersistentCookiesStorage("profile", firstVault) { now }
        val localeClient = PersistentCookiesStorage("profile", secondVault) { now }
        sessionClient.get(origin)
        localeClient.get(origin)

        coroutineScope {
            listOf(
                async {
                    sessionClient.addCookie(
                        origin,
                        Cookie("shuku_session", "refreshed-session", path = "/", httpOnly = true),
                    )
                },
                async {
                    localeClient.addCookie(
                        origin,
                        Cookie("shuku_locale", "en-US", path = "/"),
                    )
                },
            ).awaitAll()
        }

        assertEquals(
            mapOf(
                "shuku_locale" to "en-US",
                "shuku_session" to "refreshed-session",
            ),
            SerializedCookieVault(store).load("profile").associate { cookie -> cookie.name to cookie.value },
        )
    }

    @Test
    fun clearingFromAnotherVaultCannotBeUndoneByAStaleClientAggregate() = runBlocking {
        val store = MemoryCookiePayloadStore()
        val firstVault = SerializedCookieVault(store)
        val secondVault = SerializedCookieVault(store)
        val origin = Url("https://books.example/api/auth/me")
        val now = currentEpochMillis()
        val staleClient = PersistentCookiesStorage("profile", firstVault) { now }
        staleClient.addCookie(origin, Cookie("shuku_session", "old-session", path = "/"))

        secondVault.clear("profile")
        staleClient.addCookie(origin, Cookie("shuku_locale", "zh-CN", path = "/"))

        val persisted = firstVault.load("profile")
        assertEquals(listOf("shuku_locale"), persisted.map(PersistedCookie::name))
        assertEquals("zh-CN", persisted.single().value)
    }

    private class MemoryCookiePayloadStore : SecureCookiePayloadStore {
        private val payloads = mutableMapOf<String, String>()

        override fun loadCookiePayload(profileId: String) = PlatformStoragePayload(payloads[profileId])

        override fun save(profileId: String, payload: String) {
            payloads[profileId] = payload
        }

        override fun clear(profileId: String) {
            payloads.remove(profileId)
        }
    }
}
