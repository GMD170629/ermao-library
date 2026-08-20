package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.domain.ActiveMedia
import com.ermao.library.shared.modules.library.domain.LocalProgressScope
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.WorkVersion
import com.ermao.library.shared.modules.library.domain.PrimaryAction
import com.ermao.library.shared.modules.library.domain.ProgressExtra
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.ReadingUnitMetadata
import com.ermao.library.shared.modules.library.domain.ReadingUnitsPage
import com.ermao.library.shared.modules.library.domain.Volume
import com.ermao.library.shared.modules.library.domain.VolumeClassification
import com.ermao.library.shared.modules.library.domain.VolumeFile
import com.ermao.library.shared.modules.library.domain.VolumeSection
import com.ermao.library.shared.modules.library.domain.WorkDetail
import com.ermao.library.shared.modules.library.domain.WorkSummary
import kotlinx.serialization.Serializable

@Serializable
data class WorkSummaryWire(
    val id: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val availableMediaKinds: List<String>,
    val progress: Double,
)

@Serializable
data class WorkDetailPayloadWire(
    val book: WorkViewWire,
    val readingUnits: List<ReadingUnitWire>,
    val volumeSections: List<VolumeSectionWire>,
    val readingUnitsPage: ReadingUnitsPageWire,
)

@Serializable
data class WorkVolumePageWire(
    val versionId: String,
    val sourceKey: String,
    val sourceName: String? = null,
    val volumes: List<LibraryVolumeWire>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

fun WorkVolumePageWire.toDomain(): com.ermao.library.shared.modules.library.WorkVolumePage {
    require(versionId.isNotBlank() && sourceKey.isNotBlank() && page > 0 && pageSize in 1..100 && total >= 0 && totalPages > 0)
    return com.ermao.library.shared.modules.library.WorkVolumePage(
        versionId = versionId,
        sourceKey = sourceKey,
        sourceName = sourceName?.takeIf { it.isNotBlank() },
        volumes = volumes.map(LibraryVolumeWire::toDomain),
        page = page,
        pageSize = pageSize,
        total = total,
        totalPages = totalPages,
    )
}

@Serializable
data class WorkViewWire(
    val id: String,
    val title: String,
    val author: String,
    val description: String? = null,
    val publicationStatus: String,
    val trackingStatus: String,
    val tags: List<String>,
    val seriesName: String? = null,
    val seriesFacet: FacetReferenceWire? = null,
    val authorFacets: List<FacetReferenceWire> = emptyList(),
    val seriesIndex: Double? = null,
    val organized: Boolean,
    val organizeStatus: String,
    val metadataQuality: Int,
    val metadataLookupStatus: String? = null,
    val metadataLookupSource: String? = null,
    val metadataLookupError: String? = null,
    val coverStatus: String,
    val coverUrl: String,
    val continueVolumeId: String? = null,
    val continueVolumeTitle: String? = null,
    val continueVolumeProgress: Double,
    val completed: Boolean,
    val lastReadAt: String? = null,
    val addedAt: String? = null,
    val versions: List<LibraryVersionWire>,
)

@Serializable
data class LibraryVersionWire(
    val id: String,
    val sourceKey: String,
    val sourceName: String? = null,
    val completed: Boolean,
    val volumeCount: Int,
    val sizeBytes: Long,
    val volumes: List<LibraryVolumeWire>,
)

@Serializable
data class LibraryVolumeWire(
    val id: String,
    val versionId: String,
    val title: String,
    val volumeIndex: Double? = null,
    val sortOrder: Int,
    val format: String,
    val readerType: String,
    val classification: VolumeClassificationWire,
    val readable: Boolean,
    val kindleSendAvailable: Boolean,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val abridged: Boolean? = null,
    val origin: String,
    val importStatus: String,
    val importError: String? = null,
    val coverStatus: String,
    val pageCount: Int? = null,
    val chapterCount: Int? = null,
    val trackCount: Int? = null,
    val sizeBytes: Long,
    val coverUrl: String,
    val progress: Double = 0.0,
    val completed: Boolean,
    val lastReadAt: String? = null,
    val durationMs: Long? = null,
    val files: List<LibraryFileWire>,
)

@Serializable
data class LibraryFileWire(
    val id: String,
    val volumeId: String,
    val path: String,
    val mimeType: String,
    val kind: String,
    val sortOrder: Int,
    val sizeBytes: Long,
    val size: String,
    val durationMs: Long? = null,
    val codec: String? = null,
    val bitrate: Int? = null,
    val sampleRate: Int? = null,
    val channels: Int? = null,
    val discNumber: Int? = null,
    val trackNumber: Int? = null,
    val url: String? = null,
)

@Serializable
data class ActiveMediaWire(
    val key: String,
    val formatLabel: String,
    val versionId: String,
    val selectedVolumeId: String,
    val selectedVolumeTitle: String,
    val status: String,
    val progressStatus: String,
    val progress: Double,
    val positionLabel: String,
    val durationMs: Long? = null,
    val narrator: String? = null,
    val primaryAction: PrimaryActionWire? = null,
    val units: List<ReadingUnitWire>,
    val volumes: List<LibraryVolumeWire>,
    val tracks: List<LibraryFileWire>,
    val localProgressScope: LocalProgressScopeWire,
    val currentHref: String? = null,
    val currentSectionIndex: Int? = null,
    val currentChapterTitle: String? = null,
    val currentChapterIndex: Int? = null,
    val currentPageNumber: Int? = null,
    val currentChapterSortOrder: Int? = null,
    val progressExtra: ProgressExtraWire,
    val progressEstimated: Boolean = false,
)

@Serializable
data class PrimaryActionWire(val label: String, val href: String)

@Serializable
data class LocalProgressScopeWire(
    val userId: String,
    val volumeId: String,
)

@Serializable
data class ReadingUnitWire(
    val id: String,
    val volumeId: String,
    val fileId: String? = null,
    val unitType: String,
    val title: String? = null,
    val href: String? = null,
    val mediaType: String? = null,
    val sortOrder: Int,
    val startMs: Long? = null,
    val endMs: Long? = null,
    val durationMs: Long? = null,
    val width: Int? = null,
    val height: Int? = null,
    val size: Long? = null,
    val metadataJson: ReadingUnitMetadataWire,
    val createdAt: String? = null,
    val updatedAt: String? = null,
)

@Serializable
data class ReadingUnitMetadataWire(
    val exactNavigation: Boolean? = null,
    val level: Int? = null,
    val path: List<Int>? = null,
    val navigationKey: String? = null,
    val zipEntryName: String? = null,
    val idref: String? = null,
    val linear: Boolean? = null,
    val properties: List<String>? = null,
    val volumeIndex: Double? = null,
    val trackIndex: Int? = null,
    val pageNumber: Int? = null,
    val originalName: String? = null,
    val pageInVolume: Int? = null,
    val pageInSection: Int? = null,
    val sourceFileName: String? = null,
    val hrefBase: String? = null,
    val recovered: Boolean? = null,
    val readingOrderPosition: Int? = null,
)

@Serializable
data class ReadingUnitsPageWire(
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

@Serializable
data class VolumeSectionWire(
    val id: String,
    val versionId: String,
    val title: String,
    val index: Double,
    val fileId: String,
    val pageCount: Int,
    val coverUrl: String,
    val progress: Double,
    val lastReadAt: String? = null,
    val position: String? = null,
    val currentPage: Int? = null,
    val currentHref: String? = null,
    val currentSectionIndex: Int? = null,
    val currentChapterTitle: String? = null,
    val currentChapterIndex: Int? = null,
    val currentChapterSortOrder: Int? = null,
    val progressExtra: ProgressExtraWire,
    val progressEstimated: Boolean = false,
)

@Serializable
data class ProgressExtraWire(
    val cfi: String? = null,
    val progression: Double? = null,
    val navigationKey: String? = null,
    val navigationFingerprint: String? = null,
    val sourceFormat: String? = null,
    val fileId: String? = null,
    val chapterId: String? = null,
    val positionMs: Long? = null,
    val volumeId: String? = null,
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

fun WorkSummaryWire.toDomain(): WorkSummary {
    require(id.isNotBlank() && progress in 0.0..100.0)
    return WorkSummary(
        id = id,
        title = title,
        author = author,
        coverUrl = coverUrl,
        availableMediaKinds = availableMediaKinds.map(::MediaKind),
        progress = progress,
    )
}

fun WorkDetailPayloadWire.toDomain(): WorkDetail {
    val work = book
    require(work.id.isNotBlank() && work.continueVolumeProgress in 0.0..100.0)
    return WorkDetail(
        id = work.id,
        title = work.title,
        author = work.author,
        description = work.description,
        publicationStatus = work.publicationStatus,
        trackingStatus = work.trackingStatus,
        tags = work.tags,
        seriesName = work.seriesName,
        seriesFacet = work.seriesFacet?.toDomain(),
        authorFacets = work.authorFacets.map(FacetReferenceWire::toDomain),
        seriesIndex = work.seriesIndex,
        organized = work.organized,
        organizeStatus = work.organizeStatus,
        metadataQuality = work.metadataQuality,
        metadataLookupStatus = work.metadataLookupStatus,
        metadataLookupSource = work.metadataLookupSource,
        metadataLookupError = work.metadataLookupError,
        coverStatus = work.coverStatus,
        coverUrl = work.coverUrl,
        continueVolumeId = work.continueVolumeId,
        continueVolumeTitle = work.continueVolumeTitle,
        continueVolumeProgress = work.continueVolumeProgress,
        completed = work.completed,
        lastReadAt = work.lastReadAt,
        addedAt = work.addedAt,
        versions = work.versions.map(LibraryVersionWire::toDomain),
        readingUnits = readingUnits.map(ReadingUnitWire::toDomain),
        volumeSections = volumeSections.map(VolumeSectionWire::toDomain),
        readingUnitsPage = readingUnitsPage.toDomain(),
    )
}

private fun LibraryVersionWire.toDomain(): WorkVersion {
    require(id.isNotBlank() && sourceKey.isNotBlank() && volumeCount >= volumes.size && sizeBytes >= 0)
    return WorkVersion(
        id,
        sourceKey,
        sourceName?.takeIf { it.isNotBlank() },
        completed,
        volumeCount,
        sizeBytes,
        volumes.map(LibraryVolumeWire::toDomain),
    )
}

private fun LibraryVolumeWire.toDomain(): Volume {
    require(id.isNotBlank() && versionId.isNotBlank() && sizeBytes >= 0 && progress in 0.0..100.0)
    return Volume(
        id, versionId, title, volumeIndex, sortOrder, format, readerType,
        VolumeClassification(
            classification.source,
            classification.reason,
            classification.suggestedMediaKind?.let(::MediaKind),
        ),
        readable, kindleSendAvailable, publisher, publishedAt,
        language, isbn, identifier, narrator, abridged, origin, importStatus, importError, coverStatus,
        coverUrl, sizeBytes, pageCount, chapterCount, durationMs, trackCount, progress, completed, lastReadAt,
        files.map(LibraryFileWire::toDomain),
    )
}

private fun LibraryFileWire.toDomain(): VolumeFile {
    require(id.isNotBlank() && volumeId.isNotBlank() && sizeBytes >= 0)
    return VolumeFile(
        id, volumeId, path, mimeType, kind, sortOrder, sizeBytes, size, durationMs, codec, bitrate,
        sampleRate, channels, discNumber, trackNumber, url,
    )
}

internal fun ActiveMediaWire.toDomain(): ActiveMedia {
    require(versionId.isNotBlank() && selectedVolumeId.isNotBlank() && progress in 0.0..100.0)
    return ActiveMedia(
        MediaKind(key), formatLabel, versionId, selectedVolumeId, selectedVolumeTitle, status,
        progressStatus, progress, positionLabel, durationMs, narrator,
        primaryAction?.let { PrimaryAction(it.label, it.href) },
        units.map(ReadingUnitWire::toDomain), volumes.map(LibraryVolumeWire::toDomain),
        tracks.map(LibraryFileWire::toDomain),
        LocalProgressScope(
            localProgressScope.userId,
            localProgressScope.volumeId,
        ),
        currentHref, currentSectionIndex, currentChapterTitle, currentChapterIndex, currentPageNumber,
        currentChapterSortOrder, progressExtra.toDomain(), progressEstimated,
    )
}

internal fun ReadingUnitWire.toDomain(): ReadingUnit = ReadingUnit(
    id, volumeId, fileId, unitType, title, href, mediaType, sortOrder, startMs, endMs, durationMs,
    width, height, size, metadataJson.toDomain(), createdAt, updatedAt,
)

private fun ReadingUnitMetadataWire.toDomain(): ReadingUnitMetadata = ReadingUnitMetadata(
    exactNavigation = exactNavigation,
    level = level,
    path = path,
    navigationKey = navigationKey,
    zipEntryName = zipEntryName,
    idref = idref,
    linear = linear,
    properties = properties,
    volumeIndex = volumeIndex,
    trackIndex = trackIndex,
    pageNumber = pageNumber,
    originalName = originalName,
    pageInVolume = pageInVolume,
    pageInSection = pageInSection,
    sourceFileName = sourceFileName,
    hrefBase = hrefBase,
    recovered = recovered,
    readingOrderPosition = readingOrderPosition,
)

private fun ReadingUnitsPageWire.toDomain(): ReadingUnitsPage {
    require(page >= 1 && pageSize >= 1 && total >= 0 && totalPages >= 0)
    return ReadingUnitsPage(page, pageSize, total, totalPages)
}

private fun VolumeSectionWire.toDomain(): VolumeSection {
    require(id.isNotBlank() && versionId.isNotBlank() && progress in 0.0..100.0)
    return VolumeSection(
        id, versionId, title, index, fileId, pageCount, coverUrl, progress, lastReadAt, position,
        currentPage, currentHref, currentSectionIndex, currentChapterTitle, currentChapterIndex,
        currentChapterSortOrder, progressExtra.toDomain(), progressEstimated,
    )
}

private fun ProgressExtraWire.toDomain(): ProgressExtra = ProgressExtra(
    cfi, progression, navigationKey, navigationFingerprint, sourceFormat, fileId, chapterId,
    positionMs, volumeId, pageIndex, chapterHref, currentHref, chapterSectionIndex, sectionIndex,
    chapterIndex, chapterSortOrder, chapterTitle, sectionPage, sectionTotalPages, sectionTotal,
    locationCurrent, locationNext, locationTotal, remainingSectionSeconds, remainingTotalSeconds,
    progressEstimated,
)
