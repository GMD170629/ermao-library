package com.ermao.library.shared.modules.reader.domain

/** A bookmark carries the same opaque position report used by progress. */
data class ReaderBookmark(
    val id: String,
    val position: ReaderPositionReport,
    val label: String,
    val createdAt: String,
) {
    init {
        require(id.isNotBlank())
        require(label.length <= 500)
        require(createdAt.isNotBlank())
    }

    val displayPercent: Double
        get() = position.presentation.displayPercent

    val currentHref: String?
        get() = position.presentation.currentHref
}

data class ReaderBookmarkSyncTarget(
    val serverIdentity: String,
    val resourceId: String,
) {
    init {
        require(serverIdentity.isNotBlank())
        require(resourceId.isNotBlank())
    }
}

fun mergeReaderBookmarks(
    local: List<ReaderBookmark>,
    remote: List<ReaderBookmark>,
    hasPendingLocalSnapshot: Boolean,
): List<ReaderBookmark> {
    if (hasPendingLocalSnapshot) return local.sortedWith(bookmarkOrder)
    return (local + remote)
        .associateBy(ReaderBookmark::id)
        .values
        .sortedWith(bookmarkOrder)
}

fun replacePendingReaderBookmarkSnapshot(
    currentPending: List<ReaderBookmark>?,
    latestLocal: List<ReaderBookmark>,
): List<ReaderBookmark> = latestLocal.sortedWith(bookmarkOrder)

private val bookmarkOrder = compareBy<ReaderBookmark>({ it.displayPercent }, { it.createdAt }, { it.id })
