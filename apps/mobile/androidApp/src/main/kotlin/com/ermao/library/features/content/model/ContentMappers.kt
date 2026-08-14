package com.ermao.library.features.content.model

import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.ContentSource
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.reader.ReaderChapterListMetadata
import com.ermao.library.shared.modules.reader.ReaderChapterState
import com.ermao.library.shared.modules.reader.ReaderChapterUnit
import com.ermao.library.shared.modules.reader.resolveReaderChapterStates

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

fun WorkDetailSummary.toUiContent(): WorkDetailContent {
    val units = (readingUnits.ifEmpty { activeMedia?.units.orEmpty() })
        .distinctBy { unit -> unit.id }
        .sortedBy { unit -> unit.sortOrder }
    val page = readingUnitsPage
    val chapterStates = resolveReaderChapterStates(
        units = units.map {
            ReaderChapterUnit(
                href = it.href,
                sortOrder = it.sortOrder,
                readingOrderPosition = it.metadata.readingOrderPosition,
            )
        },
        currentHref = activeMedia?.currentHref,
        currentSortOrder = activeMedia?.currentChapterSortOrder,
        progressPercent = activeMedia?.progress?.coerceIn(0.0, 100.0) ?: if (completed) 100.0 else 0.0,
        metadata = ReaderChapterListMetadata(
            page = page?.page ?: 1,
            pageSize = page?.pageSize ?: maxOf(1, units.size),
            currentIndex = activeMedia?.currentChapterIndex,
        ),
    )
    return WorkDetailContent(
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
                    readerType = volume.readerType,
                    volumeIndex = volume.volumeIndex,
                    coverUrl = volume.coverUrl,
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
    readingUnits = units.mapIndexed { index, unit ->
            ReadingUnitContent(
                id = unit.id,
                title = unit.title?.takeIf(String::isNotBlank) ?: unit.id,
                progressPercent = activeMedia?.progress?.toInt()
                    ?.takeIf { chapterStates[index] == ReaderChapterState.Current },
                href = unit.href,
                sortOrder = unit.sortOrder,
                readingOrderPosition = unit.metadata.readingOrderPosition,
                readingState = when (chapterStates[index]) {
                    ReaderChapterState.Current -> ChapterReadingState.Current
                    ReaderChapterState.Read -> ChapterReadingState.Read
                    ReaderChapterState.Unread -> ChapterReadingState.Unread
                },
            )
        },
    )
}

fun ContentSort.toShared(): com.ermao.library.shared.modules.library.LibrarySort = when (this) {
    ContentSort.RecentAdded -> com.ermao.library.shared.modules.library.LibrarySort.RecentlyAdded
    ContentSort.RecentReading -> com.ermao.library.shared.modules.library.LibrarySort.RecentlyRead
    ContentSort.Title -> com.ermao.library.shared.modules.library.LibrarySort.Title
    ContentSort.Author -> com.ermao.library.shared.modules.library.LibrarySort.Author
}

fun LibraryScope.toFacetKind(): com.ermao.library.shared.modules.library.domain.FacetKind =
    if (this == LibraryScope.Series) com.ermao.library.shared.modules.library.domain.FacetKind.Series
    else com.ermao.library.shared.modules.library.domain.FacetKind.Author
