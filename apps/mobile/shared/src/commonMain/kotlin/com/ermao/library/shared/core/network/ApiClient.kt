package com.ermao.library.shared.core.network

import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.forms.MultiPartFormDataContent
import io.ktor.client.request.forms.formData
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.Headers
import io.ktor.http.URLBuilder
import io.ktor.http.contentType
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readAvailable
import io.ktor.utils.io.cancel
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

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
    val queryParameters: Map<String, List<String>> = emptyMap(),
)

internal data class ApiMultipartFile(
    val fieldName: String,
    val fileName: String,
    val contentType: String,
    val bytes: ByteArray,
)

internal data class ApiMultipartRequest<T>(
    val method: ApiMethod = ApiMethod.Post,
    val apiPath: String,
    val responseDeserializer: DeserializationStrategy<T>,
    val file: ApiMultipartFile,
)

data class AuthenticatedAsset(
    val bytes: ByteArray,
    val mimeType: String?,
    val etag: String?,
    val notModified: Boolean = false,
)

/** A bounded authenticated JSON response with conditional-request metadata. */
internal data class AuthenticatedJson(
    val bytes: ByteArray,
    val etag: String?,
    val notModified: Boolean = false,
)

internal data class AuthenticatedBinary(
    val bytes: ByteArray,
    val mimeType: String,
    val contentDisposition: String?,
)

internal data class AuthenticatedDownload(
    val mimeType: String,
    val contentLength: Long?,
    val etag: String?,
)

internal sealed interface StreamedDownloadBodyResult {
    data class Complete(val totalBytes: Long) : StreamedDownloadBodyResult
    data class Failure(val error: AppError) : StreamedDownloadBodyResult
}

