package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.ActiveMedia
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.MediaVersion
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.Volume
import com.ermao.library.shared.modules.library.domain.VolumeClassification
import com.ermao.library.shared.modules.library.domain.VolumeFile
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkDetailTab
import kotlinx.serialization.Serializable

@Serializable
data class WorkDetailSummaryPayloadWire(
    val book: WorkWire,
    val activeMedia: ActiveMediaWire? = null,
    val readingUnits: List<ReadingUnitWire> = emptyList(),
    val volumeSections: List<VolumeSectionWire> = emptyList(),
    val readingUnitsPage: ReadingUnitsPageWire? = null,
)

@Serializable
data class WorkWire(
    val id: String,
    val title: String,
    val author: String,
    val description: String? = null,
    val tags: List<String>,
    val seriesName: String? = null,
    val seriesFacet: FacetReferenceWire? = null,
    val authorFacets: List<FacetReferenceWire> = emptyList(),
    val seriesIndex: Double? = null,
    val coverStatus: String,
    val coverUrl: String,
    val recentMediaKind: String? = null,
    val continueVolumeId: String? = null,
    val continueVolumeProgress: Double = 0.0,
    val completed: Boolean,
    val mediaVersions: List<MediaVersionWire>,
    val availableMediaKinds: List<String>,
    val detailTabs: List<WorkDetailTabWire>,
    val selectedDetailTab: String,
)

@Serializable
data class FacetReferenceWire(val id: String, val kind: String, val name: String)

internal fun FacetReferenceWire.toDomain(): AppliedFacet = AppliedFacet(
    id = id.also { require(it.isNotBlank()) },
    kind = when (kind.uppercase()) {
        "SERIES" -> FacetKind.Series
        "AUTHOR" -> FacetKind.Author
        else -> error("Unsupported facet kind")
    },
    name = name.also { require(it.isNotBlank()) },
)

@Serializable
data class WorkDetailTabWire(val key: String, val label: String, val sortOrder: Int)

@Serializable
data class MediaVersionWire(
    val id: String,
    val mediaKind: String,
    val completed: Boolean,
    val volumeCount: Int,
    val sizeBytes: Long,
    val volumes: List<VolumeWire>,
)

@Serializable
data class VolumeWire(
    val id: String,
    val mediaVersionId: String,
    val title: String,
    val volumeIndex: Double? = null,
    val sortOrder: Int,
    val format: String,
    val readerType: String,
    val classification: VolumeClassificationWire,
    val readable: Boolean,
    val kindleSendAvailable: Boolean,
    val derivedFromVolumeId: String? = null,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val coverUrl: String,
    val sizeBytes: Long,
    val pageCount: Int? = null,
    val chapterCount: Int? = null,
    val durationMs: Long? = null,
    val trackCount: Int? = null,
    val progress: Double,
    val files: List<VolumeFileSummaryWire>,
)

@Serializable
data class VolumeClassificationWire(
    val source: String,
    val reason: String,
    val suggestedMediaKind: String? = null,
)

@Serializable
data class VolumeFileSummaryWire(
    val id: String,
    val path: String,
    val sizeBytes: Long,
    val size: String,
)

fun WorkDetailSummaryPayloadWire.toDomain(): WorkDetailSummary = book.toDomain(
    activeMedia = activeMedia?.toDomain(),
    readingUnits = readingUnits.map(ReadingUnitWire::toDomain),
    readingUnitsPage = readingUnitsPage?.toDomain(),
)

private fun ReadingUnitsPageWire.toDomain(): com.ermao.library.shared.modules.library.domain.ReadingUnitsPage =
    com.ermao.library.shared.modules.library.domain.ReadingUnitsPage(page, pageSize, total, totalPages)

fun WorkWire.toDomain(
    activeMedia: ActiveMedia? = null,
    readingUnits: List<ReadingUnit> = emptyList(),
    readingUnitsPage: com.ermao.library.shared.modules.library.domain.ReadingUnitsPage? = null,
): WorkDetailSummary {
    require(id.isNotBlank()) { "Work id is blank" }
    require(title.isNotBlank()) { "Work title is blank" }
    return WorkDetailSummary(
        id = id,
        title = title,
        author = author,
        description = description,
        tags = tags,
        seriesName = seriesName,
        seriesFacet = seriesFacet?.toDomain(),
        authorFacets = authorFacets.map(FacetReferenceWire::toDomain),
        seriesIndex = seriesIndex,
        coverStatus = coverStatus,
        coverUrl = coverUrl,
        recentMediaKind = recentMediaKind?.let(::MediaKind),
        continueVolumeId = continueVolumeId,
        continueVolumeProgress = continueVolumeProgress.also { require(it in 0.0..100.0) },
        completed = completed,
        mediaVersions = mediaVersions.map(MediaVersionWire::toDomain),
        availableMediaKinds = availableMediaKinds.map(::MediaKind),
        detailTabs = detailTabs.map { WorkDetailTab(it.key, it.label, it.sortOrder) },
        selectedDetailTab = selectedDetailTab,
        activeMedia = activeMedia,
        readingUnits = readingUnits,
        readingUnitsPage = readingUnitsPage,
    )
}

fun MediaVersionWire.toDomain(): MediaVersion {
    require(id.isNotBlank()) { "Media version id is blank" }
    require(volumeCount >= volumes.size) { "Bounded volume page exceeds total count" }
    require(sizeBytes >= 0) { "Media version size is negative" }
    return MediaVersion(
        id = id,
        mediaKind = MediaKind(mediaKind),
        completed = completed,
        volumeCount = volumeCount,
        sizeBytes = sizeBytes,
        volumes = volumes.map(VolumeWire::toDomain),
    )
}

fun VolumeWire.toDomain(): Volume {
    require(id.isNotBlank() && mediaVersionId.isNotBlank()) { "Volume identity is blank" }
    require(sizeBytes >= 0) { "Volume size is negative" }
    require(progress in 0.0..100.0) { "Volume progress is outside 0..100" }
    return Volume(
        id = id,
        mediaVersionId = mediaVersionId,
        title = title,
        volumeIndex = volumeIndex,
        sortOrder = sortOrder,
        format = format,
        readerType = readerType,
        classification = VolumeClassification(
            classification.source,
            classification.reason,
            classification.suggestedMediaKind?.let(::MediaKind),
        ),
        readable = readable,
        kindleSendAvailable = kindleSendAvailable,
        derivedFromVolumeId = derivedFromVolumeId,
        publisher = publisher,
        publishedAt = publishedAt,
        language = language,
        isbn = isbn,
        identifier = identifier,
        narrator = narrator,
        abridged = null,
        origin = null,
        importStatus = null,
        importError = null,
        coverStatus = null,
        coverUrl = coverUrl,
        sizeBytes = sizeBytes,
        pageCount = pageCount,
        chapterCount = chapterCount,
        durationMillis = durationMs,
        trackCount = trackCount,
        progress = progress,
        completed = null,
        lastReadAt = null,
        files = files.map {
            VolumeFile(
                id = it.id,
                volumeId = null,
                path = it.path,
                mimeType = null,
                kind = null,
                sortOrder = null,
                sizeBytes = it.sizeBytes,
                displaySize = it.size,
                durationMillis = null,
                codec = null,
                bitrate = null,
                sampleRate = null,
                channels = null,
                discNumber = null,
                trackNumber = null,
                url = null,
            )
        },
    )
}
