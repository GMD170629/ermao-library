package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

data class ReaderProgressPresentationUpdate(
    val namespaceKey: String,
    val workId: String,
    val volumeId: String,
    val percent: Double,
    val location: PublicationLocation,
    val chapterTitle: String?,
    val capturedAtEpochMillis: Long,
) {
    init {
        require(namespaceKey.isNotBlank() && workId.isNotBlank() && volumeId.isNotBlank())
        require(percent.isFinite() && percent in 0.0..100.0)
        require(capturedAtEpochMillis >= 0)
    }
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

fun resolveReaderChapterStatesFromLocation(
    units: List<ReaderChapterUnit>,
    location: PublicationLocation,
    progressPercent: Double,
): List<ReaderChapterState> {
    require(progressPercent.isFinite() && progressPercent in 0.0..100.0)
    if (progressPercent >= 100) return List(units.size) { ReaderChapterState.Read }
    val reflowable = location as? ReflowablePublicationLocation
        ?: return List(units.size) { ReaderChapterState.Unread }
    val locator = reflowable.engineLocator.toChapterLocatorOrNull()
        ?: return List(units.size) { ReaderChapterState.Unread }
    val activeIndex = resolveChapterIndex(units, locator)
        ?: return List(units.size) { ReaderChapterState.Unread }
    val activeSortOrder = units[activeIndex].sortOrder
    return units.mapIndexed { index, unit ->
        when {
            index == activeIndex -> ReaderChapterState.Current
            unit.sortOrder < activeSortOrder -> ReaderChapterState.Read
            else -> ReaderChapterState.Unread
        }
    }
}

private data class ReaderChapterLocator(
    val resourceHref: String,
    val anchoredHrefs: Set<String>,
    val position: Int?,
)

private fun EngineLocator.toChapterLocatorOrNull(): ReaderChapterLocator? {
    if (engine != ReaderEngine.Readium) return null
    val root = runCatching {
        Json.parseToJsonElement(payload.canonicalJson) as? JsonObject
    }.getOrNull() ?: return null
    val rawHref = (root["href"] as? JsonPrimitive)?.contentOrNull
        ?.takeIf(String::isNotBlank)
        ?: return null
    val resourceHref = normalizeReaderChapterResourceHref(rawHref)
    if (resourceHref.isEmpty()) return null
    val locations = root["locations"] as? JsonObject
    val fragments = buildSet {
        rawHref.substringAfter('#', "").takeIf(String::isNotBlank)?.let(::add)
        (locations?.get("fragments") as? JsonArray)?.forEach { item ->
            (item as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)?.let(::add)
        }
        listOf("fragment", "cfi").forEach { name ->
            (locations?.get(name) as? JsonPrimitive)?.contentOrNull
                ?.takeIf(String::isNotBlank)
                ?.let(::add)
        }
    }
    val anchoredHrefs = fragments.mapTo(linkedSetOf()) { fragment ->
        "$resourceHref#${fragment.removePrefix("#")}"
    }
    val position = (locations?.get("position") as? JsonPrimitive)?.intOrNull
        ?.takeIf { it >= 1 }
    return ReaderChapterLocator(resourceHref, anchoredHrefs, position)
}

private fun resolveChapterIndex(
    units: List<ReaderChapterUnit>,
    locator: ReaderChapterLocator,
): Int? {
    val exactMatches = units.indices.filter { index ->
        units[index].href?.let(::normalizeReaderChapterHref) in locator.anchoredHrefs
    }
    if (exactMatches.size == 1) return exactMatches.single()
    if (exactMatches.size > 1) return null

    val resourceMatches = units.indices.filter { index ->
        units[index].href?.let(::normalizeReaderChapterResourceHref) == locator.resourceHref
    }
    if (resourceMatches.size == 1) return resourceMatches.single()
    return resolveChapterIndexAtPosition(units, locator.position)
}

private fun resolveChapterIndexAtPosition(
    units: List<ReaderChapterUnit>,
    position: Int?,
): Int? {
    if (position == null) return null
    val candidates = units.indices.mapNotNull { index ->
        units[index].readingOrderPosition
            ?.takeIf { it <= position }
            ?.let { index to it }
    }
    val nearestPosition = candidates.maxOfOrNull { it.second } ?: return null
    return candidates.filter { it.second == nearestPosition }.map { it.first }.singleOrNull()
}

private fun normalizeReaderChapterHref(value: String): String {
    val normalized = value.trim().replace('\\', '/').removePrefix("./")
    val parts = normalized.split('#', limit = 2)
    val path = parts[0].lowercase()
    return if (parts.size == 2) "$path#${parts[1]}" else path
}

private fun normalizeReaderChapterResourceHref(value: String): String =
    normalizeReaderChapterHref(value).substringBefore('#')
