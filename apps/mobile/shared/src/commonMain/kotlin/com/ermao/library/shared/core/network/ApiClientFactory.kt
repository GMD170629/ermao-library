package com.ermao.library.shared.core.network

import com.ermao.library.shared.modules.servers.domain.ServerProfile
import io.ktor.client.HttpClient
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.cookies.HttpCookies
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json

class ApiClientFactory(
    private val cookieVault: CookieVault,
    private val requestTimeoutMillis: Long = 30_000,
) {
    private val json = Json {
        ignoreUnknownKeys = false
        explicitNulls = false
        isLenient = false
    }

    fun create(profile: ServerProfile): ApiClient {
        val cookies = PersistentCookiesStorage(profile.id, cookieVault)
        val client = createPlatformHttpClient(profile) {
            followRedirects = false
            install(HttpCookies) {
                storage = cookies
            }
            install(ContentNegotiation) {
                json(json)
            }
            install(HttpTimeout) {
                requestTimeoutMillis = this@ApiClientFactory.requestTimeoutMillis
                connectTimeoutMillis = 15_000
                socketTimeoutMillis = requestTimeoutMillis
            }
        }
        return ApiClient(profile, client, json)
    }
}

object RedirectPolicy {
    fun shouldFollow(sourceUrl: String, targetUrl: String): Boolean = try {
        val source = io.ktor.http.Url(sourceUrl)
        val target = io.ktor.http.Url(targetUrl)
        val sameHost = source.host.equals(target.host, ignoreCase = true)
        val sameOrigin = sameHost &&
            source.protocol.name.equals(target.protocol.name, ignoreCase = true) &&
            source.port == target.port
        val httpToHttpsUpgrade = sameHost &&
            source.protocol.name.equals("http", ignoreCase = true) &&
            target.protocol.name.equals("https", ignoreCase = true)
        sameOrigin || httpToHttpsUpgrade
    } catch (_: IllegalArgumentException) {
        false
    }

    fun resolve(sourceUrl: String, location: String): String? {
        if (location.isBlank() || location.any { it.code < 0x20 || it.code == 0x7f }) return null
        val withoutFragment = location.substringBefore('#')
        if (withoutFragment.startsWith("http://", ignoreCase = true) ||
            withoutFragment.startsWith("https://", ignoreCase = true)
        ) return withoutFragment
        val schemeEnd = sourceUrl.indexOf("://")
        if (schemeEnd <= 0) return null
        val authorityEnd = sourceUrl.indexOf('/', schemeEnd + 3).takeIf { it >= 0 } ?: sourceUrl.length
        val origin = sourceUrl.substring(0, authorityEnd)
        return when {
            withoutFragment.startsWith("//") -> sourceUrl.substring(0, schemeEnd) + ":" + withoutFragment
            withoutFragment.startsWith('/') -> origin + withoutFragment
            withoutFragment.startsWith('?') -> sourceUrl.substringBefore('?') + withoutFragment
            else -> sourceUrl.substringBefore('?').substringBeforeLast('/', origin) + "/" + withoutFragment
        }
    }
}

internal expect fun createPlatformHttpClient(
    profile: ServerProfile,
    configure: io.ktor.client.HttpClientConfig<*>.() -> Unit,
): HttpClient
