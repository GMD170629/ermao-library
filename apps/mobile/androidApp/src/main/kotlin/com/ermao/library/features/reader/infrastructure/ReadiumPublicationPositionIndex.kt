package com.ermao.library.features.reader.infrastructure

import kotlin.math.abs
import org.readium.r2.shared.publication.Locator

internal data class ReflowablePositionPoint(
    val resourceKey: String,
    val progression: Double?,
    val totalProgression: Double,
    val position: Int?,
)

/** One authoritative index for Android reflowable progress display and seeking. */
internal class ReadiumPublicationPositionIndex private constructor(
    private val entries: List<Entry>,
) {
    private val points = entries.map(Entry::point)

    fun totalProgression(locator: Locator): Double? {
        locator.locations.totalProgression?.let { return it.coerceIn(0.0, 1.0) }
        return resolveReflowableTotalProgression(
            resourceKey = locator.href.toString(),
            progression = locator.locations.progression,
            position = locator.locations.position,
            points = points,
        )
    }

    fun nearestLocator(totalProgression: Double): Locator? = nearestReflowablePositionIndex(
        totalProgression,
        points.map(ReflowablePositionPoint::totalProgression),
    )?.let(entries::get)?.locator

    companion object {
        val Empty = ReadiumPublicationPositionIndex(emptyList())

        fun from(positions: List<Locator>): ReadiumPublicationPositionIndex = ReadiumPublicationPositionIndex(
            positions.mapNotNull { locator ->
                val total = locator.locations.totalProgression ?: return@mapNotNull null
                Entry(
                    locator = locator,
                    point = ReflowablePositionPoint(
                        resourceKey = normalizeResourceKey(locator.href.toString()),
                        progression = locator.locations.progression,
                        totalProgression = total.coerceIn(0.0, 1.0),
                        position = locator.locations.position,
                    ),
                )
            },
        )
    }

    private data class Entry(
        val locator: Locator,
        val point: ReflowablePositionPoint,
    )
}

internal fun nearestReflowablePositionIndex(
    totalProgression: Double,
    positionProgressions: List<Double>,
): Int? = positionProgressions.indices.minByOrNull { index ->
    abs(positionProgressions[index] - totalProgression)
}

internal fun resolveReflowableTotalProgression(
    resourceKey: String,
    progression: Double?,
    position: Int?,
    points: List<ReflowablePositionPoint>,
): Double? {
    if (points.isEmpty()) return null
    position?.let { targetPosition ->
        points.firstOrNull { it.position == targetPosition }?.let { return it.totalProgression }
    }
    val matching = points
        .filter { it.resourceKey == normalizeResourceKey(resourceKey) }
        .sortedBy { it.progression ?: 0.0 }
    if (matching.isEmpty()) return null
    val target = progression ?: return matching.first().totalProgression
    val lower = matching.lastOrNull { (it.progression ?: 0.0) <= target }
    val upper = matching.firstOrNull { (it.progression ?: 0.0) >= target }
    if (lower == null) return upper?.totalProgression
    if (upper == null) return lower.totalProgression
    val lowerProgression = lower.progression ?: return lower.totalProgression
    val upperProgression = upper.progression ?: return upper.totalProgression
    if (upperProgression <= lowerProgression) return lower.totalProgression
    val fraction = ((target - lowerProgression) / (upperProgression - lowerProgression)).coerceIn(0.0, 1.0)
    return (lower.totalProgression +
        (upper.totalProgression - lower.totalProgression) * fraction).coerceIn(0.0, 1.0)
}

private fun normalizeResourceKey(value: String): String = value.substringBefore('#')
