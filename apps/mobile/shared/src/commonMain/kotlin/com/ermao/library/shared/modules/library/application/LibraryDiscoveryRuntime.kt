package com.ermao.library.shared.modules.library.application

import com.ermao.library.shared.modules.library.ContentSource
import com.ermao.library.shared.modules.library.LibraryFilters
import com.ermao.library.shared.modules.library.LibraryScope
import com.ermao.library.shared.modules.library.LibrarySort
import com.ermao.library.shared.modules.library.LibraryViewMode
import com.ermao.library.shared.modules.library.OfflineFilterAvailability
import com.ermao.library.shared.modules.library.domain.FacetKind

data class LoadedPageWindow(
    val firstPage: Int,
    val lastPage: Int,
) {
    init {
        require(firstPage > 0)
        require(lastPage >= firstPage)
    }
}

data class LibraryScrollAnchor(
    val itemId: String,
    val offset: Int = 0,
) {
    init {
        require(itemId.isNotBlank())
    }
}

data class LibraryScopeSnapshot(
    val query: String = "",
    val sort: LibrarySort = LibrarySort.RecentlyAdded,
    val viewMode: LibraryViewMode = LibraryViewMode.Grid,
    val filters: LibraryFilters = LibraryFilters(),
    val loadedPageWindow: LoadedPageWindow? = null,
    val scrollAnchor: LibraryScrollAnchor? = null,
    val selectedBookId: String? = null,
) {
    fun queryFingerprint(scope: LibraryScope): String = listOf(
        scope.name,
        query.trim(),
        if (scope == LibraryScope.Books) sort.name else "stable_name",
        if (scope == LibraryScope.Books) viewMode.name else "list",
        if (scope == LibraryScope.Books) filters.mediaKinds.map { it.wireValue }.sorted().joinToString(",") else "",
        if (scope == LibraryScope.Books) filters.readingStatuses.map { it.wireValue }.sorted().joinToString(",") else "",
        if (scope == LibraryScope.Books) filters.downloadedOnly.toString() else "false",
    ).joinToString("|")
}

sealed interface LibraryContentPhase {
    data object InitialLoading : LibraryContentPhase
    data object Ready : LibraryContentPhase
    data object Empty : LibraryContentPhase
    data class InitialError(val errorCode: String) : LibraryContentPhase
    data object PermissionRevalidating : LibraryContentPhase
    data object Inaccessible : LibraryContentPhase
}

sealed interface RefreshPhase {
    data object Idle : RefreshPhase
    data object StaleRefreshing : RefreshPhase
}

sealed interface PaginationPhase {
    data object Idle : PaginationPhase
    data class Loading(val requestKey: String) : PaginationPhase
    data class Failed(val requestKey: String, val errorCode: String) : PaginationPhase
}

data class LibraryDiscoveryScopeState(
    val snapshot: LibraryScopeSnapshot = LibraryScopeSnapshot(),
    val contentPhase: LibraryContentPhase = LibraryContentPhase.InitialLoading,
    val refreshPhase: RefreshPhase = RefreshPhase.Idle,
    val paginationPhase: PaginationPhase = PaginationPhase.Idle,
)

data class LibraryDiscoveryState(
    val selectedScope: LibraryScope = LibraryScope.Books,
    val scopes: Map<LibraryScope, LibraryDiscoveryScopeState> = LibraryScope.entries.associateWith {
        LibraryDiscoveryScopeState()
    },
    val offlineFilterAvailability: OfflineFilterAvailability = OfflineFilterAvailability.Unavailable(
        LibraryDiscoveryRuntime.OFFLINE_FILTER_NOT_SUPPORTED,
    ),
) {
    val current: LibraryDiscoveryScopeState get() = scopes.getValue(selectedScope)
}

sealed interface LibraryRoute {
    val routeKey: String
    val entityId: String?

    data object Root : LibraryRoute {
        override val routeKey: String = "library.root"
        override val entityId: String? = null
    }

