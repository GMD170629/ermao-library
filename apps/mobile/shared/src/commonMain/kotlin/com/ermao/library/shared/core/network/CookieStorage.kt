package com.ermao.library.shared.core.network

import io.ktor.client.plugins.cookies.AcceptAllCookiesStorage
import io.ktor.client.plugins.cookies.CookiesStorage
import io.ktor.http.Cookie
import io.ktor.http.CookieEncoding
import io.ktor.http.Url
import io.ktor.util.date.GMTDate
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable

interface CookieVault {
    suspend fun load(profileId: String): List<PersistedCookie>

    suspend fun save(profileId: String, cookies: List<PersistedCookie>)

    suspend fun clear(profileId: String)
}

@Serializable
data class PersistedCookie(
    val name: String,
    val value: String,
    val encoding: String,
    val receivedAtMillis: Long,
    val effectiveExpiresAtMillis: Long?,
    val requestScheme: String,
    val requestHost: String,
    val domain: String?,
    val path: String?,
    val secure: Boolean,
    val httpOnly: Boolean,
    val extensions: Map<String, String?>,
)

internal class PersistentCookiesStorage(
    private val profileId: String,
    private val vault: CookieVault,
    private val nowMillis: () -> Long = { currentEpochMillis() },
) : CookiesStorage {
    private val mutex = Mutex()
    private val delegate = AcceptAllCookiesStorage()
    private var loaded = false
    private var persistedCookies: List<PersistedCookie> = emptyList()

    override suspend fun get(requestUrl: Url): List<Cookie> = mutex.withLock {
        ensureLoaded()
        delegate.get(requestUrl)
    }

    override suspend fun addCookie(requestUrl: Url, cookie: Cookie) {
        mutex.withLock {
            ensureLoaded()
            delegate.addCookie(requestUrl, cookie)
            val persisted = cookie.toPersisted(requestUrl, nowMillis())
            persistedCookies = persistedCookies
                .filterNot { it.sameIdentityAs(persisted) }
                .let { existing -> if (persisted.isExpired(nowMillis())) existing else existing + persisted }
                .filterNot { it.isExpired(nowMillis()) }
            vault.save(profileId, persistedCookies)
        }
    }

    override fun close() {
        delegate.close()
    }

    private suspend fun ensureLoaded() {
        if (loaded) return
        val now = nowMillis()
        persistedCookies = vault.load(profileId).filterNot { it.isExpired(now) }
        persistedCookies.forEach { persisted ->
            val sourceUrl = persisted.sourceUrl()
            delegate.addCookie(sourceUrl, persisted.toKtorCookie())
        }
        loaded = true
        vault.save(profileId, persistedCookies)
    }

    private fun PersistedCookie.sourceUrl(): Url {
        val cookiePath = path?.takeIf { it.startsWith('/') } ?: "/"
        return Url("$requestScheme://$requestHost$cookiePath")
    }

    private fun Cookie.toPersisted(requestUrl: Url, receivedAtMillis: Long): PersistedCookie = PersistedCookie(
        name = name,
        value = value,
        encoding = encoding.name,
        receivedAtMillis = receivedAtMillis,
        effectiveExpiresAtMillis = maxAge
            ?.let { receivedAtMillis + it.toLong() * 1_000L }
            ?: expires?.timestamp,
        requestScheme = requestUrl.protocol.name,
        requestHost = requestUrl.host,
        domain = domain,
        path = path,
        secure = secure,
        httpOnly = httpOnly,
        extensions = extensions,
    )

    private fun PersistedCookie.toKtorCookie(): Cookie = Cookie(
        name = name,
        value = value,
        encoding = CookieEncoding.entries.firstOrNull { it.name == encoding } ?: CookieEncoding.URI_ENCODING,
        expires = effectiveExpiresAtMillis?.let(::GMTDate),
        domain = domain,
        path = path,
        secure = secure,
        httpOnly = httpOnly,
        extensions = extensions,
    )

    private fun PersistedCookie.sameIdentityAs(other: PersistedCookie): Boolean =
        name == other.name &&
            domain.orEmpty().lowercase() == other.domain.orEmpty().lowercase() &&
            (domain != null || requestHost.equals(other.requestHost, ignoreCase = true)) &&
            path.orEmpty() == other.path.orEmpty()

    private fun PersistedCookie.isExpired(now: Long): Boolean =
        effectiveExpiresAtMillis?.let { it <= now } == true
}

internal expect fun currentEpochMillis(): Long
