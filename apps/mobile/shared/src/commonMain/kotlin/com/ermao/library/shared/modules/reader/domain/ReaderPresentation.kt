package com.ermao.library.shared.modules.reader.domain

data class ReaderProgressPresentationUpdate(
    val namespaceKey: String,
    val workId: String,
    val volumeId: String,
    val percent: Double,
    val currentHref: String,
    val chapterTitle: String?,
    val capturedAtEpochMillis: Long,
) {
    init {
        require(namespaceKey.isNotBlank() && workId.isNotBlank() && volumeId.isNotBlank())
        require(percent.isFinite() && percent in 0.0..100.0)
        require(currentHref.isNotBlank())
        require(capturedAtEpochMillis >= 0)
    }
}

data class ReaderChapterUnit(
    val href: String?,
    val sortOrder: Int,
)

enum class ReaderChapterState { Current, Read, Unread }

data class ReaderChapterListMetadata(
    val page: Int = 1,
    val pageSize: Int,
    val currentIndex: Int? = null,
) {
    init {
        require(page >= 1 && pageSize >= 1)
        require(currentIndex == null || currentIndex >= 0)
    }
}

fun resolveReaderChapterStates(
    units: List<ReaderChapterUnit>,
    currentHref: String?,
    currentSortOrder: Int?,
    progressPercent: Double,
    metadata: ReaderChapterListMetadata = ReaderChapterListMetadata(pageSize = maxOf(1, units.size)),
): List<ReaderChapterState> {
    require(progressPercent.isFinite() && progressPercent in 0.0..100.0)
    if (progressPercent >= 100) return List(units.size) { ReaderChapterState.Read }
    val normalizedCurrent = currentHref?.let(::normalizeReaderChapterHref)?.takeIf(String::isNotEmpty)
    val exactMatches = normalizedCurrent?.let { target ->
        units.indices.filter { index ->
            units[index].href?.let(::normalizeReaderChapterHref) == target
        }
    }.orEmpty()
    val activeIndex = exactMatches.singleOrNull()
    val activeSortOrder = activeIndex?.let { units[it].sortOrder } ?: currentSortOrder
    val pageOffset = (metadata.page - 1) * metadata.pageSize
    return units.mapIndexed { index, unit ->
        val globalIndex = pageOffset + index
        when {
            metadata.currentIndex != null && globalIndex == metadata.currentIndex -> ReaderChapterState.Current
            metadata.currentIndex != null && globalIndex < metadata.currentIndex -> ReaderChapterState.Read
            metadata.currentIndex != null -> ReaderChapterState.Unread
            activeIndex == index -> ReaderChapterState.Current
            activeIndex == null && activeSortOrder != null && unit.sortOrder == activeSortOrder -> ReaderChapterState.Current
            activeSortOrder != null && unit.sortOrder < activeSortOrder -> ReaderChapterState.Read
            else -> ReaderChapterState.Unread
        }
    }
}

private fun normalizeReaderChapterHref(value: String): String {
    val normalized = value.trim().replace('\\', '/').removePrefix("./")
    val parts = normalized.split('#', limit = 2)
    val path = parts[0].lowercase()
    return if (parts.size == 2) "$path#${parts[1]}" else path
}
