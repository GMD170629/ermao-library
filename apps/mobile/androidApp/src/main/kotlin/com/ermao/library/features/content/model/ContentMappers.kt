package com.ermao.library.features.content.model

import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.library.domain.Volume
import java.time.Instant

fun ContentResult.Content<*>.freshness(): ContentFreshness = ContentFreshness.Fresh

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
                lastReadAtEpochMillis = it.lastReadAt.toEpochMillisOrNull(),
                resumeVolumeId = it.resumeVolumeId,
            )
        },
        recentReading = readingItems.map(WorkSummary::toCard),
        recentAdded = addedItems.map(WorkSummary::toCard),
    )
}

internal fun String?.toEpochMillisOrNull(): Long? = this
    ?.trim()
    ?.takeIf(String::isNotEmpty)
    ?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }

fun HomeSnapshot.hasSectionFailure(): Boolean =
    continueReading is HomeSection.Failure || recentReading is HomeSection.Failure || recentAdded is HomeSection.Failure

fun WorkDetailSummary.toUiContent(): WorkDetailContent {
    val continueVolumeId = continueVolumeId
    val versions = versions.map { version ->
        VersionContent(
            id = version.id,
            sourceKey = version.sourceKey,
            sourceName = version.sourceName,
            volumeCount = version.volumeCount,
            volumes = version.volumes.map { volume -> volume.toUiContent(volume.id == continueVolumeId) },
        )
    }
    val selectedVersionId = versions.firstOrNull { version ->
        version.volumes.any { it.id == continueVolumeId }
    }?.id ?: versions.firstOrNull()?.id
    return WorkDetailContent(
    work = WorkCard(
        id = id,
        title = title,
        author = author,
        coverUrl = coverUrl,
        mediaKinds = versions.flatMap { version ->
            version.volumes.mapNotNull { volume -> volume.suggestedMediaKind }
        }.distinct(),
        progressPercent = continueVolumeProgress.toInt().takeIf { it > 0 },
    ),
    seriesId = seriesFacet?.id,
    seriesName = seriesFacet?.name ?: seriesName,
    seriesIndex = seriesIndex,
    authorFacetId = authorFacets.firstOrNull()?.id,
    description = description,
    tags = tags,
    versions = versions,
    selectedVersionId = selectedVersionId,
    completed = completed,
    readingUnits = emptyList(),
    )
}

fun Volume.toUiContent(selected: Boolean = false): VolumeContent = VolumeContent(
    id = id,
    title = title,
    format = format,
    readerType = readerType,
    versionId = versionId,
    volumeIndex = volumeIndex,
    sortOrder = sortOrder,
    publisher = publisher,
    publishedAt = publishedAt,
    language = language,
    isbn = isbn,
    identifier = identifier,
    narrator = narrator,
    pageCount = pageCount,
    metadataSource = origin,
    suggestedMediaKind = classification.suggestedMediaKind?.wireValue,
    kindleSendAvailable = kindleSendAvailable,
    files = files.map { file -> VolumeFileContent(file.id, file.path, file.sizeBytes, file.displaySize) },
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
    if (this == LibraryScope.Series) com.ermao.library.shared.modules.library.domain.FacetKind.Series
    else com.ermao.library.shared.modules.library.domain.FacetKind.Author
