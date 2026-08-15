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

    data class Failure(val code: String, val recoverable: Boolean) : ComicPageReadResult
}

interface ComicPageServerPort {
    suspend fun read(
        source: RemoteComicReaderSource,
        pageIndex: Int,
        variant: ReaderComicImageVariant,
    ): ComicPageReadResult
}
