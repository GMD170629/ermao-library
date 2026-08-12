package com.ermao.library.shared.core.network

import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.engine.darwin.Darwin
import io.ktor.client.engine.darwin.DarwinHttpRequestException
import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSDate
import platform.Foundation.NSURLErrorDomain
import platform.Foundation.NSURLErrorServerCertificateHasBadDate
import platform.Foundation.NSURLErrorServerCertificateNotYetValid
import platform.Foundation.NSURLErrorServerCertificateUntrusted
import platform.Foundation.NSURLErrorServerCertificateHasUnknownRoot
import platform.Foundation.NSURLErrorSecureConnectionFailed
import platform.Foundation.NSURLErrorTimedOut
import platform.Foundation.NSURLAuthenticationMethodServerTrust
import platform.Foundation.NSURLCredential
import platform.Foundation.NSURLSessionAuthChallengePerformDefaultHandling
import platform.Foundation.NSURLSessionAuthChallengeUseCredential
import platform.Foundation.create
import platform.Foundation.serverTrust
import platform.Foundation.timeIntervalSince1970

// NSURLProtectionSpace.serverTrust is exposed through Kotlin/Native's experimental Security cinterop.
@OptIn(BetaInteropApi::class, ExperimentalForeignApi::class)
internal actual fun createPlatformHttpClient(
    profile: ServerProfile,
    configure: HttpClientConfig<*>.() -> Unit,
): HttpClient = HttpClient(Darwin) {
    configure(this)
    if (profile.tlsMode == TlsMode.InsecureSkipAllValidation) {
        engine {
            handleChallenge { _, _, challenge, completionHandler ->
                val protectionSpace = challenge.protectionSpace
                val serverTrust = protectionSpace.serverTrust
                if (protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust &&
                    serverTrust != null
                ) {
                    completionHandler(
                        NSURLSessionAuthChallengeUseCredential,
                        NSURLCredential.create(serverTrust),
                    )
                } else {
                    completionHandler(NSURLSessionAuthChallengePerformDefaultHandling, null)
                }
            }
        }
    }
}

internal actual fun mapTransportError(error: Throwable): AppError {
    val origin = (error as? DarwinHttpRequestException)?.origin
        ?: return AppError(AppErrorKind.NetworkUnavailable, "TRANSPORT_FAILURE", error.message)
    if (origin.domain != NSURLErrorDomain) {
        return AppError(AppErrorKind.NetworkUnavailable, "TRANSPORT_FAILURE", error.message)
    }
    return when (origin.code) {
        NSURLErrorTimedOut -> AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", origin.localizedDescription)
        NSURLErrorSecureConnectionFailed,
        NSURLErrorServerCertificateHasBadDate,
        NSURLErrorServerCertificateNotYetValid,
        NSURLErrorServerCertificateUntrusted,
        NSURLErrorServerCertificateHasUnknownRoot,
        -> AppError(AppErrorKind.TlsFailure, "TLS_FAILURE", origin.localizedDescription)
        else -> AppError(AppErrorKind.NetworkUnavailable, "NETWORK_UNAVAILABLE", origin.localizedDescription)
    }
}

internal actual fun currentEpochMillis(): Long = (NSDate().timeIntervalSince1970 * 1_000.0).toLong()
