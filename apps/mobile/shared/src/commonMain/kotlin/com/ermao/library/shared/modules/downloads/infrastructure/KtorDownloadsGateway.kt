package com.ermao.library.shared.modules.downloads.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.core.network.mapTransportError
import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.modules.downloads.application.CompletedTransfer
import com.ermao.library.shared.modules.downloads.application.DownloadBootstrap
import com.ermao.library.shared.modules.downloads.application.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult
import com.ermao.library.shared.modules.downloads.application.DownloadByteSink
import com.ermao.library.shared.modules.downloads.application.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.application.DownloadProgressObserver
import com.ermao.library.shared.modules.downloads.application.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.application.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferGateway
import com.ermao.library.shared.modules.downloads.application.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferResult
import com.ermao.library.shared.modules.downloads.application.DownloadsGateway
import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
import com.ermao.library.shared.modules.downloads.domain.DownloadSource
import com.ermao.library.shared.modules.downloads.domain.isSafeMediaApiPath
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.header
import io.ktor.client.request.prepareGet
import io.ktor.client.statement.bodyAsChannel
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpHeaders
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/** Foreground, app-owned download gateway backed by Reader resource bootstrap. */
class KtorDownloadsGateway(
    private val apiClient: ApiClient,
) : DownloadsGateway {
    override suspend fun load(
        context: DownloadRequestContext,
        resourceId: String,
    ): DownloadBootstrapResult {
        if (resourceId.isBlank()) return bootstrapFailure("DOWNLOAD_RESOURCE_ID_INVALID")
        return when (val response = apiClient.execute(
            ApiRequest(
                method = ApiMethod.Get,
                apiPath = "/api/reader/v4/resources/${resourceId.encodePathSegment()}/bootstrap",
                responseDeserializer = JsonObject.serializer(),
            ),
        )) {
            is ApiResult.Failure -> DownloadBootstrapResult.Failure(response.error)
            is ApiResult.Success -> try {
                DownloadBootstrapResult.Success(
                    DownloadBootstrap(response.value.toBootstrapDescriptor(context, resourceId)),
                )
            } catch (error: IllegalArgumentException) {
                DownloadBootstrapResult.Failure(
                    AppError(
                        AppErrorKind.ProtocolViolation,
                        "DOWNLOAD_BOOTSTRAP_INVALID",
                        error.message,
                    ),
                )
            }
        }
    }

    override suspend fun transfer(
        context: DownloadRequestContext,
        request: DownloadTransferRequest,
        sink: DownloadByteSink,
        progressObserver: DownloadProgressObserver?,
    ): DownloadTransferResult {
        var session: DownloadByteSinkSession? = null
        return try {
            val source = request.descriptor.source
            val statement = apiClient.authenticatedHttpClient().prepareGet(
                apiClient.resolveAuthenticatedApiPath(source.apiPath),
            ) {
                if (request.resumeFromBytes > 0) {
                    header(HttpHeaders.Range, "bytes=${request.resumeFromBytes}-")
                    request.ifRangeValidator?.takeIf(String::isNotBlank)?.let { header(HttpHeaders.IfRange, it) }
                }
            }
            return statement.execute { response ->
                if (response.status.value in REDIRECT_STATUS_CODES) {
                    response.bodyAsText()
                    return@execute transferFailure("DOWNLOAD_REDIRECT_REJECTED")
                }
                val responseContract = validateResponse(
                    statusCode = response.status.value,
                    contentLength = response.headers[HttpHeaders.ContentLength],
                    contentRange = response.headers[HttpHeaders.ContentRange],
                    expectedTotalBytes = source.totalBytes,
                    resumeFromBytes = request.resumeFromBytes,
                ) ?: run {
                    response.bodyAsChannel().cancel(null)
                    return@execute transferFailure("DOWNLOAD_RESPONSE_INVALID")
                }
                session = sink.begin(
                    DownloadSinkRequest(
                        namespace = context.namespace,
                        taskId = request.taskId,
                        resourceId = request.descriptor.identity.resourceId,
                        assetId = request.descriptor.identity.assetId,
                        expectedTotalBytes = source.totalBytes,
                        resumeFromBytes = request.resumeFromBytes,
                    ),
                )
                val channel = response.bodyAsChannel()
                val buffer = ByteArray(TRANSFER_BUFFER_BYTES)
                var receivedBytes = 0L
                while (true) {
                    val read = channel.readAvailable(buffer, 0, buffer.size)
                    if (read < 0) break
                    if (read == 0) continue
                    receivedBytes += read
                    if (receivedBytes > responseContract.contentLength) {
                        throw DownloadProtocolException("Response exceeded Content-Length")
                    }
                    session.write(buffer.copyOf(read))
                    progressObserver?.onProgress(request.resumeFromBytes + receivedBytes, source.totalBytes)
                }
                if (receivedBytes != responseContract.contentLength) {
                    throw DownloadProtocolException("Response ended before Content-Length")
                }
                val localReference = session.commit(source.totalBytes)
                require(localReference.isNotBlank()) { "Sink returned an empty local reference" }
                DownloadTransferResult.Success(
                    CompletedTransfer(
                        localReference = localReference,
                        verifiedBytes = source.totalBytes,
                        etag = response.headers[HttpHeaders.ETag],
                        lastModified = response.headers[HttpHeaders.LastModified],
                    ),
                )
            }
        } catch (cancelled: CancellationException) {
            withContext(NonCancellable) {
                if (request.preservePartialOnCancellation) session?.pause() else session?.abort()
            }
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            session?.abortSafely()
            DownloadTransferResult.Failure(AppError(AppErrorKind.Timeout, "DOWNLOAD_TIMEOUT", timeout.message))
        } catch (storage: PlatformStorageException) {
            session?.abortSafely()
            DownloadTransferResult.Failure(AppError(AppErrorKind.StorageFailure, "DOWNLOAD_STORAGE_FAILURE", storage.message))
        } catch (protocol: DownloadProtocolException) {
            session?.abortSafely()
            DownloadTransferResult.Failure(AppError(AppErrorKind.ProtocolViolation, "DOWNLOAD_RESPONSE_INVALID", protocol.message))
        } catch (error: Throwable) {
            session?.abortSafely()
            DownloadTransferResult.Failure(mapTransportError(error))
        }
    }

    private suspend fun DownloadByteSinkSession.abortSafely() {
        withContext(NonCancellable) { runCatching { abort() } }
    }

    private data class ResponseContract(val contentLength: Long)

    private fun validateResponse(
        statusCode: Int,
        contentLength: String?,
        contentRange: String?,
        expectedTotalBytes: Long,
        resumeFromBytes: Long,
    ): ResponseContract? {
        val declaredLength = contentLength?.toLongOrNull()?.takeIf { it > 0 } ?: return null
        if (resumeFromBytes == 0L) {
            return ResponseContract(declaredLength).takeIf {
                statusCode == 200 && declaredLength == expectedTotalBytes && contentRange == null
            }
        }
        if (statusCode != 206) return null
        val range = contentRange?.let(CONTENT_RANGE::matchEntire) ?: return null
        val start = range.groupValues[1].toLongOrNull() ?: return null
        val end = range.groupValues[2].toLongOrNull() ?: return null
        val total = range.groupValues[3].toLongOrNull() ?: return null
        return ResponseContract(declaredLength).takeIf {
            start == resumeFromBytes && total == expectedTotalBytes && end >= start &&
                end - start + 1 == declaredLength && declaredLength == expectedTotalBytes - resumeFromBytes
        }
    }

    private fun JsonObject.toBootstrapDescriptor(
        context: DownloadRequestContext,
        expectedResourceId: String,
    ): DownloadDescriptor {
        require(requiredLong("schemaVersion") == 4L) { "Unsupported Reader bootstrap schema" }
        val userId = requiredString("userId")
        require(userId == context.namespace.userId) { "Bootstrap user does not match download namespace" }
        val book = requiredObject("book")
        val resource = requiredObject("resource")
        require(resource.requiredString("id") == expectedResourceId) { "Bootstrap resource does not match request" }
        require(resource.requiredString("bookId") == book.requiredString("id")) {
            "Bootstrap resource does not match book"
        }
        val readerType = parseDownloadReaderType(requiredString("readerType"))
        require(parseDownloadReaderType(resource.requiredString("readerType")) == readerType) {
            "Bootstrap reader type is inconsistent"
        }
        val resourceFormat = resource.requiredString("format").trim().lowercase()
        require(requiredString("sourceFormat").equals(resourceFormat, ignoreCase = true)) {
            "Bootstrap source format is inconsistent"
        }
        val assets = this["assets"] as? JsonArray ?: throw IllegalArgumentException("Bootstrap assets are missing")
        val assetObjects = assets.map { it as? JsonObject ?: throw IllegalArgumentException("Bootstrap asset is invalid") }
            .sortedWith(compareBy<JsonObject>({ it.requiredNonNegativeInt("sortOrder") }, { it.requiredString("id") }) )
        val primaryAsset = assetObjects.firstOrNull { it.requiredString("role").equals("PRIMARY", ignoreCase = true) }
            ?: assetObjects.firstOrNull()
            ?: throw IllegalArgumentException("Bootstrap publication asset is missing")
        require(primaryAsset.requiredString("resourceId") == expectedResourceId) {
            "Bootstrap asset does not match resource"
        }
        // ReaderAssetSummary.title is a required server field even though downloads only need
        // the asset identity. Validate it here so the download boundary cannot silently accept
        // the retired asset shape.
        primaryAsset.requiredString("title")
        val primaryUrl = primaryAsset.requiredString("url")
        require(primaryUrl.isSafeMediaApiPath()) { "Bootstrap asset URL is invalid" }
        val comicArtifact = if (readerType == DownloadReaderType.Comic) {
            val publication = requiredObject("publication")
            require(publication.requiredString("kind") == "comic") { "Comic download contract is invalid" }
            (publication["downloadArtifact"] as? JsonObject)?.also { artifact ->
                require(artifact.requiredString("url") == "/api/reader/v4/resources/$expectedResourceId/comic/archive") {
                    "Comic download artifact URL is invalid"
                }
                require(artifact.requiredString("sourceFormat").equals(resourceFormat, ignoreCase = true)) {
                    "Comic download source format is inconsistent"
                }
            }.also { artifact ->
                require(resourceFormat == "image_dir" || artifact != null) {
                    "Comic download artifact is missing"
                }
                require(resourceFormat != "image_dir" || artifact == null) {
                    "IMAGE_DIR must not expose a derived download artifact"
                }
            }
        } else null
        // Offline storage always downloads the original primary Asset. The comic archive
        // URL is an online Reader capability only and must never become a local source.
        val sourceApiPath = primaryUrl
        require(sourceApiPath.isSafeMediaApiPath()) { "Bootstrap publication URL is invalid" }
        val sourceSize = primaryAsset.requiredLong("sizeBytes")
        val sourceMime = primaryAsset.requiredString("mimeType")
            .lowercase()
            .substringBefore(';')
        require(sourceSize > 0)
        require(
            sourceMime in allowedMimeTypes(readerType) ||
                (resourceFormat == "image_dir" && sourceMime in IMAGE_MIME_TYPES),
        ) { "Bootstrap asset MIME type is inconsistent" }
        return DownloadDescriptor(
            identity = DownloadIdentity(
                namespace = context.namespace,
                bookId = book.requiredString("id"),
                resourceId = expectedResourceId,
                assetId = primaryAsset.requiredString("id"),
            ),
            bookTitle = book.requiredString("title"),
            bookAuthor = book.optionalString("author"),
            coverApiPath = book.optionalString("coverUrl"),
            resourceTitle = resource.requiredString("title"),
            format = resourceFormat,
            readerType = readerType,
            source = DownloadSource(
                apiPath = sourceApiPath,
                mimeType = sourceMime,
                totalBytes = sourceSize,
            ),
            resourceIndex = resource.optionalDouble("resourceIndex"),
            resourceSortOrder = resource.requiredNonNegativeInt("sortOrder"),
            isDownloadable = comicArtifact != null || readerType != DownloadReaderType.Comic,
        )
    }

    private fun JsonObject.requiredObject(name: String): JsonObject =
        this[name] as? JsonObject ?: throw IllegalArgumentException("$name is missing")

    private fun JsonObject.requiredString(name: String): String =
        optionalString(name) ?: throw IllegalArgumentException("$name is missing")

    private fun JsonObject.optionalString(name: String): String? =
        (this[name] as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)

    private fun JsonObject.requiredLong(name: String): Long =
        this[name]?.jsonPrimitive?.longOrNull?.takeIf { it > 0 }
            ?: throw IllegalArgumentException("$name is missing")

    private fun JsonObject.optionalDouble(name: String): Double? {
        val value = this[name] ?: return null
        if (value is kotlinx.serialization.json.JsonNull) return null
        return value.jsonPrimitive.doubleOrNull?.takeIf(Double::isFinite)
            ?: throw IllegalArgumentException("$name is invalid")
    }

    private fun JsonObject.requiredNonNegativeInt(name: String): Int =
        this[name]?.jsonPrimitive?.intOrNull?.takeIf { it >= 0 }
            ?: throw IllegalArgumentException("$name is missing")

    private fun String.encodePathSegment(): String = encodeToByteArray().joinToString("") { byte ->
        val character = (byte.toInt() and 0xff).toChar()
        if (character.isLetterOrDigit() || character in "-._~") character.toString()
        else "%" + byte.toUByte().toString(16).padStart(2, '0').uppercase()
    }

    private fun bootstrapFailure(code: String) = DownloadBootstrapResult.Failure(
        AppError(AppErrorKind.Validation, code),
    )

    private fun transferFailure(code: String) = DownloadTransferResult.Failure(
        AppError(AppErrorKind.ProtocolViolation, code),
    )

    private class DownloadProtocolException(message: String) : Exception(message)

    private companion object {
        const val TRANSFER_BUFFER_BYTES = 64 * 1024
        val REDIRECT_STATUS_CODES = setOf(301, 302, 303, 307, 308)
        val CONTENT_RANGE = Regex("^bytes (\\d+)-(\\d+)/(\\d+)$")
        val DOWNLOADABLE_REFLOWABLE_FORMATS = setOf("epub", "mobi", "azw", "azw3", "prc", "txt")
        val IMAGE_MIME_TYPES = setOf("image/jpeg", "image/png", "image/gif", "image/webp")
    }
}

