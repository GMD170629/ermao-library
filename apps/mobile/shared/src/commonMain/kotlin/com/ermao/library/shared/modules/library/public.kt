package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.domain.BookDetail
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.infrastructure.BookDetailPayloadWire
import com.ermao.library.shared.modules.library.infrastructure.BookPayloadWire
import com.ermao.library.shared.modules.library.infrastructure.BookSummaryWire
import com.ermao.library.shared.modules.library.infrastructure.toBookDetailSummary
import com.ermao.library.shared.modules.library.infrastructure.toDomain
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode

/** Stable capability boundary; platform code does not import library infrastructure mappers directly. */
object LibraryContract {
    fun bookSummary(wire: BookSummaryWire): BookSummary = wire.toDomain()

    fun bookDetailSummary(wire: BookPayloadWire): BookDetailSummary = wire.toDomain()

    fun bookDetail(wire: BookDetailPayloadWire): BookDetail = wire.toDomain()
}

/** Swift-friendly construction boundary; invalid or mismatched contexts are rejected. */
fun createContentRequestContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
    userId: String,
    authorizationVersion: Long,
): ContentRequestContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return ContentRequestContext(
        profile = ServerProfile(
            id = profileId,
            displayName = displayName,
            baseUrl = parsed.baseUrl,
            serverIdentity = serverIdentity,
            isActive = true,
            tlsMode = if (acceptsInsecureTls) TlsMode.InsecureSkipAllValidation else TlsMode.SystemTrust,
        ),
        namespace = PrivateDataNamespace(serverIdentity, userId, authorizationVersion),
    )
}

fun createLibraryFilters(
    readingStatus: ReadingStatus?,
): LibraryFilters = LibraryFilters(
    readingStatus = readingStatus,
)

/** Swift-friendly server-node navigation boundary. */
fun resolveBookContentTarget(node: BookContentEntry): BookContentTarget? = bookContentTarget(node)

typealias BookContentSnapshot = com.ermao.library.shared.modules.library.application.BookContentSnapshot

typealias BookDetailActionScope = com.ermao.library.shared.modules.library.domain.BookDetailActionScope
typealias BookDetailObjectKind = com.ermao.library.shared.modules.library.domain.BookDetailObjectKind
typealias BookDetailDownloadState = com.ermao.library.shared.modules.library.domain.BookDetailDownloadState
typealias BookDetailDownloadSummary = com.ermao.library.shared.modules.library.domain.BookDetailDownloadSummary

fun summarizeBookDetailDownloads(states: List<BookDetailDownloadState>): BookDetailDownloadSummary =
    com.ermao.library.shared.modules.library.domain.bookDetailDownloadSummary(states)

fun resolveBookDetailActionScope(
    isBookRoot: Boolean,
    bookId: String,
    selectedResourceId: String?,
    continueResourceId: String?,
): BookDetailActionScope? = com.ermao.library.shared.modules.library.domain.bookDetailActionScope(
    isBookRoot, bookId, selectedResourceId, continueResourceId,
)

suspend fun loadBookContentPage(
    repository: ContentRepository,
    context: ContentRequestContext,
    bookId: String,
    target: BookContentTarget,
    sort: BookContentSort,
    page: Int,
): ContentResult<BookContentSnapshot> = com.ermao.library.shared.modules.library.application.loadBookContent(
    repository, context, bookId, target, sort, page,
)
