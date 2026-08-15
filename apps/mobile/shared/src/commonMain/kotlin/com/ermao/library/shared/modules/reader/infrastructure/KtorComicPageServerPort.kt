package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.reader.application.ComicPageReadResult
import com.ermao.library.shared.modules.reader.application.ComicPageServerPort
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import io.ktor.client.call.body
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.http.HttpHeaders
import kotlinx.coroutines.CancellationException

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
        val page = source.pages.getOrNull(pageIndex)
            ?: return@withClient ComicPageReadResult.Failure("COMIC_PAGE_OUT_OF_RANGE", false)
        try {
            val apiPath = source.pageApiPathTemplate.replace("{pageIndex}", pageIndex.toString())
            val response = client.authenticatedHttpClient().get(client.resolveAuthenticatedApiPath(apiPath)) {
                parameter("imageVariant", variant.wireValue)
            }
            if (response.status.value !in 200..299) {
                return@withClient ComicPageReadResult.Failure("COMIC_PAGE_LOAD_FAILED", true)
            }
            val mediaType = response.headers[HttpHeaders.ContentType]?.substringBefore(';')?.trim().orEmpty()
            if (!mediaType.startsWith("image/")) {
                return@withClient ComicPageReadResult.Failure("COMIC_PAGE_DECODE_FAILED", false)
            }
            val bytes = response.body<ByteArray>()
            if (bytes.isEmpty() || bytes.size > MAXIMUM_PAGE_BYTES) {
                return@withClient ComicPageReadResult.Failure("COMIC_OUT_OF_MEMORY_RISK", false)
            }
            val actualVariant = when (response.headers["X-Comic-Image-Variant"]) {
                ReaderComicImageVariant.DataSaver.wireValue -> ReaderComicImageVariant.DataSaver
                else -> ReaderComicImageVariant.Original
            }
            ComicPageReadResult.Content(pageIndex, mediaType, actualVariant, bytes)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: HttpRequestTimeoutException) {
            ComicPageReadResult.Failure("COMIC_PAGE_LOAD_FAILED", true)
        } catch (_: Throwable) {
            ComicPageReadResult.Failure("COMIC_PAGE_LOAD_FAILED", true)
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
        const val MAXIMUM_PAGE_BYTES = 128 * 1024 * 1024
    }
}
