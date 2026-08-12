package com.ermao.library.features.content.model

import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.ContentSource
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary

fun ContentResult.Content<*>.freshness(): ContentFreshness = when {
    isStale -> ContentFreshness.Stale
    source == ContentSource.Cache -> ContentFreshness.Cached
    else -> ContentFreshness.Fresh
}

fun WorkSummary.toCard(): WorkCard = WorkCard(
    id = id,
    title = title,
    author = author,
    coverUrl = coverUrl,
    mediaKinds = availableMediaKinds.map { it.wireValue },
    progressPercent = progress.toInt().takeIf { it > 0 },
)

fun HomeSnapshot.toUiContent(): HomeContent {
    val continueItem = when (val section = continueReading) {
        is HomeSection.Content -> section.value
        is HomeSection.Failure -> null
    }
    val readingItems = when (val section = recentReading) {
        is HomeSection.Content -> section.value
        is HomeSection.Failure -> emptyList()
    }
    val addedItems = when (val section = recentAdded) {
        is HomeSection.Content -> section.value
        is HomeSection.Failure -> emptyList()
    }
    return HomeContent(
        continueReading = continueItem?.let {
            ContinueReadingCard(
                work = WorkCard(
                    id = it.workId,
                    title = it.title,
                    author = it.author,
                    coverUrl = it.coverUrl,
                    mediaKinds = listOf(it.mediaKind.wireValue),
                    progressPercent = it.progress.toInt().takeIf { percent -> percent > 0 },
                ),
                volumeTitle = it.volumeTitle,
                positionLabel = null,
                lastReadLabel = it.lastReadAt,
            )
        },
        recentReading = readingItems.map(WorkSummary::toCard),
        recentAdded = addedItems.map(WorkSummary::toCard),
    )
}

fun HomeSnapshot.hasSectionFailure(): Boolean =
    continueReading is HomeSection.Failure || recentReading is HomeSection.Failure || recentAdded is HomeSection.Failure

fun WorkDetailSummary.toUiContent(): WorkDetailContent = WorkDetailContent(
    work = WorkCard(
        id = id,
        title = title,
        author = author,
        coverUrl = coverUrl,
        mediaKinds = availableMediaKinds.map { it.wireValue },
        progressPercent = (activeMedia?.progress?.toInt()
            ?: mediaVersions.flatMap { it.volumes }.maxOfOrNull { it.progress.toInt() })?.takeIf { it > 0 },
    ),
    seriesId = seriesFacet?.id,
    seriesName = seriesFacet?.name ?: seriesName,
    authorFacetId = authorFacets.firstOrNull()?.id,
    description = description,
    tags = tags,
    media = mediaVersions.map { media ->
        MediaContent(
            kind = media.mediaKind.wireValue,
            volumes = media.volumes.map { volume ->
                VolumeContent(
                    id = volume.id,
                    title = volume.title,
                    format = volume.format,
                    sizeBytes = volume.sizeBytes,
                    progressPercent = volume.progress.toInt().takeIf { it > 0 },
                    readable = volume.readable,
                    selected = volume.id == continueVolumeId,
                )
            },
        )
    },
    selectedMediaKind = recentMediaKind?.wireValue,
    completed = completed,
    readingUnits = (readingUnits.ifEmpty { activeMedia?.units.orEmpty() })
        .distinctBy { unit -> unit.id }
        .sortedBy { unit -> unit.sortOrder }
        .map { unit ->
            ReadingUnitContent(
                id = unit.id,
                title = unit.title?.takeIf(String::isNotBlank) ?: unit.id,
                progressPercent = activeMedia?.takeIf { active ->
                    active.currentChapterTitle == unit.title
                }?.progress?.toInt(),
            )
        },
)

fun ContentSort.toShared(): com.ermao.library.shared.modules.library.LibrarySort = when (this) {
    ContentSort.RecentAdded -> com.ermao.library.shared.modules.library.LibrarySort.RecentlyAdded
    ContentSort.RecentReading -> com.ermao.library.shared.modules.library.LibrarySort.RecentlyRead
    ContentSort.Title -> com.ermao.library.shared.modules.library.LibrarySort.Title
    ContentSort.Author -> com.ermao.library.shared.modules.library.LibrarySort.Author
}

fun LibraryScope.toFacetKind(): com.ermao.library.shared.modules.library.domain.FacetKind =
    if (this == LibraryScope.Series) com.ermao.library.shared.modules.library.domain.FacetKind.Series
    else com.ermao.library.shared.modules.library.domain.FacetKind.Author
