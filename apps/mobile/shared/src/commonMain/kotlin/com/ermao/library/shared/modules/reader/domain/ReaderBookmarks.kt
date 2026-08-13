package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.Serializable

@Serializable
data class ReaderBookmarkLocation(
    val resourceKey: String,
    val progression: Double? = null,
) {
    init {
        require(resourceKey.isNotBlank())
        require(progression == null || progression.isFinite() && progression in 0.0..1.0)
    }
}

@Serializable
data class ReaderBookmark(
    val id: String,
    val location: ReaderBookmarkLocation,
    val label: String,
    val percent: Double,
    val createdAt: String,
) {
    init {
        require(id.isNotBlank())
        require(label.length <= 500)
        require(percent.isFinite() && percent in 0.0..100.0)
        require(createdAt.isNotBlank())
    }
}

data class ReaderBookmarkSyncTarget(
    val serverIdentity: String,
    val volumeId: String,
    val contentFingerprint: String,
) {
    init {
        require(serverIdentity.isNotBlank())
        require(volumeId.isNotBlank())
        require(contentFingerprint.isNotBlank())
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

private val bookmarkOrder = compareBy<ReaderBookmark>({ it.percent }, { it.createdAt }, { it.id })
