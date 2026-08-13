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
import com.ermao.library.shared.modules.downloads.domain.DownloadMediaKind
import com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
import com.ermao.library.shared.modules.downloads.domain.DownloadSource
import com.ermao.library.shared.modules.downloads.domain.isSafeMediaApiPath
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.get
import io.ktor.client.request.header
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
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

class KtorDownloadsGateway(
    private val apiClient: ApiClient,
) : DownloadsGateway {
    override suspend fun load(
        context: DownloadRequestContext,
        volumeId: String,
    ): DownloadBootstrapResult {
        if (volumeId.isBlank()) return bootstrapFailure("DOWNLOAD_VOLUME_ID_INVALID")
        return when (val response = apiClient.execute(
            ApiRequest(
                method = ApiMethod.Get,
                apiPath = "/api/reader/v4/volumes/${volumeId.encodePathSegment()}/bootstrap",
                responseDeserializer = JsonObject.serializer(),
            ),
        )) {
            is ApiResult.Failure -> DownloadBootstrapResult.Failure(response.error)
            is ApiResult.Success -> try {
                DownloadBootstrapResult.Success(
                    DownloadBootstrap(response.value.toBootstrapDescriptor(context, volumeId)),
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
        try {
            val source = request.descriptor.source
            val response = apiClient.authenticatedHttpClient().get(
                apiClient.resolveAuthenticatedApiPath(source.apiPath),
            ) {
                if (request.resumeFromBytes > 0) {
                    header(HttpHeaders.Range, "bytes=${request.resumeFromBytes}-")
                }
            }
            if (response.status.value in REDIRECT_STATUS_CODES) {
                response.bodyAsText()
                return transferFailure("DOWNLOAD_REDIRECT_REJECTED")
            }
            val responseContract = validateResponse(
                statusCode = response.status.value,
                contentLength = response.headers[HttpHeaders.ContentLength],
                contentRange = response.headers[HttpHeaders.ContentRange],
                expectedTotalBytes = source.totalBytes,
                resumeFromBytes = request.resumeFromBytes,
            ) ?: run {
                response.bodyAsChannel().cancel(null)
                return transferFailure("DOWNLOAD_RESPONSE_INVALID")
            }
            session = sink.begin(
                DownloadSinkRequest(
                    namespace = context.namespace,
                    taskId = request.taskId,
                    volumeId = request.descriptor.identity.volumeId,
                    contentFingerprint = request.descriptor.identity.contentFingerprint,
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
            return DownloadTransferResult.Success(
                CompletedTransfer(
                    localReference = localReference,
                    verifiedBytes = source.totalBytes,
                    etag = response.headers[HttpHeaders.ETag],
                    lastModified = response.headers[HttpHeaders.LastModified],
                ),
            )
        } catch (cancelled: CancellationException) {
            withContext(NonCancellable) { session?.abort() }
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            session?.abortSafely()
            return DownloadTransferResult.Failure(AppError(AppErrorKind.Timeout, "DOWNLOAD_TIMEOUT", timeout.message))
        } catch (storage: PlatformStorageException) {
            session?.abortSafely()
            return DownloadTransferResult.Failure(AppError(AppErrorKind.StorageFailure, "DOWNLOAD_STORAGE_FAILURE", storage.message))
        } catch (protocol: DownloadProtocolException) {
            session?.abortSafely()
            return DownloadTransferResult.Failure(AppError(AppErrorKind.ProtocolViolation, "DOWNLOAD_RESPONSE_INVALID", protocol.message))
        } catch (error: Throwable) {
            session?.abortSafely()
            return DownloadTransferResult.Failure(mapTransportError(error))
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
        expectedVolumeId: String,
    ): DownloadDescriptor {
        require(requiredLong("schemaVersion") == 4L) { "Unsupported Reader bootstrap schema" }
        val userId = requiredString("userId")
        require(userId == context.namespace.userId) { "Bootstrap user does not match download namespace" }
        val work = requiredObject("book")
        val mediaVersion = requiredObject("mediaVersion")
        val volume = requiredObject("volume")
        require(mediaVersion.requiredString("workId") == work.requiredString("id")) {
            "Bootstrap media version does not match work"
        }
        require(volume.requiredString("id") == expectedVolumeId) { "Bootstrap volume does not match request" }
        require(volume.requiredString("mediaVersionId") == mediaVersion.requiredString("id")) {
            "Bootstrap volume does not match media version"
        }
        val readerType = parseDownloadReaderType(requiredString("readerType"))
        require(parseDownloadReaderType(volume.requiredString("readerType")) == readerType) {
            "Bootstrap reader type is inconsistent"
        }
        val mediaKind = parseDownloadMediaKind(mediaVersion.requiredString("mediaKind"))
        require(mediaKind.isCompatibleWith(readerType)) { "Bootstrap media kind is inconsistent" }
        val files = this["files"] as? JsonArray ?: throw IllegalArgumentException("Bootstrap files are missing")
        val fileUrl = requiredString("fileUrl")
        require(fileUrl.isSafeMediaApiPath()) { "Bootstrap file URL is invalid" }
        val volumeFormat = volume.requiredString("format")
        val sourceFiles = files.map { it as? JsonObject ?: throw IllegalArgumentException("Bootstrap file is invalid") }
        val expectedKind = if (readerType == DownloadReaderType.Reflowable) {
            val sourceFormat = requiredString("sourceFormat").trim().lowercase()
            require(sourceFormat in DOWNLOADABLE_REFLOWABLE_FORMATS) { "Unsupported reflowable source format" }
            require(volumeFormat.equals(sourceFormat, ignoreCase = true)) { "Bootstrap source format is inconsistent" }
            sourceFormat.uppercase()
        } else {
            volumeFormat.uppercase()
        }
        val sourceFile = sourceFiles
            .sortedWith(compareBy<JsonObject>({ it.requiredNonNegativeInt("sortOrder") }, { it.requiredString("id") }))
            .firstOrNull { it.requiredString("kind").equals(expectedKind, ignoreCase = true) }
            ?: throw IllegalArgumentException("Bootstrap publication file is missing")
        require(sourceFile.requiredString("url").isSafeMediaApiPath()) { "Bootstrap publication URL is invalid" }
        val sourceSize = sourceFile.requiredLong("sizeBytes")
        val sourceMime = sourceFile.requiredString("mimeType").lowercase()
        if (readerType == DownloadReaderType.Reflowable) {
            require(sourceMime in allowedReflowableMimeTypes(expectedKind)) {
                "Bootstrap publication MIME type is inconsistent"
            }
        }
        val contentFingerprint = requiredString("contentFingerprint")
        require(contentFingerprint.matches(CONTENT_FINGERPRINT)) { "Bootstrap content fingerprint is invalid" }
        return DownloadDescriptor(
            identity = DownloadIdentity(
                namespace = context.namespace,
                workId = work.requiredString("id"),
                volumeId = expectedVolumeId,
                contentFingerprint = contentFingerprint,
            ),
            workTitle = work.requiredString("title"),
            workAuthor = work.optionalString("author"),
            coverApiPath = work.optionalString("coverUrl"),
            volumeTitle = volume.requiredString("title"),
            format = volumeFormat,
            readerType = readerType,
            source = DownloadSource(
                apiPath = fileUrl,
                mimeType = sourceMime,
                totalBytes = sourceSize,
            ),
            mediaVersionId = mediaVersion.requiredString("id"),
            mediaKind = mediaKind.wireValue,
            mediaVersionCompleted = mediaVersion.requiredBoolean("completed"),
            volumeIndex = volume.optionalDouble("volumeIndex"),
            volumeSortOrder = volume.requiredNonNegativeInt("sortOrder"),
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

    private fun JsonObject.requiredBoolean(name: String): Boolean =
        this[name]?.jsonPrimitive?.booleanOrNull
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
        val character = byte.toInt().toChar()
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
        val DOWNLOADABLE_REFLOWABLE_FORMATS = setOf("epub", "mobi", "azw", "azw3", "prc")
        val CONTENT_FINGERPRINT = Regex("^sha256:[0-9a-f]{64}$")
    }
}

private fun allowedReflowableMimeTypes(kind: String): Set<String> = when (kind) {
    "EPUB" -> setOf("application/epub+zip", "application/octet-stream")
    "MOBI", "PRC" -> setOf("application/x-mobipocket-ebook", "application/octet-stream")
    "AZW", "AZW3" -> setOf(
        "application/vnd.amazon.ebook",
        "application/x-mobipocket-ebook",
        "application/octet-stream",
    )
    else -> emptySet()
}

fun parseDownloadReaderType(value: String): DownloadReaderType = when (value.trim().lowercase()) {
    "reflowable" -> DownloadReaderType.Reflowable
    "pdf" -> DownloadReaderType.Pdf
    "comic" -> DownloadReaderType.Comic
    "audio" -> DownloadReaderType.Audio
    else -> throw IllegalArgumentException("Unsupported reader type")
}

fun parseDownloadMediaKind(value: String): DownloadMediaKind = when (value.trim().uppercase()) {
    "EBOOK" -> DownloadMediaKind.Ebook
    "COMIC" -> DownloadMediaKind.Comic
    "AUDIOBOOK" -> DownloadMediaKind.Audiobook
    else -> throw IllegalArgumentException("Unsupported media kind")
}

private fun DownloadMediaKind.isCompatibleWith(readerType: DownloadReaderType): Boolean = when (readerType) {
    DownloadReaderType.Reflowable,
    DownloadReaderType.Pdf,
    -> this == DownloadMediaKind.Ebook
    DownloadReaderType.Comic -> this == DownloadMediaKind.Comic
    DownloadReaderType.Audio -> this == DownloadMediaKind.Audiobook
}
