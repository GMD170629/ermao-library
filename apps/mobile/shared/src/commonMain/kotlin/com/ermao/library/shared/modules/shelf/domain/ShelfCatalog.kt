package com.ermao.library.shared.modules.shelf.domain

data class ShelfBookPreview(
    val id: String,
    val title: String,
    val author: String?,
    val coverUrl: String,
    val progress: Double,
)

data class ShelfCatalogEntry(
    val id: String,
    val name: String,
    val description: String?,
    val kind: ShelfKind,
    val count: Int,
    val books: List<ShelfBookPreview>,
    val collectionIds: List<String>,
    val rulesSupported: Boolean,
)

/** Search is over the complete authorized summary response, never just a loaded detail page. */
enum class ShelfCatalogScope { All, Shelves, Collections }

fun filterShelfCatalog(
    entries: List<ShelfCatalogEntry>,
    scope: ShelfCatalogScope,
    query: String,
    collectionId: String? = null,
): List<ShelfCatalogEntry> {
    val normalizedQuery = query.trim()
    return entries.filter { entry ->
        val matchesKind = when (scope) {
            ShelfCatalogScope.All -> true
            ShelfCatalogScope.Shelves -> entry.kind != ShelfKind.Collection
            ShelfCatalogScope.Collections -> entry.kind == ShelfKind.Collection
        }
        matchesKind && (collectionId == null || collectionId in entry.collectionIds) &&
            (normalizedQuery.isEmpty() || entry.name.contains(normalizedQuery, ignoreCase = true) ||
                entry.description.orEmpty().contains(normalizedQuery, ignoreCase = true))
    }
}

/** A collection owns shelves, not books. Its artwork is a deduplicated member preview. */
fun shelfPreviewBooks(entry: ShelfCatalogEntry, catalog: List<ShelfCatalogEntry>): List<ShelfBookPreview> =
    if (entry.kind == ShelfKind.Collection) {
        catalog.asSequence().filter { entry.id in it.collectionIds }
            .flatMap { it.books.asSequence() }.distinctBy { it.id }.take(3).toList()
    } else entry.books.take(3)

data class ShelfCatalogPage(
    val shelf: ShelfCatalogEntry,
    val members: List<ShelfCatalogEntry>,
    val page: Int,
    val totalPages: Int,
)

data class CreateShelfInput(
    val name: String,
    val description: String,
    val kind: ShelfKind,
    val memberShelfIds: List<String>,
) {
    init {
        require(name.isNotBlank())
        require(kind != ShelfKind.Smart)
        require(kind == ShelfKind.Collection || memberShelfIds.isEmpty())
        require(memberShelfIds.distinct().size == memberShelfIds.size)
    }
}