class ApiClient internal constructor(
    private val profile: ServerProfile,
    private val client: HttpClient,
    private val json: Json,
) {
    private val decoder = ApiEnvelopeDecoder(json)

    /** Feature infrastructure may stream authenticated bodies without exposing Ktor publicly. */
    internal fun authenticatedHttpClient(): HttpClient = client

    internal fun resolveAuthenticatedApiPath(apiPath: String): String {
        require(apiPath.startsWith("/api/")) { "API path must start with /api/" }
        require(!apiPath.contains('#') && !apiPath.contains('?')) { "API path must not contain a query or fragment" }
        return profile.baseUrl.resolveApiPath(apiPath)
    }

    suspend fun <T> execute(request: ApiRequest<T>): ApiResult<T> {
        try {
            require(request.apiPath.startsWith("/api/")) { "API path must start with /api/" }
            var requestUrl = buildRequestUrl(request.apiPath, request.queryParameters)
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

    internal suspend fun <T> executeMultipart(request: ApiMultipartRequest<T>): ApiResult<T> {
        try {
            require(request.apiPath.startsWith("/api/")) { "API path must start with /api/" }
            require(request.method in setOf(ApiMethod.Post, ApiMethod.Put, ApiMethod.Patch)) {
                "Multipart request method must support a body"
            }
            require(request.file.fieldName.isSafeMultipartToken()) { "Invalid multipart field name" }
            require(request.file.fileName.isSafeMultipartFileName()) { "Invalid multipart file name" }
            require(request.file.bytes.isNotEmpty()) { "Multipart file must not be empty" }
            val contentType = ContentType.parse(request.file.contentType)
            val response = client.request(profile.baseUrl.resolveApiPath(request.apiPath)) {
                method = request.method.toKtorMethod()
                setBody(
                    MultiPartFormDataContent(
                        formData {
                            append(
                                request.file.fieldName,
                                request.file.bytes,
                                Headers.build {
                                    append(
                                        HttpHeaders.ContentDisposition,
                                        "filename=\"${request.file.fileName}\"",
                                    )
                                    append(HttpHeaders.ContentType, contentType.toString())
                                },
                            )
                        },
                    ),
                )
            }
            if (response.status.value in REDIRECT_STATUS_CODES) {
                response.bodyAsText()
                return redirectFailure("MULTIPART_REDIRECT_REJECTED")
            }
            return decoder.decode(
                statusCode = response.status.value,
                body = response.bodyAsText(),
                dataDeserializer = request.responseDeserializer,
                headers = response.headers.entries().associate { it.key to it.value },
            )
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            return ApiResult.Failure(AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT"))
        } catch (error: PlatformStorageException) {
            return ApiResult.Failure(AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE"))
        } catch (error: Throwable) {
            return ApiResult.Failure(mapTransportError(error))
        }
    }

    suspend fun loadAuthenticatedAsset(
        apiPath: String,
        etag: String? = null,
        maximumBytes: Int = DEFAULT_MAXIMUM_ASSET_BYTES,
    ): ApiResult<AuthenticatedAsset> {
        try {
            require(apiPath.startsWith("/api/")) { "Asset path must start with /api/" }
            require(!apiPath.contains('#')) { "Asset path must not contain a fragment" }
            require(maximumBytes > 0) { "Asset size limit must be positive" }
            var requestUrl = profile.baseUrl.resolveApiPath(apiPath)
            var redirectCount = 0
            while (true) {
                val response = client.request(requestUrl) {
                    method = HttpMethod.Get
                    etag?.let { headers.append(HttpHeaders.IfNoneMatch, it) }
                }
                if (response.status.value in REDIRECT_STATUS_CODES) {
                    response.bodyAsText()
                    val location = response.headers[HttpHeaders.Location]
                        ?: return redirectFailure("REDIRECT_LOCATION_MISSING")
                    val targetUrl = RedirectPolicy.resolve(requestUrl, location)
                        ?: return redirectFailure("REDIRECT_LOCATION_INVALID")
                    if (!RedirectPolicy.shouldFollow(requestUrl, targetUrl)) {
                        return redirectFailure("REDIRECT_REJECTED")
                    }
                    if (redirectCount >= MAX_REDIRECTS) {
                        return redirectFailure("TOO_MANY_REDIRECTS")
                    }
                    redirectCount += 1
                    requestUrl = targetUrl
                    continue
                }
                if (response.status.value == 304) {
                    response.bodyAsText()
                    return ApiResult.Success(
                        AuthenticatedAsset(byteArrayOf(), null, etag, notModified = true),
                        ApiResponseMetadata(response.status.value),
                    )
                }
                if (response.status.value !in 200..299) {
                    return when (val decoded = decoder.decode(
                        response.status.value,
                        response.bodyAsText(),
                        JsonElement.serializer(),
                    )) {
                        is ApiResult.Failure -> decoded
                        is ApiResult.Success -> redirectFailure("UNEXPECTED_ASSET_RESPONSE")
                    }
                }
                val mimeType = response.headers[HttpHeaders.ContentType]
                    ?.substringBefore(';')
                    ?.trim()
                    ?.lowercase()
                    ?: return redirectFailure("ASSET_CONTENT_TYPE_MISSING")
                if (!mimeType.startsWith("image/")) {
                    response.bodyAsText()
                    return redirectFailure("ASSET_CONTENT_TYPE_INVALID")
                }
                val declaredSize = response.headers[HttpHeaders.ContentLength]?.toLongOrNull()
                if (declaredSize != null && declaredSize > maximumBytes) {
                    response.bodyAsText()
                    return ApiResult.Failure(
                        AppError(AppErrorKind.PayloadTooLarge, "ASSET_TOO_LARGE"),
                    )
                }
                val bytes = response.body<ByteArray>()
                if (bytes.size > maximumBytes) {
                    return ApiResult.Failure(
                        AppError(AppErrorKind.PayloadTooLarge, "ASSET_TOO_LARGE"),
                    )
                }
                return ApiResult.Success(
                    AuthenticatedAsset(bytes, mimeType, response.headers[HttpHeaders.ETag]),
                    ApiResponseMetadata(
                        response.status.value,
                        response.headers.entries().associate { it.key to it.value },
                    ),
                )
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            return ApiResult.Failure(AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", timeout.message))
        } catch (error: PlatformStorageException) {
            return ApiResult.Failure(AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE", error.message))
        } catch (error: Throwable) {
            return ApiResult.Failure(mapTransportError(error))
        }
    }

    /**
     * Loads a JSON endpoint using the same Cookie/redirect policy as media assets.
     *
     * This is intentionally separate from [loadAuthenticatedAsset]: the latter validates an
     * image content type and is unsuitable for Reader progress, whose response is JSON and may
     * legitimately be `304 Not Modified`.
     */
    internal suspend fun loadAuthenticatedJson(
        apiPath: String,
        etag: String? = null,
        maximumBytes: Int = DEFAULT_MAXIMUM_JSON_BYTES,
    ): ApiResult<AuthenticatedJson> {
        try {
            require(apiPath.startsWith("/api/")) { "JSON path must start with /api/" }
            require(!apiPath.contains('#')) { "JSON path must not contain a fragment" }
            require(maximumBytes > 0) { "JSON size limit must be positive" }
            var requestUrl = profile.baseUrl.resolveApiPath(apiPath)
            var redirectCount = 0
            while (true) {
                val response = client.request(requestUrl) {
                    method = HttpMethod.Get
                    etag?.let { headers.append(HttpHeaders.IfNoneMatch, it) }
                }
                if (response.status.value in REDIRECT_STATUS_CODES) {
                    response.bodyAsText()
                    val location = response.headers[HttpHeaders.Location]
                        ?: return redirectFailure("REDIRECT_LOCATION_MISSING")
                    val targetUrl = RedirectPolicy.resolve(requestUrl, location)
                        ?: return redirectFailure("REDIRECT_LOCATION_INVALID")
                    if (!RedirectPolicy.shouldFollow(requestUrl, targetUrl)) {
                        return redirectFailure("REDIRECT_REJECTED")
                    }
                    if (redirectCount >= MAX_REDIRECTS) {
                        return redirectFailure("TOO_MANY_REDIRECTS")
                    }
                    redirectCount += 1
                    requestUrl = targetUrl
                    continue
                }
                val responseEtag = response.headers[HttpHeaders.ETag]
                if (response.status.value == 304) {
                    response.bodyAsText()
                    return ApiResult.Success(
                        AuthenticatedJson(byteArrayOf(), responseEtag ?: etag, notModified = true),
                        ApiResponseMetadata(response.status.value),
                    )
                }
                if (response.status.value !in 200..299) {
                    return when (val decoded = decoder.decode(
                        response.status.value,
                        response.bodyAsText(),
                        JsonElement.serializer(),
                    )) {
                        is ApiResult.Failure -> decoded
                        is ApiResult.Success -> redirectFailure("UNEXPECTED_JSON_RESPONSE")
                    }
                }
                val contentType = response.headers[HttpHeaders.ContentType]
                    ?.substringBefore(';')
                    ?.trim()
                    ?.lowercase()
                    ?: return redirectFailure("JSON_CONTENT_TYPE_MISSING")
                if (contentType != "application/json" && !contentType.endsWith("+json")) {
                    response.bodyAsText()
                    return redirectFailure("JSON_CONTENT_TYPE_INVALID")
                }
                val declaredSize = response.headers[HttpHeaders.ContentLength]?.toLongOrNull()
                if (declaredSize != null && declaredSize > maximumBytes) {
                    response.bodyAsText()
                    return ApiResult.Failure(AppError(AppErrorKind.PayloadTooLarge, "JSON_TOO_LARGE"))
                }
                val bytes = response.bodyAsChannel().readBounded(maximumBytes)
                    ?: return ApiResult.Failure(AppError(AppErrorKind.PayloadTooLarge, "JSON_TOO_LARGE"))
                return ApiResult.Success(
                    AuthenticatedJson(bytes, responseEtag),
                    ApiResponseMetadata(
                        response.status.value,
                        response.headers.entries().associate { it.key to it.value },
                    ),
                )
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            return ApiResult.Failure(AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", timeout.message))
        } catch (error: PlatformStorageException) {
            return ApiResult.Failure(AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE", error.message))
        } catch (error: Throwable) {
            return ApiResult.Failure(mapTransportError(error))
        }
    }

    internal suspend fun loadAuthenticatedBinary(
        apiPath: String,
        maximumBytes: Int,
        allowedMimeTypes: Set<String>,
    ): ApiResult<AuthenticatedBinary> {
        try {
            require(apiPath.startsWith("/api/")) { "Binary path must start with /api/" }
            require(!apiPath.contains('#')) { "Binary path must not contain a fragment" }
            require(maximumBytes > 0) { "Binary size limit must be positive" }
            require(allowedMimeTypes.isNotEmpty()) { "At least one binary MIME type is required" }
            val response = client.request(profile.baseUrl.resolveApiPath(apiPath)) {
                method = HttpMethod.Get
            }
            if (response.status.value in REDIRECT_STATUS_CODES) {
                return redirectFailure("BINARY_REDIRECT_REJECTED")
            }
            if (response.status.value !in 200..299) {
                val errorBody = response.bodyAsChannel().readBounded(DOWNLOAD_ERROR_BODY_BYTES)
                    ?: return redirectFailure("DOWNLOAD_ERROR_BODY_TOO_LARGE")
                return when (val decoded = decoder.decode(
                    response.status.value,
                    errorBody.decodeToString(),
                    JsonElement.serializer(),
                )) {
                    is ApiResult.Failure -> decoded
                    is ApiResult.Success -> redirectFailure("UNEXPECTED_BINARY_RESPONSE")
                }
            }
            val mimeType = response.headers[HttpHeaders.ContentType]
                ?.substringBefore(';')
                ?.trim()
                ?.lowercase()
                ?: return redirectFailure("BINARY_CONTENT_TYPE_MISSING")
            if (mimeType !in allowedMimeTypes) {
                return redirectFailure("BINARY_CONTENT_TYPE_INVALID")
            }
            val declaredSize = response.headers[HttpHeaders.ContentLength]?.toLongOrNull()
            if (declaredSize != null && declaredSize > maximumBytes) {
                return ApiResult.Failure(AppError(AppErrorKind.PayloadTooLarge, "BINARY_TOO_LARGE"))
            }
            val bytes = response.bodyAsChannel().readBounded(maximumBytes)
                ?: return ApiResult.Failure(AppError(AppErrorKind.PayloadTooLarge, "BINARY_TOO_LARGE"))
            return ApiResult.Success(
                AuthenticatedBinary(
                    bytes = bytes,
                    mimeType = mimeType,
                    contentDisposition = response.headers[HttpHeaders.ContentDisposition],
                ),
                ApiResponseMetadata(
                    response.status.value,
                    response.headers.entries().associate { it.key to it.value },
                ),
            )
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            return ApiResult.Failure(AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", timeout.message))
        } catch (error: PlatformStorageException) {
            return ApiResult.Failure(AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE", error.message))
        } catch (error: Throwable) {
            return ApiResult.Failure(mapTransportError(error))
        }
    }

    /** Streams an authenticated response without retaining the publication in memory. */
    internal suspend fun streamAuthenticatedDownload(
        apiPath: String,
        maximumBytes: Long,
        allowedMimeTypes: Set<String>,
        writeChunk: suspend (bytes: ByteArray, count: Int) -> Unit,
    ): ApiResult<AuthenticatedDownload> {
        try {
            require(apiPath.startsWith("/api/")) { "Download path must start with /api/" }
            require(!apiPath.contains('#')) { "Download path must not contain a fragment" }
            require(maximumBytes > 0) { "Download size limit must be positive" }
            require(allowedMimeTypes.isNotEmpty()) { "At least one download MIME type is required" }
            val response = client.request(profile.baseUrl.resolveApiPath(apiPath)) {
                method = HttpMethod.Get
            }
            if (response.status.value in REDIRECT_STATUS_CODES) {
                response.bodyAsChannel().cancelQuietly()
                return redirectFailure("DOWNLOAD_REDIRECT_REJECTED")
            }
            if (response.status.value !in 200..299) {
                val errorChannel = response.bodyAsChannel()
                val errorBody = errorChannel.readBounded(DOWNLOAD_ERROR_BODY_BYTES)
                if (errorBody == null) {
                    errorChannel.cancelQuietly()
                    return redirectFailure("DOWNLOAD_ERROR_BODY_TOO_LARGE")
                }
                return when (val decoded = decoder.decode(
                    response.status.value,
                    errorBody.decodeToString(),
                    JsonElement.serializer(),
                )) {
                    is ApiResult.Failure -> decoded
                    is ApiResult.Success -> redirectFailure("UNEXPECTED_DOWNLOAD_RESPONSE")
                }
            }
            val mimeType = response.headers[HttpHeaders.ContentType]
                ?.substringBefore(';')
                ?.trim()
                ?.lowercase()
                ?: run {
                    response.bodyAsChannel().cancelQuietly()
                    return redirectFailure("DOWNLOAD_CONTENT_TYPE_MISSING")
                }
            if (mimeType !in allowedMimeTypes) {
                response.bodyAsChannel().cancelQuietly()
                return redirectFailure("DOWNLOAD_CONTENT_TYPE_INVALID")
            }
            val declaredSize = response.headers[HttpHeaders.ContentLength]?.toLongOrNull()
            if (declaredSize != null && declaredSize !in 1..maximumBytes) {
                response.bodyAsChannel().cancelQuietly()
                return ApiResult.Failure(AppError(AppErrorKind.PayloadTooLarge, "DOWNLOAD_TOO_LARGE"))
            }
            val channel = response.bodyAsChannel()
            when (val body = consumeStreamedDownloadBody(
                channel,
                maximumBytes,
                declaredSize,
                writeChunk,
            )) {
                is StreamedDownloadBodyResult.Failure -> return ApiResult.Failure(body.error)
                is StreamedDownloadBodyResult.Complete -> Unit
            }
            return ApiResult.Success(
                AuthenticatedDownload(mimeType, declaredSize, response.headers[HttpHeaders.ETag]),
                ApiResponseMetadata(
                    response.status.value,
                    response.headers.entries().associate { it.key to it.value },
                ),
            )
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            return ApiResult.Failure(AppError(AppErrorKind.Timeout, "REQUEST_TIMEOUT", timeout.message))
        } catch (error: PlatformStorageException) {
            return ApiResult.Failure(AppError(AppErrorKind.StorageFailure, "STORAGE_FAILURE", error.message))
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

    private fun buildRequestUrl(
        apiPath: String,
        queryParameters: Map<String, List<String>>,
    ): String = URLBuilder(profile.baseUrl.resolveApiPath(apiPath)).apply {
        queryParameters.entries.sortedBy { it.key }.forEach { (name, values) ->
            values.forEach { value -> parameters.append(name, value) }
        }
    }.buildString()

    private fun ApiMethod.toKtorMethod(): HttpMethod = when (this) {
        ApiMethod.Get -> HttpMethod.Get
        ApiMethod.Post -> HttpMethod.Post
        ApiMethod.Put -> HttpMethod.Put
        ApiMethod.Patch -> HttpMethod.Patch
        ApiMethod.Delete -> HttpMethod.Delete
        ApiMethod.Head -> HttpMethod.Head
    }

    private fun String.isSafeMultipartToken(): Boolean = isNotBlank() && all { character ->
        character.isLetterOrDigit() || character == '_' || character == '-'
    }

    private fun String.isSafeMultipartFileName(): Boolean = isNotBlank() && all { character ->
        character.code in 0x20..0x7e && character != '"' && character != '\\' && character != '/'
    }

    private suspend fun ByteReadChannel.readBounded(maximumBytes: Int): ByteArray? {
        val chunks = mutableListOf<ByteArray>()
        val readBuffer = ByteArray(BINARY_READ_BUFFER_BYTES)
        var totalBytes = 0L
        while (true) {
            val remainingWithOverflowProbe = maximumBytes.toLong() - totalBytes + 1L
            val requestedBytes = minOf(readBuffer.size.toLong(), remainingWithOverflowProbe).toInt()
            val count = readAvailable(readBuffer, 0, requestedBytes)
            if (count < 0) break
            if (count == 0) continue
            totalBytes += count
            if (totalBytes > maximumBytes) return null
            chunks += readBuffer.copyOf(count)
        }
        val result = ByteArray(totalBytes.toInt())
        var offset = 0
        chunks.forEach { chunk ->
            chunk.copyInto(result, destinationOffset = offset)
            offset += chunk.size
        }
        return result
    }

    /** Rejected bodies are intentionally abandoned; cleanup failure must not replace the protocol result. */
    private fun ByteReadChannel.cancelQuietly() {
        try {
            cancel()
        } catch (_: Throwable) {
            // The response has already been classified and no body bytes are retained.
        }
    }

    private companion object {
        val REDIRECT_STATUS_CODES = setOf(301, 302, 303, 307, 308)
        const val MAX_REDIRECTS = 3
        const val DEFAULT_MAXIMUM_ASSET_BYTES = 12 * 1024 * 1024
        const val DEFAULT_MAXIMUM_JSON_BYTES = 196_608
        const val BINARY_READ_BUFFER_BYTES = 64 * 1024
        const val DOWNLOAD_BUFFER_BYTES = 64 * 1024
        const val DOWNLOAD_ERROR_BODY_BYTES = 64 * 1024
    }
}

internal suspend fun consumeStreamedDownloadBody(
    channel: ByteReadChannel,
    maximumBytes: Long,
    declaredSize: Long?,
    writeChunk: suspend (bytes: ByteArray, count: Int) -> Unit,
): StreamedDownloadBodyResult {
    require(maximumBytes > 0)
    val buffer = ByteArray(64 * 1024)
    var totalBytes = 0L
    while (true) {
        val remainingWithOverflowProbe = maximumBytes - totalBytes + 1L
        val requestedBytes = minOf(buffer.size.toLong(), remainingWithOverflowProbe).toInt()
        val count = try {
            channel.readAvailable(buffer, 0, requestedBytes)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            return StreamedDownloadBodyResult.Failure(
                AppError(AppErrorKind.NetworkUnavailable, "DOWNLOAD_INTERRUPTED"),
            )
        }
        if (count < 0) break
        if (count == 0) continue
        totalBytes += count
        if (totalBytes > maximumBytes) {
            try {
                channel.cancel()
            } catch (_: Throwable) {
                // The body is already rejected and no bytes are retained.
            }
            return StreamedDownloadBodyResult.Failure(
                AppError(AppErrorKind.PayloadTooLarge, "DOWNLOAD_TOO_LARGE"),
            )
        }
        writeChunk(buffer, count)
    }
    if (totalBytes == 0L) {
        return StreamedDownloadBodyResult.Failure(
            AppError(AppErrorKind.ProtocolViolation, "DOWNLOAD_EMPTY"),
        )
    }
    if (declaredSize != null && totalBytes != declaredSize) {
        return StreamedDownloadBodyResult.Failure(
            AppError(AppErrorKind.ProtocolViolation, "DOWNLOAD_LENGTH_MISMATCH"),
        )
    }
    return StreamedDownloadBodyResult.Complete(totalBytes)
}

internal expect fun mapTransportError(error: Throwable): AppError
