package com.ermao.library.shared.modules.library.application

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.library.BookContentSort
import com.ermao.library.shared.modules.library.BookContentTarget
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookContentsQuery
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BookResourcePageQuery
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.bookContentTarget
import com.ermao.library.shared.modules.library.domain.BookDetailSummary

data class BookContentSnapshot(
    val book: BookDetailSummary,
    val target: BookContentTarget,
    val contents: BookContentsPage?,
)

/** Read a single authorized navigation destination. No selection or navigation side effects. */
suspend fun loadBookContent(
    repository: ContentRepository,
    context: ContentRequestContext,
    bookId: String,
    target: BookContentTarget,
    sort: BookContentSort,
    page: Int,
): ContentResult<BookContentSnapshot> {
    val book = when (val result = repository.loadBookDetail(context, BookDetailQuery(bookId))) {
        is ContentResult.Content -> result.value
        is ContentResult.Failure -> return result
    }
    val contents = if (target is BookContentTarget.ResourceDetail) null else {
        when (val result = repository.loadBookContents(
            context, BookContentsQuery(bookId, (target as? BookContentTarget.Directory)?.sourceNodeId, sort, page),
        )) {
            is ContentResult.Content -> result.value
            is ContentResult.Failure -> return result
        }
    }
    val destination = if (target == BookContentTarget.Root) {
        contents?.currentNode?.let(::bookContentTarget) ?: return inaccessible()
    } else target
    val requiredIds = buildSet {
        if (target == BookContentTarget.Root) book.continueResourceId?.let(::add)
        if (destination is BookContentTarget.ResourceDetail) add(destination.resourceId)
        contents?.entries?.forEach { entry ->
            entry.resourceId?.let(::add)
            entry.representativeResourceId?.let(::add)
        }
    }
    val resources = book.resources.associateByTo(linkedMapOf()) { it.id }
    var resourcePage = 1
    while (!resources.keys.containsAll(requiredIds)) {
        when (val result = repository.loadBookResources(context, BookResourcePageQuery(bookId, resourcePage))) {
            is ContentResult.Failure -> return result
            is ContentResult.Content -> {
                result.value.resources.forEach { resources[it.id] = it }
                if (resourcePage >= result.value.totalPages || result.value.resources.isEmpty()) break
                resourcePage += 1
            }
        }
    }
    if (destination is BookContentTarget.ResourceDetail) {
        val resource = resources[destination.resourceId] ?: return inaccessible()
        if (resource.bookId != bookId || resource.hidden) return inaccessible()
    }
    return ContentResult.Content(BookContentSnapshot(
        book.copy(resources = resources.values.filter { it.bookId == bookId && !it.hidden }), destination, contents,
    ))
}

private fun inaccessible(): ContentResult.Failure = ContentResult.Failure(
    AppError(AppErrorKind.NotFoundOrUnavailable, "CONTENT_NOT_ACCESSIBLE"),
)
