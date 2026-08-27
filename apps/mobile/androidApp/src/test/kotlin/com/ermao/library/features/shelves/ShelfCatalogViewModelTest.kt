package com.ermao.library.features.shelves

import com.ermao.library.features.shelves.application.ShelfCatalogViewModel
import com.ermao.library.features.shelves.application.ShelfLoadState
import com.ermao.library.features.shelves.application.ShelfSaveState
import com.ermao.library.shared.modules.shelf.CreateShelfInput
import com.ermao.library.shared.modules.shelf.ShelfBookPreview
import com.ermao.library.shared.modules.shelf.ShelfCatalogEntry
import com.ermao.library.shared.modules.shelf.ShelfCatalogPage
import com.ermao.library.shared.modules.shelf.ShelfCatalogRepository
import com.ermao.library.shared.modules.shelf.ShelfCatalogScope
import com.ermao.library.shared.modules.shelf.ShelfError
import com.ermao.library.shared.modules.shelf.ShelfErrorKind
import com.ermao.library.shared.modules.shelf.ShelfKind
import com.ermao.library.shared.modules.shelf.createShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

@OptIn(ExperimentalCoroutinesApi::class)
class ShelfCatalogViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @Before fun setUp() { Dispatchers.setMain(dispatcher) }
    @After fun tearDown() { Dispatchers.resetMain() }

    @Test fun scopeSearchesRestoreIndependently() = runTest(dispatcher) {
        val model = model(Fake())
        advanceUntilIdle()
        model.search("Favorites")
        model.selectScope(ShelfCatalogScope.Collections)
        assertEquals("", model.state.value.query)
        model.search("Plan")
        model.selectScope(ShelfCatalogScope.All)
        assertEquals("Favorites", model.state.value.query)
    }

    @Test fun refreshFailureClearsPreviousPrivateContentButKeepsSearch() = runTest(dispatcher) {
        val fake = Fake()
        val model = model(fake)
        advanceUntilIdle()
        model.search("Favorites")
        fake.failure = ShelfErrorKind.Offline
        model.refresh()
        advanceUntilIdle()
        assertIs<ShelfLoadState.Failed>(model.state.value.content)
        assertEquals(emptyList(), model.state.value.visibleShelves)
        assertEquals("Favorites", model.state.value.query)
    }

    @Test fun paginationFailureKeepsLoadedBooksAndRetryDoesNotDuplicate() = runTest(dispatcher) {
        val fake = Fake()
        val model = model(fake, "s")
        advanceUntilIdle()
        fake.failure = ShelfErrorKind.Offline
        model.loadMore()
        advanceUntilIdle()
        val ready = assertIs<ShelfLoadState.Ready>(model.state.value.content)
        assertEquals(1, ready.detail?.shelf?.books?.size)
        assertEquals(ShelfErrorKind.Offline, model.state.value.paginationError?.kind)
        fake.failure = null
        model.loadMore()
        advanceUntilIdle()
        assertEquals(1, assertIs<ShelfLoadState.Ready>(model.state.value.content).detail?.shelf?.books?.size)
        assertEquals(2, assertIs<ShelfLoadState.Ready>(model.state.value.content).detail?.page)
    }

    @Test fun failedCreateDoesNotNavigateOrPublishSuccess() = runTest(dispatcher) {
        val fake = Fake()
        val model = model(fake)
        advanceUntilIdle()
        fake.failure = ShelfErrorKind.Server
        var navigations = 0
        model.create(CreateShelfInput("New", "", ShelfKind.Static, emptyList())) { navigations++ }
        advanceUntilIdle()
        assertEquals(0, navigations)
        assertIs<ShelfSaveState.Failed>(model.state.value.saveState)
    }

    @Test fun unauthorizedPaginationClearsContentAndReauthenticates() = runTest(dispatcher) {
        val fake = Fake()
        var reauth = 0
        val model = ShelfCatalogViewModel(fake, context(), "s") { reauth++ }
        advanceUntilIdle()
        fake.failure = ShelfErrorKind.Unauthorized
        model.loadMore()
        advanceUntilIdle()
        assertEquals(1, reauth)
        assertIs<ShelfLoadState.Failed>(model.state.value.content)
    }

    private fun model(fake: Fake, id: String? = null) = ShelfCatalogViewModel(fake, context(), id) {}
    private fun context() = createShelfRequestContext("p", "Books", "https://example.test", "server", false, "user", 1)
    private class Fake : ShelfCatalogRepository {
        var failure: ShelfErrorKind? = null
        private val shelf = ShelfCatalogEntry("s", "Favorites", null, ShelfKind.Static, 2,
            listOf(ShelfBookPreview("b", "Book", null, "", 0.0)), emptyList(), true)
        private fun <T> result(value: T): ShelfResult<T> = failure?.let { ShelfResult.Failure(ShelfError(it, "TEST")) } ?: ShelfResult.Content(value)
        override suspend fun loadCatalog(context: ShelfRequestContext) = result(listOf(shelf))
        override suspend fun loadPage(context: ShelfRequestContext, shelfId: String, page: Int) = result(ShelfCatalogPage(shelf, emptyList(), page, 2))
        override suspend fun createShelf(context: ShelfRequestContext, input: CreateShelfInput) = result("created")
    }
}
