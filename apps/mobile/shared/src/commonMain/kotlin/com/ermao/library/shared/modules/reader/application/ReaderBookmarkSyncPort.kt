package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderBookmark
import com.ermao.library.shared.modules.reader.domain.ReaderBookmarkSyncTarget

data class ReaderBookmarkSyncResponse(
    val succeeded: Boolean,
    val bookmarks: List<ReaderBookmark> = emptyList(),
    val failureCode: String? = null,
) {
    init {
        require(succeeded == (failureCode == null))
        require(failureCode == null || failureCode.isNotBlank())
    }
}

interface ReaderBookmarkSyncPort {
    suspend fun load(target: ReaderBookmarkSyncTarget): ReaderBookmarkSyncResponse

    suspend fun replace(
        target: ReaderBookmarkSyncTarget,
        bookmarks: List<ReaderBookmark>,
    ): ReaderBookmarkSyncResponse
}
