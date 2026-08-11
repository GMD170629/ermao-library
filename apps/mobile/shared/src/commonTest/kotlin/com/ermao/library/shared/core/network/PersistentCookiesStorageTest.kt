package com.ermao.library.shared.core.network

import io.ktor.http.Cookie
import io.ktor.http.Url
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
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
}
