package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.Serializable

@Serializable
data class ReaderBookmarkLocation(
    val resourceKey: String,
    val progression: Double? = null,
    /** Backend bookmark morphology: reflow, comic, pdf, or audio. */
    val kind: String = "reflow",
    /** Comic page number, one-based as required by the bookmark HTTP contract. */
    val pageIndex: Int? = null,
    /** PDF page number, one-based as required by the bookmark HTTP contract. */
    val pageNumber: Int? = null,
    /** Audio asset identity. */
    val assetId: String? = null,
    val chapterId: String? = null,
    /** Audio position in milliseconds. */
    val positionMs: Long? = null,
) {
    init {
        require(resourceKey.isNotBlank())
        require(progression == null || progression.isFinite() && progression in 0.0..1.0)
        require(kind in SUPPORTED_KINDS)
        when (kind) {
            "reflow" -> {
                require(pageIndex == null && pageNumber == null && assetId == null && chapterId == null && positionMs == null)
            }
            "comic" -> {
                require(progression == null && pageIndex != null && pageIndex >= 1)
                require(pageNumber == null && assetId == null && chapterId == null && positionMs == null)
            }
            "pdf" -> {
                require(progression == null && pageNumber != null && pageNumber >= 1)
                require(pageIndex == null && assetId == null && chapterId == null && positionMs == null)
            }
            "audio" -> {
                require(progression == null && pageIndex == null && pageNumber == null)
                require(assetId != null && assetId.isNotBlank() && positionMs != null && positionMs >= 0)
                require(chapterId == null || chapterId.isNotBlank())
            }
        }
    }

    companion object {
        private val SUPPORTED_KINDS = setOf("reflow", "comic", "pdf", "audio")

        fun reflow(resourceKey: String, progression: Double? = null): ReaderBookmarkLocation =
            ReaderBookmarkLocation(resourceKey = resourceKey, progression = progression)

        fun comic(pageIndex: Int): ReaderBookmarkLocation = ReaderBookmarkLocation(
            resourceKey = "page-$pageIndex",
            kind = "comic",
            pageIndex = pageIndex,
        )

        fun pdf(pageNumber: Int): ReaderBookmarkLocation = ReaderBookmarkLocation(
            resourceKey = "page-$pageNumber",
            kind = "pdf",
            pageNumber = pageNumber,
        )

        fun audio(assetId: String, chapterId: String? = null, positionMs: Long): ReaderBookmarkLocation =
            ReaderBookmarkLocation(
                resourceKey = assetId,
                kind = "audio",
                assetId = assetId,
                chapterId = chapterId,
                positionMs = positionMs,
            )
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

private val bookmarkOrder = compareBy<ReaderBookmark>({ it.percent }, { it.createdAt }, { it.id })
