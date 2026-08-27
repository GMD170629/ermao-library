package com.ermao.library.shared.modules.library.domain

/** One action scope for both native detail surfaces; it never changes the navigation destination. */
enum class BookDetailObjectKind { Book, Resource }

data class BookDetailActionScope(
    val objectKind: BookDetailObjectKind,
    val objectId: String,
    val readingResourceId: String?,
) {
    val includesBookActions: Boolean get() = objectKind == BookDetailObjectKind.Book
}

fun bookDetailActionScope(
    isBookRoot: Boolean,
    bookId: String,
    selectedResourceId: String?,
    continueResourceId: String?,
): BookDetailActionScope? {
    if (!isBookRoot && selectedResourceId == null) return null
    return BookDetailActionScope(
        objectKind = if (isBookRoot) BookDetailObjectKind.Book else BookDetailObjectKind.Resource,
        objectId = if (isBookRoot) bookId else requireNotNull(selectedResourceId),
        readingResourceId = selectedResourceId ?: continueResourceId.takeIf { isBookRoot },
    )
}

enum class BookDetailDownloadState { NotDownloaded, Downloading, Paused, Failed, Downloaded }

data class BookDetailDownloadSummary(val state: BookDetailDownloadState, val downloadedResources: Int)

/** Summarizes the current book, never the continue-reading resource alone. */
fun bookDetailDownloadSummary(states: List<BookDetailDownloadState>): BookDetailDownloadSummary {
    val state = when {
        BookDetailDownloadState.Downloading in states -> BookDetailDownloadState.Downloading
        BookDetailDownloadState.Failed in states -> BookDetailDownloadState.Failed
        BookDetailDownloadState.Paused in states -> BookDetailDownloadState.Paused
        BookDetailDownloadState.Downloaded in states -> BookDetailDownloadState.Downloaded
        else -> BookDetailDownloadState.NotDownloaded
    }
    return BookDetailDownloadSummary(state, states.count { it == BookDetailDownloadState.Downloaded })
}
