package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.domain.RemoteComicReaderSource

sealed interface ComicPageReadResult {
    data class Content(
        val pageIndex: Int,
        val mediaType: String,
        val actualVariant: ReaderComicImageVariant,
        val bytes: ByteArray,
    ) : ComicPageReadResult

    data class Failure(
        val code: String,
        val recoverable: Boolean,
        val cause: Throwable? = null,
        val source: String = "server",
    ) : ComicPageReadResult {
        val readerError: com.ermao.library.shared.modules.reader.domain.ReaderError
            get() = com.ermao.library.shared.modules.reader.domain.ReaderError(
                com.ermao.library.shared.modules.reader.domain.readerErrorCodeForFailure(code, recoverable),
                mapOf("code" to code, "stage" to "resource", "source" to source),
                cause = cause,
            )
    }
}

interface ComicPageServerPort {
    suspend fun read(
        source: RemoteComicReaderSource,
        pageIndex: Int,
        variant: ReaderComicImageVariant,
    ): ComicPageReadResult
}
