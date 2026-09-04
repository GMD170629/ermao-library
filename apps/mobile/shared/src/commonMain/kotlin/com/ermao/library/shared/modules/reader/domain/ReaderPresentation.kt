package com.ermao.library.shared.modules.reader.domain

data class ReaderProgressPresentationUpdate(
    val namespaceKey: String,
    val bookId: String,
    val resourceId: String,
    val position: ReaderPositionReport,
    val capturedAtEpochMillis: Long,
) {
    init {
        require(namespaceKey.isNotBlank() && bookId.isNotBlank() && resourceId.isNotBlank())
        require(capturedAtEpochMillis >= 0)
    }

    /** Compatibility projection for surfaces that only render a percentage. */
    val presentation: ReaderPositionPresentation get() = position.presentation
}

data class ReaderChapterUnit(
    val href: String?,
    val sortOrder: Int,
    val readingOrderPosition: Int? = null,
) {
    init {
        require(readingOrderPosition == null || readingOrderPosition >= 1)
    }
}

enum class ReaderChapterState { Current, Read, Unread }

/**
 * Projects a reflowable resource position onto the whole Publication.
 *
 * The ordered href list is the canonical Reader bootstrap navigation order. A
 * resource-local progression is meaningful only after its href is resolved in
 * that order; it must never be used as a whole-book percentage on its own.
 */
fun resolveReflowableTotalProgressionFromNavigation(
    orderedResourceHrefs: List<String>,
    resourceHref: String?,
    resourceProgression: Double?,
    totalProgression: Double?,
): Double? {
    totalProgression
        ?.takeIf(Double::isFinite)
        ?.let { return it.coerceIn(0.0, 1.0) }
    if (orderedResourceHrefs.isEmpty()) return null
    val normalizedHref = resourceHref
        ?.let(::normalizeReaderProgressResourceHref)
        ?.takeIf(String::isNotEmpty)
        ?: return null
    val unitIndex = orderedResourceHrefs.indexOfFirst { href ->
        normalizeReaderProgressResourceHref(href) == normalizedHref
    }
    if (unitIndex < 0) return null
    val withinResource = resourceProgression
        ?.takeIf(Double::isFinite)
        ?.coerceIn(0.0, 1.0)
        ?: 0.0
    return ((unitIndex + withinResource) / orderedResourceHrefs.size).coerceIn(0.0, 1.0)
}

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

fun resolveReaderChapterStatesFromPresentation(
    units: List<ReaderChapterUnit>,
    presentation: ReaderPositionPresentation,
): List<ReaderChapterState> {
    require(presentation.displayPercent.isFinite() && presentation.displayPercent in 0.0..100.0)
    if (presentation.displayPercent >= 100.0) return List(units.size) { ReaderChapterState.Read }
    val chapterIndex = presentation.chapter?.index
        ?.takeIf { it in units.indices }
    if (chapterIndex != null) {
        return units.mapIndexed { index, _ ->
            when {
                index == chapterIndex -> ReaderChapterState.Current
                index < chapterIndex -> ReaderChapterState.Read
                else -> ReaderChapterState.Unread
            }
        }
    }
    return resolveReaderChapterStates(
        units = units,
        currentHref = presentation.chapter?.href ?: presentation.currentHref,
        currentSortOrder = null,
        progressPercent = presentation.displayPercent,
    )
}

private fun normalizeReaderChapterHref(value: String): String {
    val normalized = value.trim().replace('\\', '/').removePrefix("./")
    val parts = normalized.split('#', limit = 2)
    val path = parts[0].lowercase()
    return if (parts.size == 2) "$path#${parts[1]}" else path
}

private fun normalizeReaderProgressResourceHref(value: String): String =
    value.trim().replace('\\', '/').removePrefix("./").substringBefore('#')
