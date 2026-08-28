package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.modules.library.ContinueReadingItem
import com.ermao.library.shared.modules.library.FacetPage
import com.ermao.library.shared.modules.library.GroupingSummary
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.domain.AppliedFacet
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.FacetKind
import kotlinx.serialization.Serializable

@Serializable
internal data class BookPageWire(
    val books: List<BookSummaryWire>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
    val appliedFacet: FacetReferenceWire? = null,
)

@Serializable
internal data class BooksWire(val books: List<BookSummaryWire>)

@Serializable
internal data class ContinueReadingPayloadWire(val item: ContinueReadingWire? = null)

@Serializable
internal data class ContinueReadingWire(
    val bookId: String,
    val title: String,
    val author: String? = null,
    val coverUrl: String,
    val resourceFormat: String,
    val readerType: String,
    val resumeResourceId: String? = null,
    val progress: Double,
    val chapter: String? = null,
    val lastReadAt: String? = null,
    val resourceTitle: String? = null,
    val narrator: String? = null,
)

@Serializable
internal data class GroupingPageWire(
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
    val representativeBooks: List<GroupingRepresentativeBookWire> = emptyList(),
)

@Serializable
internal data class GroupingRepresentativeBookWire(
    val id: String,
    val title: String,
    val author: String? = null,
    val coverUrl: String,
    val updatedAt: String,
)

@Serializable
data class BookSummaryWire(
    val id: String,
    val title: String,
    val author: String? = null,
    val coverUrl: String,
    val completed: Boolean? = null,
    val resourceImportSummary: ResourceImportSummaryWire = ResourceImportSummaryWire(),
    val progress: Double,
)

@Serializable
data class ResourceImportSummaryWire(
    val ready: Int = 0,
    val pending: Int = 0,
    val failed: Int = 0,
)

internal fun BookPageWire.toPage(): LibraryPage<BookSummary> =
    LibraryPage(books.map(BookSummaryWire::toDomain), page, pageSize, total, totalPages)

internal fun BookPageWire.toFacetPage(queryKind: FacetKind, facetId: String): FacetPage = FacetPage(
    facet = appliedFacet?.toDomain()
        ?: AppliedFacet(facetId, queryKind, facetId),
    books = toPage(),
)

internal fun GroupingPageWire.toPage(): LibraryPage<GroupingSummary> = LibraryPage(
    groups.map { group ->
        GroupingSummary(
            id = group.id.also { require(it.isNotBlank()) },
            name = group.name.also { require(it.isNotBlank()) },
            bookCount = group.bookCount.also { require(it >= 0) },
            updatedAt = group.updatedAt,
            representativeBooks = group.representativeBooks.take(3).map(GroupingRepresentativeBookWire::toDomain),
        )
    },
    page,
    pageSize,
    total,
    totalPages,
)

private fun GroupingRepresentativeBookWire.toDomain() = BookSummary(
    id = id.also { require(it.isNotBlank()) },
    title = title,
    author = author,
    coverUrl = coverUrl,
    progress = 0.0,
)

internal fun ContinueReadingWire.toDomain(): ContinueReadingItem = ContinueReadingItem(
    bookId = bookId.also { require(it.isNotBlank()) },
    title = title,
    author = author,
    coverUrl = coverUrl,
    resourceFormat = resourceFormat,
    readerType = readerType,
    resumeResourceId = resumeResourceId,
    progress = progress.also { require(it in 0.0..100.0) },
    chapter = chapter,
    lastReadAt = lastReadAt,
    resourceTitle = resourceTitle,
    narrator = narrator,
)

internal fun BookSummaryWire.toDomain(): BookSummary {
    require(id.isNotBlank() && progress in 0.0..100.0)
    return BookSummary(
        id = id,
        title = title,
        author = author,
        coverUrl = coverUrl,
        progress = progress,
        completed = completed,
    )
}

internal fun FacetReferenceWire.toDomain(): AppliedFacet = AppliedFacet(
    id = id.also { require(it.isNotBlank()) },
    kind = when (kind.uppercase()) {
        "SERIES" -> FacetKind.Series
        "AUTHOR" -> FacetKind.Author
        "TAG" -> FacetKind.Tag
        else -> error("Unsupported facet kind")
    },
    name = name.also { require(it.isNotBlank()) },
)

internal fun facetKindWire(kind: FacetKind): String = when (kind) {
    FacetKind.Series -> "SERIES"
    FacetKind.Author -> "AUTHOR"
    FacetKind.Tag -> "TAG"
}
