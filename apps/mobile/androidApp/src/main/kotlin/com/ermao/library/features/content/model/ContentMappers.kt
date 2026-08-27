package com.ermao.library.features.content.model

import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.Resource
import java.time.Instant

fun BookSummary.toCard(): BookCard = BookCard(
    id = id,
    title = title,
    author = author.orEmpty(),
    coverUrl = coverUrl,
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
                book = BookCard(
                    id = it.bookId,
                    title = it.title,
                    author = it.author.orEmpty(),
                    coverUrl = it.coverUrl,
                    progressPercent = it.progress.toInt().takeIf { percent -> percent > 0 },
                ),
                resourceTitle = it.resourceTitle,
                positionLabel = it.chapter,
                lastReadAtEpochMillis = it.lastReadAt.toEpochMillisOrNull(),
                resumeResourceId = it.resumeResourceId,
            )
        },
        recentReading = readingItems.map(BookSummary::toCard),
        recentAdded = addedItems.map(BookSummary::toCard),
    )
}

internal fun String?.toEpochMillisOrNull(): Long? = this
    ?.trim()
    ?.takeIf(String::isNotEmpty)
    ?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }

fun HomeSnapshot.hasSectionFailure(): Boolean =
    continueReading is HomeSection.Failure ||
        recentReading is HomeSection.Failure ||
        recentAdded is HomeSection.Failure

fun BookDetailSummary.toUiContent(): BookDetailContent {
    val mappedResources = resources.map { resource ->
        resource.toUiContent(resource.id == continueResourceId)
    }
    val selectedResourceId = continueResourceId
    return BookDetailContent(
        book = BookCard(
            id = id,
            title = title,
            author = author.orEmpty(),
            coverUrl = coverUrl,
            progressPercent = continueResourceProgress.toInt().takeIf { it > 0 },
        ),
        seriesId = seriesFacet?.id,
        seriesName = seriesFacet?.name ?: seriesName,
        seriesIndex = seriesIndex,
        authorFacetId = authorFacets.firstOrNull()?.id,
        description = description,
        tags = tags,
        resources = mappedResources,
        selectedResourceId = selectedResourceId,
        completed = completed,
        readingUnits = emptyList(),
        continueResourceId = continueResourceId,
    )
}

fun Resource.toUiContent(selected: Boolean = false): ResourceContent = ResourceContent(
    id = id,
    sourceNodeId = sourceNodeId,
    title = title,
    format = format,
    readerType = readerType,
    description = description,
    importStatus = importStatus,
    importError = importError,
    resourceIndex = resourceIndex,
    sortOrder = sortOrder,
    publisher = publisher,
    publishedAt = publishedAt,
    language = language,
    isbn = isbn,
    identifier = identifier,
    narrator = narrator,
    pageCount = pageCount,
    chapterCount = chapterCount,
    durationMillis = durationMillis,
    trackCount = trackCount,
    metadataSource = null,
    kindleSendAvailable = kindleSendAvailable,
    assets = assets.map { asset ->
        AssetContent(
            id = asset.id,
            path = asset.downloadUrl ?: asset.url.orEmpty(),
            sizeBytes = asset.sizeBytes,
            displaySize = asset.displaySize,
        )
    },
    coverUrl = coverUrl,
    sizeBytes = sizeBytes,
    progressPercent = progress.toInt().takeIf { it > 0 },
    readable = readable,
    selected = selected,
)

fun ContentSort.toShared(): com.ermao.library.shared.modules.library.LibrarySort = when (this) {
    ContentSort.RecentAdded -> com.ermao.library.shared.modules.library.LibrarySort.RecentlyAdded
    ContentSort.RecentReading -> com.ermao.library.shared.modules.library.LibrarySort.RecentlyRead
    ContentSort.Title -> com.ermao.library.shared.modules.library.LibrarySort.Title
    ContentSort.Author -> com.ermao.library.shared.modules.library.LibrarySort.Author
}

fun LibraryScope.toFacetKind(): com.ermao.library.shared.modules.library.domain.FacetKind =
    if (this == LibraryScope.Series) {
        com.ermao.library.shared.modules.library.domain.FacetKind.Series
    } else {
        com.ermao.library.shared.modules.library.domain.FacetKind.Author
    }
