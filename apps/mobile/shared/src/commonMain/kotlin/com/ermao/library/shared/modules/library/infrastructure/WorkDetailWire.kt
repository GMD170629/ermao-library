package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.Resource
import com.ermao.library.shared.modules.library.domain.Asset
import kotlinx.serialization.Serializable

@Serializable
data class FacetReferenceWire(val id: String, val kind: String, val name: String)

@Serializable
data class BookPayloadWire(
    val book: BookWire,
)

@Serializable
data class BookWire(
    val id: String,
    val libraryId: String,
    val sourceNodeId: String,
    val title: String,
    val author: String? = null,
    val description: String? = null,
    val seriesName: String? = null,
    val seriesIndex: Double? = null,
    val visibilityState: String,
    val curationState: String,
    val publicationStatus: String,
    val trackingStatus: String,
    val metadataQuality: Int,
    val coverStatus: String,
    val coverPath: String? = null,
    val coverUrl: String,
    val tags: List<String> = emptyList(),
    val ignored: Boolean = false,
    val organized: Boolean = false,
    val addedAt: String? = null,
    val createdAt: String? = null,
    val updatedAt: String? = null,
    val gradient: String = "",
    val resources: List<ResourceWire> = emptyList(),
    val resourceImportSummary: ResourceImportSummaryWire = ResourceImportSummaryWire(),
    val completed: Boolean = false,
    val continueResourceId: String? = null,
    val continueResourceTitle: String? = null,
    val continueResourceProgress: Double = 0.0,
)

@Serializable
data class ResourceWire(
    val id: String,
    val bookId: String,
    val sourceNodeId: String,
    val title: String,
    val description: String? = null,
    val resourceIndex: Double? = null,
    val sortOrder: Int = 0,
    val format: String,
    val readerType: String,
    val kindleSendAvailable: Boolean = false,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val abridged: Boolean? = null,
    val importStatus: String = "READY",
    val importError: String? = null,
    val sizeBytes: Long = 0,
    val pageCount: Int? = null,
    val chapterCount: Int? = null,
    val durationMs: Long? = null,
    val trackCount: Int? = null,
    val coverStatus: String = "UNKNOWN",
    val coverPath: String? = null,
    val coverUrl: String = "",
    val progress: Double = 0.0,
    val lastReadAt: String? = null,
    val hidden: Boolean = false,
    val readable: Boolean = true,
    val resourceCompleted: Boolean = false,
    val assets: List<AssetWire> = emptyList(),
)

@Serializable
data class AssetWire(
    val id: String,
    val title: String,
    val resourceId: String? = null,
    val sourceNodeId: String? = null,
    val role: String? = null,
    val mimeType: String? = null,
    val sizeBytes: Long = 0,
    val size: String = "0 B",
    val mtimeMs: Long? = null,
    val durationMs: Long? = null,
    val codec: String? = null,
    val bitrate: Int? = null,
    val sampleRate: Int? = null,
    val channels: Int? = null,
    val discNumber: Int? = null,
    val trackNumber: Int? = null,
    val sortOrder: Int? = null,
    val url: String? = null,
    val downloadUrl: String? = null,
    val sourceFormat: String? = null,
)

fun BookPayloadWire.toDomain(): BookDetailSummary = book.toBookDetailSummary()

fun BookWire.toBookDetailSummary(): BookDetailSummary {
    require(id.isNotBlank()) { "Book id is blank" }
    require(title.isNotBlank()) { "Book title is blank" }
    require(continueResourceProgress in 0.0..100.0) { "Book progress is outside 0..100" }
    return BookDetailSummary(
        id = id,
        sourceNodeId = sourceNodeId,
        title = title,
        author = author,
        description = description,
        tags = tags,
        seriesName = seriesName,
        seriesFacet = null,
        authorFacets = emptyList(),
        seriesIndex = seriesIndex,
        coverStatus = coverStatus,
        coverUrl = coverUrl,
        continueResourceId = continueResourceId,
        continueResourceProgress = continueResourceProgress,
        completed = completed,
        resources = resources.map(ResourceWire::toDomain),
    )
}

fun ResourceWire.toDomain(): Resource {
    require(id.isNotBlank() && bookId.isNotBlank() && sourceNodeId.isNotBlank()) {
        "Resource identity is blank"
    }
    require(sizeBytes >= 0 && progress in 0.0..100.0) {
        "Resource metrics are invalid"
    }
    return Resource(
        id = id,
        bookId = bookId,
        sourceNodeId = sourceNodeId,
        title = title,
        description = description,
        resourceIndex = resourceIndex,
        sortOrder = sortOrder,
        format = format,
        readerType = readerType,
        readable = readable,
        kindleSendAvailable = kindleSendAvailable,
        publisher = publisher,
        publishedAt = publishedAt,
        language = language,
        isbn = isbn,
        identifier = identifier,
        narrator = narrator,
        abridged = abridged,
        importStatus = importStatus,
        importError = importError,
        coverStatus = coverStatus,
        coverPath = coverPath,
        coverUrl = coverUrl,
        sizeBytes = sizeBytes,
        pageCount = pageCount,
        chapterCount = chapterCount,
        durationMillis = durationMs,
        trackCount = trackCount,
        progress = progress,
        lastReadAt = lastReadAt,
        hidden = hidden,
        completed = resourceCompleted,
        assets = assets.map(AssetWire::toDomain),
    )
}

fun AssetWire.toDomain(): Asset {
    require(id.isNotBlank() && sizeBytes >= 0) { "Asset identity or size is invalid" }
    return Asset(
        id = id,
        title = title,
        resourceId = resourceId,
        sourceNodeId = sourceNodeId,
        role = role,
        mimeType = mimeType,
        sizeBytes = sizeBytes,
        displaySize = size,
        mtimeMillis = mtimeMs,
        durationMillis = durationMs,
        codec = codec,
        bitrate = bitrate,
        sampleRate = sampleRate,
        channels = channels,
        discNumber = discNumber,
        trackNumber = trackNumber,
        sortOrder = sortOrder,
        url = url,
        downloadUrl = downloadUrl,
        sourceFormat = sourceFormat,
    )
}
