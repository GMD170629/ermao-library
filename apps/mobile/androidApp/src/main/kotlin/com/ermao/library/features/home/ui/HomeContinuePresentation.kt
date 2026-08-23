package com.ermao.library.features.home.ui

import java.time.Instant
import java.time.ZoneId
import java.util.Locale

internal sealed interface HomeLastReadPresentation {
    val instant: Instant

    data class Today(override val instant: Instant) : HomeLastReadPresentation

    data class Yesterday(override val instant: Instant) : HomeLastReadPresentation

    data class Absolute(override val instant: Instant) : HomeLastReadPresentation
}

internal fun selectContinuePositionLabel(
    bookTitle: String,
    positionLabel: String?,
    resourceTitle: String?,
): String? {
    return sequenceOf(positionLabel, resourceTitle).firstNotNullOfOrNull { label ->
        label?.deduplicatedAgainst(bookTitle)
    }
}

private fun String.deduplicatedAgainst(bookTitle: String): String? {
    val candidate = trim().takeIf(String::isNotEmpty) ?: return null
    if (candidate.normalizedIdentityTitle() == bookTitle.normalizedIdentityTitle()) return null
    if (!candidate.startsWith(bookTitle, ignoreCase = true)) return candidate
    return candidate
        .drop(bookTitle.length)
        .trimStart { character -> character.isWhitespace() || character in ContinueLabelSeparators }
        .takeIf(String::isNotEmpty)
}

internal fun homeLastReadPresentation(
    lastReadAtEpochMillis: Long?,
    now: Instant,
    zoneId: ZoneId,
): HomeLastReadPresentation? {
    val instant = lastReadAtEpochMillis?.let(Instant::ofEpochMilli) ?: return null
    val lastRead = instant.atZone(zoneId)
    val today = now.atZone(zoneId).toLocalDate()
    return when (lastRead.toLocalDate()) {
        today -> HomeLastReadPresentation.Today(instant)
        today.minusDays(1) -> HomeLastReadPresentation.Yesterday(instant)
        else -> HomeLastReadPresentation.Absolute(instant)
    }
}

private fun String.normalizedIdentityTitle(): String =
    lowercase(Locale.ROOT).filterNot(Char::isWhitespace)

private val ContinueLabelSeparators: Set<Char> = setOf('-', '–', '—', '·', ':', '：', '/', '|')
