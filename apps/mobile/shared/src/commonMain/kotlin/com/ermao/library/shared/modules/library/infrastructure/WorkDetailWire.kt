package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.domain.Volume
import com.ermao.library.shared.modules.library.domain.VolumeClassification
import com.ermao.library.shared.modules.library.domain.VolumeFile
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkVersion
import kotlinx.serialization.Serializable

@Serializable
data class WorkDetailSummaryPayloadWire(
    val book: WorkWire,
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
    val continueVolumeId: String? = null,
    val continueVolumeProgress: Double = 0.0,
    val completed: Boolean,
    val versions: List<WorkVersionWire>,
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
data class WorkVersionWire(
    val id: String,
    val sourceKey: String,
    val sourceName: String? = null,
    val completed: Boolean,
    val volumeCount: Int,
    val sizeBytes: Long,
    val volumes: List<VolumeWire>,
)

@Serializable
data class VolumeWire(
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

fun WorkDetailSummaryPayloadWire.toDomain(): WorkDetailSummary = book.toDomain()

fun WorkWire.toDomain(): WorkDetailSummary {
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
        continueVolumeId = continueVolumeId,
        continueVolumeProgress = continueVolumeProgress.also { require(it in 0.0..100.0) },
        completed = completed,
        versions = versions.map(WorkVersionWire::toDomain),
    )
}

fun WorkVersionWire.toDomain(): WorkVersion {
    require(id.isNotBlank()) { "Work version id is blank" }
    require(sourceKey.isNotBlank()) { "Work version source key is blank" }
    require(volumeCount >= volumes.size) { "Bounded volume page exceeds total count" }
    require(sizeBytes >= 0) { "Work version size is negative" }
    return WorkVersion(
        id = id,
        sourceKey = sourceKey,
        sourceName = sourceName?.takeIf { it.isNotBlank() },
        completed = completed,
        volumeCount = volumeCount,
        sizeBytes = sizeBytes,
        volumes = volumes.map(VolumeWire::toDomain),
    )
}

fun VolumeWire.toDomain(): Volume {
    require(id.isNotBlank() && versionId.isNotBlank()) { "Volume identity is blank" }
    require(sizeBytes >= 0) { "Volume size is negative" }
    require(progress in 0.0..100.0) { "Volume progress is outside 0..100" }
    return Volume(
        id = id,
        versionId = versionId,
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
