package com.ermao.library.shared.modules.library.application

import com.ermao.library.shared.modules.library.ContentSource
import com.ermao.library.shared.modules.library.LibraryFilters
import com.ermao.library.shared.modules.library.LibraryScope
import com.ermao.library.shared.modules.library.OfflineFilterAvailability
import com.ermao.library.shared.modules.library.domain.FacetKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LibraryDiscoveryRuntimeTest {
    @Test
    fun scopeSelectionPreservesIndependentQueriesAndAnchors() {
        val runtime = LibraryDiscoveryRuntime()
        runtime.updateQuery(LibraryScope.Works, "三体")
        runtime.rememberScrollAnchor(LibraryScope.Works, LibraryScrollAnchor("work-9", 18))
        runtime.updateQuery(LibraryScope.Series, "基地")
        runtime.rememberScrollAnchor(LibraryScope.Series, LibraryScrollAnchor("series-2", 4))

        runtime.selectScope(LibraryScope.Series)
        runtime.selectScope(LibraryScope.Works)

        assertEquals("三体", runtime.state.current.snapshot.query)
        assertEquals("work-9", runtime.state.current.snapshot.scrollAnchor?.itemId)
        assertEquals("基地", runtime.state.scopes.getValue(LibraryScope.Series).snapshot.query)
        assertEquals("series-2", runtime.state.scopes.getValue(LibraryScope.Series).snapshot.scrollAnchor?.itemId)
    }

    @Test
    fun obsoleteResponseCannotOverwriteNewQuery() {
        val runtime = LibraryDiscoveryRuntime()
        runtime.updateQuery(LibraryScope.Works, "old")
        val oldRequest = runtime.beginInitialRequest(LibraryScope.Works, retainsVisibleContent = false)
        runtime.updateQuery(LibraryScope.Works, "new")
        val newRequest = runtime.beginInitialRequest(LibraryScope.Works, retainsVisibleContent = false)

        assertFalse(runtime.acceptPage(oldRequest, isEmpty = false, ContentSource.Network, isStale = false))
        assertTrue(runtime.acceptPage(newRequest, isEmpty = false, ContentSource.Network, isStale = false))
        assertIs<LibraryContentPhase.Ready>(runtime.state.current.contentPhase)
    }

    @Test
    fun unavailableOfflineFilterIsRejectedWithoutChangingCommittedFilters() {
        val runtime = LibraryDiscoveryRuntime(
            OfflineFilterAvailability.Unavailable(LibraryDiscoveryRuntime.OFFLINE_FILTER_NOT_SUPPORTED),
        )

        val result = runtime.applyFilters(LibraryFilters(downloadedOnly = true))

        assertIs<FilterCommitResult.Rejected>(result)
        assertFalse(runtime.state.scopes.getValue(LibraryScope.Works).snapshot.filters.downloadedOnly)
    }

    @Test
    fun duplicatePaginationRequestIsRejectedAndRetryKeepsSameRequestKey() {
        val runtime = LibraryDiscoveryRuntime()
        val initial = runtime.beginInitialRequest(LibraryScope.Works, retainsVisibleContent = false)
        assertTrue(runtime.acceptPage(initial, isEmpty = false, ContentSource.Network, isStale = false))

        val first = requireNotNull(runtime.beginNextPage(LibraryScope.Works, 2))
        assertNull(runtime.beginNextPage(LibraryScope.Works, 2))
        assertTrue(runtime.fail(first, "NETWORK_UNAVAILABLE", hasVisibleContent = true))
        val retry = requireNotNull(runtime.beginNextPage(LibraryScope.Works, 2))

        assertEquals(first.requestKey, retry.requestKey)
    }

    @Test
    fun cachedAndStalePhasesRemainMutuallyExclusive() {
        val runtime = LibraryDiscoveryRuntime()
        val request = runtime.beginInitialRequest(LibraryScope.Works, retainsVisibleContent = false)

        runtime.acceptPage(request, isEmpty = false, ContentSource.Cache, isStale = true)

        assertIs<LibraryContentPhase.OfflineCached>(runtime.state.current.contentPhase)
        assertIs<RefreshPhase.StaleRefreshing>(runtime.state.current.refreshPhase)
    }

    @Test
    fun permissionRevalidationDropsPrivateStateAndInvalidatesOutstandingRequests() {
        val runtime = LibraryDiscoveryRuntime()
        runtime.rememberScrollAnchor(LibraryScope.Works, LibraryScrollAnchor("private-work"))
        runtime.selectWork(LibraryScope.Works, "private-work")
        val request = runtime.beginInitialRequest(LibraryScope.Works, retainsVisibleContent = false)

        runtime.beginPermissionRevalidation()

        val state = runtime.state.scopes.getValue(LibraryScope.Works)
        assertIs<LibraryContentPhase.PermissionRevalidating>(state.contentPhase)
        assertNull(state.snapshot.scrollAnchor)
        assertNull(state.snapshot.selectedWorkId)
        assertFalse(runtime.acceptPage(request, isEmpty = false, ContentSource.Network, isStale = false))
    }

    @Test
    fun stableRoutesExposeRouteAndEntityIdentity() {
        val first = LibraryRoute.Facet(FacetKind.Series, "series-1")
        val duplicate = LibraryRoute.Facet(FacetKind.Series, "series-1")
        val other = LibraryRoute.Facet(FacetKind.Series, "series-2")

        assertEquals(first.routeKey to first.entityId, duplicate.routeKey to duplicate.entityId)
        assertTrue(first.routeKey to first.entityId != other.routeKey to other.entityId)
    }
}