    data class Search(val scope: LibraryScope) : LibraryRoute {
        override val routeKey: String = "library.search"
        override val entityId: String = scope.name
    }

    data class Facet(val kind: FacetKind, val id: String) : LibraryRoute {
        init {
            require(id.isNotBlank())
        }

        override val routeKey: String = "library.facet.${kind.name.lowercase()}"
        override val entityId: String = id
    }

    data class Book(val id: String) : LibraryRoute {
        init {
            require(id.isNotBlank())
        }

        override val routeKey: String = "library.book"
        override val entityId: String = id
    }
}

data class LibraryRequestToken(
    val scope: LibraryScope,
    val queryFingerprint: String,
    val page: Int,
    val generation: Long,
) {
    init {
        require(page > 0)
    }

    val requestKey: String get() = "$queryFingerprint|$page"
}

sealed interface FilterCommitResult {
    data object Applied : FilterCommitResult
    data class Rejected(val reasonCode: String) : FilterCommitResult
}

/**
 * Shared state owner for Library Discovery. Platform stores retain only coroutine/lifecycle and UI mapping.
 * Network responses are guarded by query identity and generation so an obsolete response cannot mutate state.
 */
class LibraryDiscoveryRuntime(
    offlineFilterAvailability: OfflineFilterAvailability = OfflineFilterAvailability.Unavailable(
        OFFLINE_FILTER_NOT_SUPPORTED,
    ),
) {
    var state: LibraryDiscoveryState = LibraryDiscoveryState(
        offlineFilterAvailability = offlineFilterAvailability,
    )
        private set

    private val generations = LibraryScope.entries.associateWith { 0L }.toMutableMap()

    fun selectScope(scope: LibraryScope) {
        state = state.copy(selectedScope = scope)
    }

    fun updateQuery(scope: LibraryScope, query: String) = updateSnapshot(scope) { it.copy(query = query) }

    fun updateSort(scope: LibraryScope, sort: LibrarySort) {
        if (scope == LibraryScope.Books) updateSnapshot(scope) { it.copy(sort = sort) }
    }

    fun updateViewMode(scope: LibraryScope, viewMode: LibraryViewMode) {
        if (scope == LibraryScope.Books) updateSnapshot(scope) { it.copy(viewMode = viewMode) }
    }

    fun rememberScrollAnchor(scope: LibraryScope, anchor: LibraryScrollAnchor?) =
        updateSnapshot(scope) { it.copy(scrollAnchor = anchor) }

    fun selectBook(scope: LibraryScope, bookId: String?) =
        updateSnapshot(scope) { it.copy(selectedBookId = bookId) }

    fun applyFilters(filters: LibraryFilters): FilterCommitResult {
        val availability = state.offlineFilterAvailability
        if (filters.downloadedOnly && availability is OfflineFilterAvailability.Unavailable) {
            return FilterCommitResult.Rejected(availability.reasonCode)
        }
        updateSnapshot(LibraryScope.Books) { it.copy(filters = filters) }
        return FilterCommitResult.Applied
    }

    fun beginInitialRequest(scope: LibraryScope, retainsVisibleContent: Boolean): LibraryRequestToken {
        val generation = generations.getValue(scope) + 1
        generations[scope] = generation
        val snapshot = state.scopes.getValue(scope).snapshot
        updateScope(scope) {
            it.copy(
                contentPhase = if (retainsVisibleContent) LibraryContentPhase.Ready else LibraryContentPhase.InitialLoading,
                refreshPhase = if (retainsVisibleContent) RefreshPhase.StaleRefreshing else RefreshPhase.Idle,
                paginationPhase = PaginationPhase.Idle,
            )
        }
        return LibraryRequestToken(scope, snapshot.queryFingerprint(scope), 1, generation)
    }

    fun beginNextPage(scope: LibraryScope, page: Int): LibraryRequestToken? {
        val current = state.scopes.getValue(scope)
        val generation = generations.getValue(scope)
        if (generation == 0L) return null
        val token = LibraryRequestToken(scope, current.snapshot.queryFingerprint(scope), page, generation)
        val pagination = current.paginationPhase
        if (pagination is PaginationPhase.Loading && pagination.requestKey == token.requestKey) return null
        updateScope(scope) { it.copy(paginationPhase = PaginationPhase.Loading(token.requestKey)) }
        return token
    }

    fun acceptPage(token: LibraryRequestToken, isEmpty: Boolean, source: ContentSource, isStale: Boolean): Boolean {
        if (!isCurrent(token)) return false
        updateScope(token.scope) { current ->
            val priorWindow = current.snapshot.loadedPageWindow
            val nextWindow = if (token.page == 1 || priorWindow == null) {
                LoadedPageWindow(token.page, token.page)
            } else {
                LoadedPageWindow(minOf(priorWindow.firstPage, token.page), maxOf(priorWindow.lastPage, token.page))
            }
            current.copy(
                snapshot = current.snapshot.copy(loadedPageWindow = nextWindow),
                contentPhase = if (isEmpty) LibraryContentPhase.Empty else LibraryContentPhase.Ready,
                refreshPhase = if (isStale) RefreshPhase.StaleRefreshing else RefreshPhase.Idle,
                paginationPhase = PaginationPhase.Idle,
            )
        }
        return true
    }

    fun fail(token: LibraryRequestToken, errorCode: String, hasVisibleContent: Boolean): Boolean {
        if (!isCurrent(token)) return false
        updateScope(token.scope) { current ->
            if (token.page > 1) {
                current.copy(paginationPhase = PaginationPhase.Failed(token.requestKey, errorCode))
            } else {
                current.copy(
                    refreshPhase = RefreshPhase.Idle,
                    contentPhase = LibraryContentPhase.InitialError(errorCode),
                )
            }
        }
        return true
    }

    fun beginPermissionRevalidation() {
        state = state.copy(
            scopes = state.scopes.mapValues { (_, scopeState) ->
                scopeState.copy(
                    snapshot = scopeState.snapshot.copy(
                        loadedPageWindow = null,
                        scrollAnchor = null,
                        selectedBookId = null,
                    ),
                    contentPhase = LibraryContentPhase.PermissionRevalidating,
                    refreshPhase = RefreshPhase.Idle,
                    paginationPhase = PaginationPhase.Idle,
                )
            },
        )
        LibraryScope.entries.forEach { scope -> generations[scope] = generations.getValue(scope) + 1 }
    }

    fun markInaccessible(scope: LibraryScope) {
        updateScope(scope) {
            it.copy(
                snapshot = it.snapshot.copy(loadedPageWindow = null, scrollAnchor = null, selectedBookId = null),
                contentPhase = LibraryContentPhase.Inaccessible,
                refreshPhase = RefreshPhase.Idle,
                paginationPhase = PaginationPhase.Idle,
            )
        }
    }

    private fun isCurrent(token: LibraryRequestToken): Boolean {
        val current = state.scopes.getValue(token.scope).snapshot
        return generations.getValue(token.scope) == token.generation &&
            current.queryFingerprint(token.scope) == token.queryFingerprint
    }

    private fun updateSnapshot(scope: LibraryScope, transform: (LibraryScopeSnapshot) -> LibraryScopeSnapshot) {
        updateScope(scope) { it.copy(snapshot = transform(it.snapshot)) }
    }

    private fun updateScope(scope: LibraryScope, transform: (LibraryDiscoveryScopeState) -> LibraryDiscoveryScopeState) {
        val next = transform(state.scopes.getValue(scope))
        state = state.copy(scopes = state.scopes + (scope to next))
    }

    companion object {
        const val SEARCH_DEBOUNCE_MILLIS: Long = 300L
        const val OFFLINE_FILTER_NOT_SUPPORTED: String = "MANAGED_DOWNLOADS_UNAVAILABLE"
    }
}
