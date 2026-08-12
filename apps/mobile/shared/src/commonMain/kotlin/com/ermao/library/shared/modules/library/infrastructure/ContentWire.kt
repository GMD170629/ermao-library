package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.ContinueReadingItem
import com.ermao.library.shared.modules.library.FacetPage
import com.ermao.library.shared.modules.library.GroupingSummary
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.domain.MediaKind
import kotlinx.serialization.Serializable

@Serializable
internal data class WorkPageWire(
    val books: List<WorkSummaryWire>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
    val appliedFacet: FacetReferenceWire? = null,
)

@Serializable
internal data class WorksWire(val books: List<WorkSummaryWire>)

@Serializable
internal data class ContinueReadingPayloadWire(val item: ContinueReadingWire? = null)

@Serializable
internal data class ContinueReadingWire(
    val workId: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val mediaKind: String,
    val volumeFormat: String,
    val readerType: String,
    val resumeVolumeId: String? = null,
    val progress: Double,
    val chapter: String? = null,
    val lastReadAt: String? = null,
    val volumeTitle: String? = null,
    val narrator: String? = null,
)

@Serializable
internal data class GroupingPageWire(
    val kind: String,
    val groups: List<GroupingWire>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

@Serializable
internal data class GroupingWire(
    val id: String,
    val name: String,
    val bookCount: Int,
    val updatedAt: String,
    val representativeWorks: List<GroupingRepresentativeWorkWire> = emptyList(),
)

@Serializable
internal data class GroupingRepresentativeWorkWire(
    val id: String,
    val title: String,
    val author: String,
    val coverUrl: String,
)

internal fun WorkPageWire.toPage(): LibraryPage<com.ermao.library.shared.modules.library.domain.WorkSummary> =
    LibraryPage(books.map(WorkSummaryWire::toDomain), page, pageSize, total, totalPages)

internal fun WorkPageWire.toFacetPage(): FacetPage? = appliedFacet?.let { facet ->
    FacetPage(facet = facet.toDomain(), works = toPage())
}

internal fun GroupingPageWire.toPage(): LibraryPage<GroupingSummary> = LibraryPage(
    groups.map { group ->
        GroupingSummary(
            group.id.also { require(it.isNotBlank()) },
            group.name.also { require(it.isNotBlank()) },
            group.bookCount.also { require(it >= 0) },
            group.updatedAt,
            group.representativeWorks.take(3).map(GroupingRepresentativeWorkWire::toDomain),
        )
    },
    page,
    pageSize,
    total,
    totalPages,
)

private fun GroupingRepresentativeWorkWire.toDomain() =
    com.ermao.library.shared.modules.library.domain.WorkSummary(
        id = id.also { require(it.isNotBlank()) },
        title = title,
        author = author,
        coverUrl = coverUrl,
        availableMediaKinds = emptyList(),
        progress = 0.0,
    )

internal fun ContinueReadingWire.toDomain(): ContinueReadingItem = ContinueReadingItem(
    workId = workId.also { require(it.isNotBlank()) },
    title = title,
    author = author,
    coverUrl = coverUrl,
    mediaKind = MediaKind(mediaKind),
    resumeVolumeId = resumeVolumeId,
    progress = progress.also { require(it in 0.0..100.0) },
    lastReadAt = lastReadAt,
    volumeTitle = volumeTitle,
    narrator = narrator,
)

internal fun facetKindWire(kind: FacetKind): String = when (kind) {
    FacetKind.Series -> "SERIES"
    FacetKind.Author -> "AUTHOR"
}
