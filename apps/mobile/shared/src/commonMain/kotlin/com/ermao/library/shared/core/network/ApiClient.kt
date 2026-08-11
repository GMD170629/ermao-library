package com.ermao.library.shared.core.network

import com.ermao.library.shared.modules.servers.domain.ServerProfile
import io.ktor.client.HttpClient
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpMethod
import io.ktor.http.contentType
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.json.Json
import com.ermao.library.shared.core.storage.PlatformStorageException

enum class ApiMethod {
    Get,
    Post,
    Put,
    Patch,
    Delete,
    Head,
}

data class ApiRequest<T>(
    val method: ApiMethod,
    val apiPath: String,
    val responseDeserializer: DeserializationStrategy<T>,
    val requestBody: String? = null,
)

class ApiClient internal constructor(
    private val profile: ServerProfile,
    private val client: HttpClient,
    private val json: Json,
) {
    private val decoder = ApiEnvelopeDecoder(json)

    suspend fun <T> execute(request: ApiRequest<T>): ApiResult<T> {
        try {
            require(request.apiPath.startsWith("/api/")) { "API path must start with /api/" }
            var requestUrl = profile.baseUrl.resolveApiPath(request.apiPath)
            var method = request.method
            var requestBody = request.requestBody
            var redirectCount = 0
            while (true) {
            val response = client.request(requestUrl) {
                this.method = method.toKtorMethod()
                requestBody?.let {
                    contentType(ContentType.Application.Json)
                    setBody(it)
                }
            }
            if (response.status.value in REDIRECT_STATUS_CODES) {
                response.bodyAsText()
                val location = response.headers[io.ktor.http.HttpHeaders.Location]
                    ?: return redirectFailure("REDIRECT_LOCATION_MISSING")
                val targetUrl = RedirectPolicy.resolve(requestUrl, location)
                    ?: return redirectFailure("REDIRECT_LOCATION_INVALID")
                if (!RedirectPolicy.shouldFollow(requestUrl, targetUrl)) {
                    return redirectFailure("REDIRECT_REJECTED")
                }
                if (redirectCount >= MAX_REDIRECTS) {
                    return redirectFailure("TOO_MANY_REDIRECTS")
                }
                when (response.status.value) {
                    303 -> {
                        method = ApiMethod.Get
                        requestBody = null
                    }
                    301, 302 -> if (method != ApiMethod.Get && method != ApiMethod.Head) {
                        return redirectFailure("AMBIGUOUS_REDIRECT_METHOD")
                    }
                }
                redirectCount += 1
                requestUrl = targetUrl
                continue
            }
            return decoder.decode(
                statusCode = response.status.value,
                body = response.bodyAsText(),
                dataDeserializer = request.responseDeserializer,
                headers = response.headers.entries().associate { it.key to it.value },
            )
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            return ApiResult.Failure(
                AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", timeout.message),
            )
        } catch (error: PlatformStorageException) {
            return ApiResult.Failure(
                AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE", error.message),
            )
        } catch (error: Throwable) {
            return ApiResult.Failure(mapTransportError(error))
        }
    }

    fun close() {
        client.close()
    }

    private fun redirectFailure(code: String): ApiResult.Failure = ApiResult.Failure(
        AppError(AppErrorKind.ProtocolViolation, code),
    )

    private fun ApiMethod.toKtorMethod(): HttpMethod = when (this) {
        ApiMethod.Get -> HttpMethod.Get
        ApiMethod.Post -> HttpMethod.Post
        ApiMethod.Put -> HttpMethod.Put
        ApiMethod.Patch -> HttpMethod.Patch
        ApiMethod.Delete -> HttpMethod.Delete
        ApiMethod.Head -> HttpMethod.Head
    }

    private companion object {
        val REDIRECT_STATUS_CODES = setOf(301, 302, 303, 307, 308)
        const val MAX_REDIRECTS = 3
    }
}

internal expect fun mapTransportError(error: Throwable): AppError