private fun allowedMimeTypes(readerType: DownloadReaderType): Set<String> = when (readerType) {
    DownloadReaderType.Reflowable -> setOf(
        "application/epub+zip",
        "application/x-mobipocket-ebook",
        "application/vnd.amazon.ebook",
        "application/x-fictionbook+xml",
        "text/plain",
    )
    DownloadReaderType.Pdf -> setOf("application/pdf", "application/octet-stream")
    DownloadReaderType.Comic -> setOf(
        "application/vnd.comicbook+zip",
        "application/x-cbz",
        "application/zip",
        "application/vnd.comicbook-rar",
        "application/x-cbr",
        "application/vnd.rar",
        "application/octet-stream",
    )
    DownloadReaderType.Audio -> setOf(
        "audio/aac", "audio/ac3", "audio/aiff", "audio/amr", "audio/basic",
        "audio/eac3", "audio/flac", "audio/mp4", "audio/mpeg", "audio/ogg",
        "audio/vnd.dts", "audio/vnd.rn-realaudio", "audio/wav", "audio/webm",
        "audio/x-matroska", "audio/x-ms-wma", "audio/x-adx", "audio/x-ape", "audio/x-aptx",
        "audio/x-aptxhd", "audio/x-caf", "audio/x-dff", "audio/x-dsf", "audio/x-g722",
        "audio/x-g726", "audio/x-gsm", "audio/x-lbc", "audio/x-mlp",
        "audio/x-mpc", "audio/x-oma", "audio/x-qcp", "audio/x-shn",
        "audio/x-sph", "audio/x-tak", "audio/x-thd", "audio/x-tta",
        "audio/x-voc", "audio/x-wv", "audio/x-xma",
    )
}

fun parseDownloadReaderType(value: String): DownloadReaderType = when (value.trim().lowercase()) {
    "reflowable" -> DownloadReaderType.Reflowable
    "pdf" -> DownloadReaderType.Pdf
    "comic" -> DownloadReaderType.Comic
    "audio" -> DownloadReaderType.Audio
    else -> throw IllegalArgumentException("Unsupported reader type")
}
