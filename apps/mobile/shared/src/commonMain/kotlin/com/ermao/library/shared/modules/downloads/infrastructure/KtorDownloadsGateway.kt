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
import com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult
import com.ermao.library.shared.modules.downloads.application.DownloadBundleByteSink
import com.ermao.library.shared.modules.downloads.application.DownloadBundleMemberSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadBundleSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadByteSink
import com.ermao.library.shared.modules.downloads.application.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.application.DownloadProgressObserver
import com.ermao.library.shared.modules.downloads.application.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.application.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferRequest
import com.ermao.library.shared.modules.downloads.application.DownloadTransferResult
import com.ermao.library.shared.modules.downloads.application.DownloadsGateway
import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadArtifactKind
import com.ermao.library.shared.modules.downloads.domain.DownloadBundleMember
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
import com.ermao.library.shared.modules.downloads.domain.DownloadSource
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.header
import io.ktor.client.request.prepareGet
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.HttpHeaders
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject

/** Original-asset transfers; metadata uses the Library contract without starting Reader. */
class KtorDownloadsGateway(
    private val apiClient: ApiClient,
) : DownloadsGateway {
    override suspend fun load(
        context: DownloadRequestContext,
        resourceId: String,
    ): DownloadBootstrapResult {
        if (resourceId.isBlank()) return bootstrapFailure("DOWNLOAD_RESOURCE_ID_INVALID")
        return try {
            val resourceResponse = apiClient.execute(ApiRequest(ApiMethod.Get,
                "/api/resources/${resourceId.encodePathSegment()}", JsonObject.serializer()))
            val resource = when (resourceResponse) {
                is ApiResult.Failure -> return DownloadBootstrapResult.Failure(resourceResponse.error)
                is ApiResult.Success -> com.ermao.library.shared.modules.library.LibraryContract.resourcePayload(resourceResponse.value)
            }
            require(resource.id == resourceId)
            val bookResponse = apiClient.execute(ApiRequest(ApiMethod.Get,
                "/api/books/${resource.bookId.encodePathSegment()}", JsonObject.serializer()))
            val book = when (bookResponse) {
                is ApiResult.Failure -> return DownloadBootstrapResult.Failure(bookResponse.error)
                is ApiResult.Success -> com.ermao.library.shared.modules.library.LibraryContract.bookPayload(bookResponse.value)
            }
            require(book.id == resource.bookId)
            DownloadBootstrapResult.Success(DownloadBootstrap(toDescriptor(context, resource, book)))
        } catch (error: IllegalArgumentException) {
            DownloadBootstrapResult.Failure(AppError(AppErrorKind.ProtocolViolation, "DOWNLOAD_DESCRIPTOR_INVALID", error.message))
        }
    }

    override suspend fun transfer(
        context: DownloadRequestContext,
        request: DownloadTransferRequest,
        sink: DownloadByteSink,
        progressObserver: DownloadProgressObserver?,
    ): DownloadTransferResult {
        require(context.namespace == request.descriptor.identity.namespace)
        return try {
            val descriptor = request.descriptor
            val completed = when (descriptor.artifactKind) {
                DownloadArtifactKind.SingleOriginalAsset -> transferAsset(
                    source = descriptor.source,
                    resumeFromBytes = request.resumeFromBytes,
                    preservePartialOnCancellation = request.preservePartialOnCancellation,
                    begin = { sink.begin(DownloadSinkRequest(context.namespace, request.taskId,
                        descriptor.identity.resourceId, descriptor.identity.assetId, descriptor.totalBytes, request.resumeFromBytes)) },
                    progress = { progressObserver?.onProgress(it, descriptor.totalBytes) },
                )
                DownloadArtifactKind.OriginalPageSet -> transferPageSet(context, request, sink, progressObserver)
            }
            DownloadTransferResult.Success(completed)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (timeout: HttpRequestTimeoutException) {
            DownloadTransferResult.Failure(AppError(AppErrorKind.Timeout, "DOWNLOAD_TIMEOUT", timeout.message))
        } catch (storage: PlatformStorageException) {
            DownloadTransferResult.Failure(AppError(AppErrorKind.StorageFailure, "DOWNLOAD_STORAGE_FAILURE", storage.message))
        } catch (protocol: DownloadProtocolException) {
            DownloadTransferResult.Failure(AppError(AppErrorKind.ProtocolViolation, "DOWNLOAD_RESPONSE_INVALID", protocol.message))
        } catch (error: Throwable) {
            // The transfer task is the transport containment boundary; the caller persists failure.
            DownloadTransferResult.Failure(mapTransportError(error))
        }
    }

    private suspend fun transferPageSet(
        context: DownloadRequestContext,
        request: DownloadTransferRequest,
        sink: DownloadByteSink,
        progressObserver: DownloadProgressObserver?,
    ): CompletedTransfer {
        val bundleSink = sink as? DownloadBundleByteSink
            ?: throw DownloadProtocolException("DOWNLOAD_BUNDLE_SINK_REQUIRED")
        val descriptor = request.descriptor
        val bundle = bundleSink.beginBundle(DownloadBundleSinkRequest(
            context.namespace, request.taskId, descriptor.identity.resourceId, descriptor.identity.assetId,
            descriptor.artifactKind, descriptor.bundleMembers.size, descriptor.totalBytes,
        ))
        try {
            var transferred = 0L
            for (member in descriptor.bundleMembers) {
                transferAsset(member.source, 0, false,
                    begin = { bundle.beginMember(DownloadBundleMemberSinkRequest(
                        member.assetId, member.sequenceIndex, member.source.mimeType, member.source.totalBytes,
                    )) },
                    progress = { progressObserver?.onProgress(transferred + it, descriptor.totalBytes) },
                )
                transferred += member.source.totalBytes
            }
            return CompletedTransfer(bundle.commit(), transferred, null, null)
        } catch (error: Throwable) {
            withContext(NonCancellable) {
                try { bundle.abort() } catch (cleanup: Throwable) { error.addSuppressed(cleanup) }
            }
            throw error
        }
    }

    /** The only original-asset HTTP/body-copy implementation, including IMAGE_DIR members. */
    private suspend fun transferAsset(
        source: DownloadSource,
        resumeFromBytes: Long,
        preservePartialOnCancellation: Boolean,
        begin: suspend () -> DownloadByteSinkSession,
        progress: (Long) -> Unit,
    ): CompletedTransfer {
        var session: DownloadByteSinkSession? = null
        val expectedVersion = source.sourceModifiedAtMillis?.let { "${source.totalBytes}:$it" }
        try {
            return apiClient.authenticatedHttpClient().prepareGet(
                apiClient.resolveAuthenticatedApiPath(source.apiPath),
            ) {
                expectedVersion?.let { header("X-Asset-Version", it) }
                if (resumeFromBytes > 0) {
                    header(HttpHeaders.Range, "bytes=$resumeFromBytes-")
                }
            }.execute { response ->
                if (expectedVersion != null && response.headers["X-Asset-Version"] != expectedVersion) {
                    response.bodyAsChannel().cancel(null)
                    throw DownloadProtocolException("ASSET_VERSION_CHANGED")
                }
                val contract = validateResponse(response.status.value,
                    response.headers[HttpHeaders.ContentLength], response.headers[HttpHeaders.ContentRange],
                    response.headers[HttpHeaders.ContentType], source.mimeType, source.totalBytes, resumeFromBytes,
                ) ?: run {
                    response.bodyAsChannel().cancel(null)
                    throw DownloadProtocolException("Download response does not match the original asset contract")
                }
                val active = begin().also { session = it }
                val channel = response.bodyAsChannel()
                val buffer = ByteArray(TRANSFER_BUFFER_BYTES)
                var received = 0L
                while (true) {
                    val count = channel.readAvailable(buffer, 0, buffer.size)
                    if (count < 0) break
                    if (count == 0) continue
                    received += count
                    if (received > contract.contentLength) throw DownloadProtocolException("Response exceeded Content-Length")
                    active.write(buffer.copyOf(count))
                    progress(resumeFromBytes + received)
                }
                if (received != contract.contentLength) throw DownloadProtocolException("Response ended before Content-Length")
                val reference = active.commit(source.totalBytes)
                require(reference.isNotBlank()) { "Sink returned an empty local reference" }
                CompletedTransfer(reference, source.totalBytes, response.headers[HttpHeaders.ETag], response.headers[HttpHeaders.LastModified])
            }
        } catch (error: Throwable) {
            withContext(NonCancellable) {
                try {
                    if (error is CancellationException && preservePartialOnCancellation) session?.pause() else session?.abort()
                } catch (cleanup: Throwable) { error.addSuppressed(cleanup) }
            }
            throw error
        }
    }

    private data class ResponseContract(val contentLength: Long)

    private fun validateResponse(
        statusCode: Int,
        contentLength: String?,
        contentRange: String?,
        contentType: String?,
        expectedMimeType: String,
        expectedTotalBytes: Long,
        resumeFromBytes: Long,
    ): ResponseContract? {
        val declaredLength = contentLength?.toLongOrNull()?.takeIf { it > 0 } ?: return null
        val normalizedContentType = contentType?.substringBefore(';')?.trim()?.lowercase() ?: return null
        if (normalizedContentType != expectedMimeType.lowercase()) return null
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

    private fun toDescriptor(
        context: DownloadRequestContext,
        resource: com.ermao.library.shared.modules.library.domain.Resource,
        book: com.ermao.library.shared.modules.library.domain.BookDetailSummary,
    ): DownloadDescriptor {
        val readerType = parseDownloadReaderType(resource.readerType)
        val assets = resource.assets.sortedWith(compareBy({ it.sortOrder ?: 0 }, { it.id }))
        require(assets.isNotEmpty() && assets.all { it.resourceId == resource.id })
        val primary = assets.firstOrNull { it.role.equals("PRIMARY", true) } ?: assets.first()
        val format = requireNotNull(primary.sourceFormat).lowercase()
        fun source(asset: com.ermao.library.shared.modules.library.domain.Asset): DownloadSource {
            val mime = requireNotNull(asset.mimeType).substringBefore(';').lowercase()
            require(mime in allowedMimeTypes(readerType) || (format == "image_dir" && mime in IMAGE_MIME_TYPES))
            return DownloadSource(requireNotNull(asset.url), mime, asset.sizeBytes, asset.mtimeMillis)
        }
        val pages = if (format == "image_dir") assets.filter { it.role.equals("PAGE", true) }.mapIndexed { index, asset ->
            require(asset.sortOrder == index)
            DownloadBundleMember(asset.id, index, source(asset))
        } else emptyList()
        require(format != "image_dir" || pages.isNotEmpty())
        return DownloadDescriptor(
            identity = DownloadIdentity(context.namespace, book.id, resource.id,
                if (format == "image_dir") "page-set:${resource.id}" else primary.id),
            bookTitle = book.title, bookAuthor = book.author, coverApiPath = book.coverUrl.takeIf(String::isNotBlank),
            resourceTitle = resource.title, format = format, readerType = readerType, source = source(primary),
            resourceIndex = resource.resourceIndex, resourceSortOrder = resource.sortOrder,
            artifactKind = if (pages.isEmpty()) DownloadArtifactKind.SingleOriginalAsset else DownloadArtifactKind.OriginalPageSet,
            members = pages,
        )
    }

    private fun String.encodePathSegment(): String = encodeToByteArray().joinToString("") { byte ->
        val character = (byte.toInt() and 0xff).toChar()
        if (character.isLetterOrDigit() || character in "-._~") character.toString()
        else "%" + byte.toUByte().toString(16).padStart(2, '0').uppercase()
    }

    private fun bootstrapFailure(code: String) = DownloadBootstrapResult.Failure(
        AppError(AppErrorKind.Validation, code),
    )

    private class DownloadProtocolException(message: String) : Exception(message)

    private companion object {
        const val TRANSFER_BUFFER_BYTES = 64 * 1024
        val CONTENT_RANGE = Regex("^bytes (\\d+)-(\\d+)/(\\d+)$")
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
    DownloadReaderType.Pdf -> setOf("application/pdf")
    DownloadReaderType.Comic -> setOf(
        "application/vnd.comicbook+zip",
        "application/x-cbz",
        "application/zip",
        "application/vnd.comicbook-rar",
        "application/x-cbr",
        "application/vnd.rar",
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
