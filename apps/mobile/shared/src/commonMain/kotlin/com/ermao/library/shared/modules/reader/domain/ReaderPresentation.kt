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
    val navigationKey: String? = null,
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

fun resolveReaderChapterStates(
    units: List<ReaderChapterUnit>,
    currentSortOrder: Int?,
    progressPercent: Double,
): List<ReaderChapterState> {
    require(progressPercent.isFinite() && progressPercent in 0.0..100.0)
    require(currentSortOrder == null || currentSortOrder >= 0)
    return units.map { unit ->
        if (unit.href == null) return@map ReaderChapterState.Unread
        when {
            progressPercent >= 100.0 -> ReaderChapterState.Read
            currentSortOrder == null -> ReaderChapterState.Unread
            unit.sortOrder == currentSortOrder -> ReaderChapterState.Current
            unit.sortOrder < currentSortOrder -> ReaderChapterState.Read
            else -> ReaderChapterState.Unread
        }
    }
}

fun resolveReaderChapterStatesFromPresentation(
    units: List<ReaderChapterUnit>,
    presentation: ReaderPositionPresentation,
): List<ReaderChapterState> {
    require(presentation.displayPercent.isFinite() && presentation.displayPercent in 0.0..100.0)
    val currentSortOrder = presentation.chapter?.navigationKey
        ?.takeIf(String::isNotBlank)
        ?.let { navigationKey ->
            units
                .filter { it.href != null && it.navigationKey == navigationKey }
                .singleOrNull()
                ?.sortOrder
        }
    return resolveReaderChapterStates(
        units = units,
        progressPercent = presentation.displayPercent,
        currentSortOrder = currentSortOrder,
    )
}

private fun normalizeReaderProgressResourceHref(value: String): String =
    value.trim().replace('\\', '/').removePrefix("./").substringBefore('#')
