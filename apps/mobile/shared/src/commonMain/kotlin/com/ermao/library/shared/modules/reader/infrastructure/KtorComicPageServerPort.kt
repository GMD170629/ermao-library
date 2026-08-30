package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.reader.application.ComicPageReadResult
import com.ermao.library.shared.modules.reader.application.ComicPageServerPort
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
import com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource
import com.ermao.library.shared.modules.servers.domain.ServerProfile

class KtorComicPageServerPort internal constructor(
    private val profile: ServerProfile,
    private val createClient: (ServerProfile) -> ApiClient,
) : ComicPageServerPort {
    constructor(profile: ServerProfile, clients: ApiClientFactory) : this(profile, clients::create)

    override suspend fun read(
        source: RemoteComicReaderSource,
        pageIndex: Int,
        variant: ReaderComicImageVariant,
    ): ComicPageReadResult = withClient { client ->
        if (source.pages.getOrNull(pageIndex) == null) {
            return@withClient ComicPageReadResult.Failure("COMIC_PAGE_OUT_OF_RANGE", false)
        }
        val path = source.pageApiPathTemplate.replace("{pageIndex}", pageIndex.toString())
        when (val result = client.loadAuthenticatedBinary(
            apiPath = path,
            maximumBytes = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES).toInt(),
            allowedMimeTypes = ReaderSafetyPolicy.comicProfile.allowedPageMimeTypes.toSet(),
            queryParameters = mapOf(
                "imageVariant" to listOf(variant.wireValue),
                "revision" to listOf(source.revision),
            ),
            errorCodeStatuses = ReaderHttpErrorStatuses.comic +
                (comicResourceChanged to setOf(PRECONDITION_FAILED_STATUS)),
        )) {
            is ApiResult.Failure -> ComicPageReadResult.Failure(
                if (result.error.kind == AppErrorKind.PayloadTooLarge) "COMIC_OUT_OF_MEMORY_RISK" else result.error.code,
                result.error.kind in setOf(AppErrorKind.NetworkUnavailable, AppErrorKind.Timeout, AppErrorKind.ServiceUnavailable),
                cause = result.error.cause,
                source = readerFailureSource(result.error.kind),
            )
            is ApiResult.Success -> {
                if (result.metadata.firstHeader(COMIC_REVISION_HEADER) != source.revision) {
                    return@withClient ComicPageReadResult.Failure(
                        comicResourceChanged,
                        recoverable = false,
                    )
                }
                val actualVariant = if (result.metadata.firstHeader("X-Comic-Image-Variant") == ReaderComicImageVariant.DataSaver.wireValue) {
                    ReaderComicImageVariant.DataSaver
                } else ReaderComicImageVariant.Original
                ComicPageReadResult.Content(pageIndex, result.value.mimeType, actualVariant, result.value.bytes)
            }
        }
    }

    private suspend fun <T> withClient(block: suspend (ApiClient) -> T): T {
        val client = createClient(profile)
        return try {
            block(client)
        } finally {
            client.close()
        }
    }

    private companion object {
        const val COMIC_REVISION_HEADER = "X-Comic-Revision"
        const val PRECONDITION_FAILED_STATUS = 412
        val comicResourceChanged = requireNotNull(
            ReaderSafetyPolicy.rule(ReaderSafetyRuleId.COMIC_MANIFEST_REVISION).errorCode,
        ).name
    }
}

private fun readerFailureSource(kind: AppErrorKind): String = when (kind) {
    AppErrorKind.NetworkUnavailable, AppErrorKind.Timeout, AppErrorKind.TlsFailure,
    AppErrorKind.Cancelled, AppErrorKind.ProtocolViolation -> "transport"
    AppErrorKind.StorageFailure -> "storage"
    else -> "server"
}
