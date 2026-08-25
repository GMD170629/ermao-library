package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.domain.ActiveMedia
import com.ermao.library.shared.modules.library.domain.BookDetail
import com.ermao.library.shared.modules.library.domain.LocalProgressScope
import com.ermao.library.shared.modules.library.domain.PrimaryAction
import com.ermao.library.shared.modules.library.domain.ProgressExtra
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.ReadingUnitMetadata
import com.ermao.library.shared.modules.library.domain.ReadingUnitsPage
import com.ermao.library.shared.modules.library.domain.ResourceSection
import kotlinx.serialization.Serializable

/** Optional enriched detail projection used when a caller also loads navigation units. */
@Serializable
data class BookDetailPayloadWire(
    val book: BookWire,
    val readingUnits: List<ReadingUnitWire> = emptyList(),
    val resourceSections: List<ResourceSectionWire> = emptyList(),
    val readingUnitsPage: ReadingUnitsPageWire = ReadingUnitsPageWire(),
)

@Serializable
data class ReadingUnitWire(
    val id: String,
    val resourceId: String,
    val assetId: String? = null,
    val unitType: String,
    val title: String? = null,
    val href: String? = null,
    val mediaType: String? = null,
    val sortOrder: Int = 0,
    val startMs: Long? = null,
    val endMs: Long? = null,
    val durationMs: Long? = null,
    val width: Int? = null,
    val height: Int? = null,
    val size: Long? = null,
    val metadataJson: String? = null,
    val createdAt: String? = null,
    val updatedAt: String? = null,
)

@Serializable
data class ReadingUnitsPageWire(
    val page: Int = 1,
    val pageSize: Int = 50,
    val total: Int = 0,
    val totalPages: Int = 1,
)

@Serializable
data class ResourceSectionWire(
    val id: String,
    val resourceId: String,
    val title: String,
    val index: Double = 0.0,
    val assetId: String,
    val pageCount: Int = 0,
    val coverUrl: String = "",
    val progress: Double = 0.0,
    val lastReadAt: String? = null,
    val position: String? = null,
    val currentPage: Int? = null,
    val currentHref: String? = null,
    val currentSectionIndex: Int? = null,
    val currentChapterTitle: String? = null,
    val currentChapterIndex: Int? = null,
    val currentChapterSortOrder: Int? = null,
    val progressExtra: ProgressExtraWire = ProgressExtraWire(),
    val progressEstimated: Boolean = false,
)

@Serializable
data class ProgressExtraWire(
    val cfi: String? = null,
    val progression: Double? = null,
    val navigationKey: String? = null,
    val navigationFingerprint: String? = null,
    val sourceFormat: String? = null,
    val assetId: String? = null,
    val chapterId: String? = null,
    val positionMs: Long? = null,
    val resourceId: String? = null,
    val pageIndex: Double? = null,
    val chapterHref: String? = null,
    val currentHref: String? = null,
    val chapterSectionIndex: Double? = null,
    val sectionIndex: Double? = null,
    val chapterIndex: Double? = null,
    val chapterSortOrder: Double? = null,
    val chapterTitle: String? = null,
    val sectionPage: Double? = null,
    val sectionTotalPages: Double? = null,
    val sectionTotal: Double? = null,
    val locationCurrent: Double? = null,
    val locationNext: Double? = null,
    val locationTotal: Double? = null,
    val remainingSectionSeconds: Double? = null,
    val remainingTotalSeconds: Double? = null,
    val progressEstimated: Boolean? = null,
)

fun BookDetailPayloadWire.toDomain(): BookDetail {
    require(book.id.isNotBlank() && book.continueResourceProgress in 0.0..100.0)
    return BookDetail(
        id = book.id,
        sourceNodeId = book.sourceNodeId,
        title = book.title,
        author = book.author,
        description = book.description,
        publicationStatus = book.publicationStatus,
        trackingStatus = book.trackingStatus,
        tags = book.tags,
        seriesName = book.seriesName,
        seriesFacet = null,
        authorFacets = emptyList(),
        seriesIndex = book.seriesIndex,
        organized = book.organized,
        coverStatus = book.coverStatus,
        coverUrl = book.coverUrl,
        continueResourceId = book.continueResourceId,
        continueResourceTitle = book.continueResourceTitle,
        continueResourceProgress = book.continueResourceProgress,
        completed = book.completed,
        lastReadAt = null,
        addedAt = book.addedAt,
        resources = book.resources.map(ResourceWire::toDomain),
        readingUnits = readingUnits.map(ReadingUnitWire::toDomain),
        resourceSections = resourceSections.map(ResourceSectionWire::toDomain),
        readingUnitsPage = readingUnitsPage.toDomain(),
    )
}

