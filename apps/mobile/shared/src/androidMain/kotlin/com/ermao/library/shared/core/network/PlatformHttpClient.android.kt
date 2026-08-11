package com.ermao.library.shared.core.network

import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.engine.okhttp.OkHttp
import java.io.IOException
import java.net.SocketTimeoutException
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

internal actual fun createPlatformHttpClient(
    profile: ServerProfile,
    configure: HttpClientConfig<*>.() -> Unit,
): HttpClient = HttpClient(OkHttp) {
    configure(this)
    if (profile.tlsMode == TlsMode.InsecureSkipAllValidation) {
        engine {
            config {
                followRedirects(false)
                followSslRedirects(false)
                val trustManager = InsecureTrustManager
                val sslContext = SSLContext.getInstance("TLS").apply {
                    init(null, arrayOf<TrustManager>(trustManager), SecureRandom())
                }
                sslSocketFactory(sslContext.socketFactory, trustManager)
                hostnameVerifier { _, _ -> true }
            }
        }
    }
}

internal actual fun mapTransportError(error: Throwable): AppError = when (error) {
    is SocketTimeoutException -> AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", error.message)
    is SSLException -> AppError(AppErrorKind.TlsFailure, "TLS_FAILURE", error.message)
    is IOException -> AppError(AppErrorKind.NetworkUnavailable, "NETWORK_UNAVAILABLE", error.message)
    else -> AppError(AppErrorKind.NetworkUnavailable, "TRANSPORT_FAILURE", error.message)
}

internal actual fun currentEpochMillis(): Long = System.currentTimeMillis()

/** Constructed only for a profile whose user explicitly and permanently accepted the TLS risk. */
private object InsecureTrustManager : X509TrustManager {
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        requireUsableChallenge(chain, authType)
    }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        requireUsableChallenge(chain, authType)
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    private fun requireUsableChallenge(chain: Array<out X509Certificate>?, authType: String?) {
        if (chain.isNullOrEmpty() || authType.isNullOrBlank()) {
            throw java.security.cert.CertificateException("TLS challenge did not contain a certificate chain")
        }
    }
}