fun ReadingUnitWire.toDomain(): ReadingUnit = ReadingUnit(
    id = id.also { require(it.isNotBlank()) },
    resourceId = resourceId.also { require(it.isNotBlank()) },
    assetId = assetId,
    unitType = unitType,
    title = title,
    href = href,
    mediaType = mediaType,
    sortOrder = sortOrder,
    startMillis = startMs,
    endMillis = endMs,
    durationMillis = durationMs,
    width = width,
    height = height,
    sizeBytes = size,
    metadata = ReadingUnitMetadata(
        exactNavigation = null,
        level = null,
        path = null,
        navigationKey = null,
        zipEntryName = null,
        idref = null,
        linear = null,
        properties = null,
        resourceIndex = null,
        trackIndex = null,
        pageNumber = null,
        sourceFileName = null,
        hrefBase = null,
        recovered = null,
    ),
    createdAt = createdAt,
    updatedAt = updatedAt,
)

private fun ReadingUnitsPageWire.toDomain(): ReadingUnitsPage {
    require(page >= 1 && pageSize >= 1 && total >= 0 && totalPages >= 1)
    return ReadingUnitsPage(page, pageSize, total, totalPages)
}

private fun ResourceSectionWire.toDomain(): ResourceSection {
    require(id.isNotBlank() && resourceId.isNotBlank() && progress in 0.0..100.0)
    return ResourceSection(
        id = id,
        resourceId = resourceId,
        title = title,
        index = index,
        assetId = assetId,
        pageCount = pageCount,
        coverUrl = coverUrl,
        progress = progress,
        lastReadAt = lastReadAt,
        position = position,
        currentPage = currentPage,
        currentHref = currentHref,
        currentSectionIndex = currentSectionIndex,
        currentChapterTitle = currentChapterTitle,
        currentChapterIndex = currentChapterIndex,
        currentChapterSortOrder = currentChapterSortOrder,
        progressExtra = progressExtra.toDomain(),
        progressEstimated = progressEstimated,
    )
}

internal fun ActiveMediaWire.toDomain(): ActiveMedia {
    require(selectedResourceId.isNotBlank() && progress in 0.0..100.0)
    return ActiveMedia(
        key = key,
        formatLabel = formatLabel,
        selectedResourceId = selectedResourceId,
        selectedResourceTitle = selectedResourceTitle,
        status = status,
        progressStatus = progressStatus,
        progress = progress,
        positionLabel = positionLabel,
        durationMillis = durationMs,
        narrator = narrator,
        primaryAction = primaryAction?.let { PrimaryAction(it.label, it.href) },
        units = units.map(ReadingUnitWire::toDomain),
        resources = resources.map(ResourceWire::toDomain),
        tracks = tracks.map(AssetWire::toDomain),
        localProgressScope = LocalProgressScope(localProgressScope.userId, localProgressScope.resourceId),
        currentHref = currentHref,
        currentSectionIndex = currentSectionIndex,
        currentChapterTitle = currentChapterTitle,
        currentChapterIndex = currentChapterIndex,
        currentPageNumber = currentPageNumber,
        currentChapterSortOrder = currentChapterSortOrder,
        progressExtra = progressExtra.toDomain(),
        progressEstimated = progressEstimated,
    )
}

@Serializable
internal data class ActiveMediaWire(
    val key: String,
    val formatLabel: String,
    val selectedResourceId: String,
    val selectedResourceTitle: String,
    val status: String,
    val progressStatus: String,
    val progress: Double,
    val positionLabel: String,
    val durationMs: Long? = null,
    val narrator: String? = null,
    val primaryAction: PrimaryActionWire? = null,
    val units: List<ReadingUnitWire> = emptyList(),
    val resources: List<ResourceWire> = emptyList(),
    val tracks: List<AssetWire> = emptyList(),
    val localProgressScope: LocalProgressScopeWire,
    val currentHref: String? = null,
    val currentSectionIndex: Int? = null,
    val currentChapterTitle: String? = null,
    val currentChapterIndex: Int? = null,
    val currentPageNumber: Int? = null,
    val currentChapterSortOrder: Int? = null,
    val progressExtra: ProgressExtraWire = ProgressExtraWire(),
    val progressEstimated: Boolean = false,
)

@Serializable
internal data class PrimaryActionWire(val label: String, val href: String)

@Serializable
internal data class LocalProgressScopeWire(val userId: String, val resourceId: String)

private fun ProgressExtraWire.toDomain(): ProgressExtra = ProgressExtra(
    cfi = cfi,
    progression = progression,
    navigationKey = navigationKey,
    navigationFingerprint = navigationFingerprint,
    sourceFormat = sourceFormat,
    assetId = assetId,
    chapterId = chapterId,
    positionMillis = positionMs,
    resourceId = resourceId,
    pageIndex = pageIndex,
    chapterHref = chapterHref,
    currentHref = currentHref,
    chapterSectionIndex = chapterSectionIndex,
    sectionIndex = sectionIndex,
    chapterIndex = chapterIndex,
    chapterSortOrder = chapterSortOrder,
    chapterTitle = chapterTitle,
    sectionPage = sectionPage,
    sectionTotalPages = sectionTotalPages,
    sectionTotal = sectionTotal,
    locationCurrent = locationCurrent,
    locationNext = locationNext,
    locationTotal = locationTotal,
    remainingSectionSeconds = remainingSectionSeconds,
    remainingTotalSeconds = remainingTotalSeconds,
    progressEstimated = progressEstimated,
)
