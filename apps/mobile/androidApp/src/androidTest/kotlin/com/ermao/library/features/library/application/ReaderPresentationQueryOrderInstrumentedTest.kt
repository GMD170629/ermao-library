package com.ermao.library.features.library.application

import android.os.Looper
import android.util.Log
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.features.home.application.HomeViewModel
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BookContentTarget
import com.ermao.library.shared.modules.library.BooksQuery
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.ContinueReadingItem
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.GroupingQuery
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.ResourceReadingUnitsPage
import com.ermao.library.shared.modules.library.ResourceReadingUnitsQuery
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.library.domain.ReadingUnitMetadata
import com.ermao.library.shared.modules.library.domain.Resource
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionPresentationQuery
import com.ermao.library.shared.modules.reader.ReaderPositionPresentationSnapshot
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.shelf.domain.ShelfMembershipChange
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TestName
import org.junit.runner.RunWith

/** RISK-08: real ViewModels; only owned repository/query boundaries are controlled. */
@RunWith(AndroidJUnit4::class)
class ReaderPresentationQueryOrderInstrumentedTest {
    @get:Rule val testName = TestName()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val stores = mutableListOf<ViewModelStore>()
    private val jobs = mutableListOf<Job>()
    private val gates = mutableListOf<CompletableDeferred<Unit>>()
    private val request = ContentRequestContext(
        ServerProfile(
            "risk08-profile", "RISK-08 owned fixture",
            (ServerBaseUrl.parse("https://risk08.invalid") as ServerBaseUrlParseResult.Valid).baseUrl,
            "risk08-server", false, TlsMode.SystemTrust,
        ),
        PrivateDataNamespace("risk08-server", "risk08-user", 1),
    )
    private var eventNumber = 0

    @After
    fun clearViewModels() {
        main {
            stores.forEach(ViewModelStore::clear)
            gates.forEach { it.complete(Unit) }
        }
        runBlocking { withTimeout(10_000) { jobs.forEach { it.join() } } }
        instrumentation.waitForIdleSync()
        assertTrue("All owned ViewModel jobs must finish", jobs.all { it.isCompleted })
        main { event("cleanup: ViewModelStore.clear; gates released; all jobs completed") }
    }

    @Test
    fun detailOlderQueryCannotReplaceNewContentOrReadingUnits() {
        val releaseA = gate()
        val enteredA = CountDownLatch(1)
        val repository = OwnedContentRepository(bookTitles = listOf("A", "B"), unitTitles = listOf("B-units", "A-units"))
        val query = query(setOf(BOOK), {
            event("A: presentation entered after production generation guard")
            enteredA.countDown()
            releaseA.await()
            event("A: presentation returning after B completed")
            emptyList()
        }, { emptyList() })
        val viewModel = main { detail(repository, query) }
        await(enteredA)
        // retry is a supported load entry even while initial A isLoading; no private load copy.
        main { viewModel.retry() }
        instrumentation.waitForIdleSync()
        val expected = "B" to listOf("B-units")
        assertEquals("Fixture must complete B before releasing A", expected, main { detailDisplay(viewModel) })
        main { event("B committed: ${detailDisplay(viewModel)}"); releaseA.complete(Unit) }
        instrumentation.waitForIdleSync()
        val actual = main { detailDisplay(viewModel).also { event("after A: $it") } }
        assertEquals("Late Detail A must not overwrite B content or readingUnits", expected, actual)
    }

    @Test
    fun homeCancelledQueryCannotCommitOldStateAfterNewLoad() {
        val releaseCancellation = gate()
        val neverReturns = gate()
        val enteredA = CountDownLatch(1)
        val cancelledA = CountDownLatch(1)
        val repository = OwnedContentRepository(homeTitles = listOf("A", "B"))
        val query = query(emptySet(), {
            event("A: cancellable presentation entered")
            enteredA.countDown()
            try {
                neverReturns.await()
                error("A must be cancelled")
            } catch (cancelled: CancellationException) {
                event("A: received cancellation; holding unwind, not swallowing it")
                cancelledA.countDown()
                withContext(NonCancellable) { releaseCancellation.await() }
                event("A: rethrow cancellation; active=${currentCoroutineContext().isActive}")
                throw cancelled
            }
        }, { emptyList() })
        val viewModel = main { home(repository, query) }
        await(enteredA)
        main { viewModel.refresh() }
        await(cancelledA)
        instrumentation.waitForIdleSync()
        assertEquals("Fixture must complete B while A cancellation is held", "B", main { homeTitle(viewModel) })
        main { event("B committed: ${homeTitle(viewModel)}"); releaseCancellation.complete(Unit) }
        instrumentation.waitForIdleSync()
        val actual = main { homeTitle(viewModel).also { event("after cancelled A: $it") } }
        assertEquals("Cancelled Home A must not commit old content after B", "B", actual)
    }

    @Test
    fun homeQueryFailureMustPreserveDisplayedPending() {
        val repository = OwnedContentRepository(homeTitles = listOf("initial", "refresh"))
        val viewModel = main { home(repository, query(emptySet(), { pending() }, { throw IOException("RISK08_OWNED_QUERY_FAILURE") })) }
        instrumentation.waitForIdleSync()
        assertEquals("Fixture must display pending before failure", 73, main { homePercent(viewModel) })
        main { event("before failure: ${homePercent(viewModel)}"); viewModel.refresh() }
        instrumentation.waitForIdleSync()
        val actual = main { homePercent(viewModel).also { event("after query failure: $it; error=${viewModel.uiState.value.errorCode}") } }
        assertEquals("Home query failure is not successful empty pending", 73, actual)
        assertEquals("CONTENT_LOAD_FAILED", main { viewModel.uiState.value.errorCode })
        assertEquals(false, main { viewModel.uiState.value.isRefreshing })
    }

    @Test
    fun detailQueryFailureMustPreserveDisplayedPending() {
        val repository = OwnedContentRepository(bookTitles = listOf("initial", "refresh"), unitTitles = listOf("initial-units", "refresh-units"))
        val viewModel = main { detail(repository, query(setOf(BOOK), { pending() }, { throw IOException("RISK08_OWNED_QUERY_FAILURE") })) }
        instrumentation.waitForIdleSync()
        assertEquals("Fixture must display pending before failure", 73, main { viewModel.uiState.value.content?.book?.progressPercent })
        main { event("before failure: 73"); viewModel.refresh() }
        instrumentation.waitForIdleSync()
        val actual = main {
            viewModel.uiState.value.content?.book?.progressPercent.also {
                event("after query failure: $it; error=${viewModel.uiState.value.errorCode}")
            }
        }
        assertEquals("Detail query failure is not successful empty pending", 73, actual)
        assertEquals("CONTENT_LOAD_FAILED", main { viewModel.uiState.value.errorCode })
        assertEquals(false, main { viewModel.uiState.value.isSurfaceLoading })
    }

    @Test
    fun homeSuccessfulEmptyQueryClearsFormerPendingProjection() {
        val repository = OwnedContentRepository(homeTitles = listOf("pending", "acknowledged"))
        val viewModel = main { home(repository, query(emptySet(), { pending() }, { emptyList() })) }
        instrumentation.waitForIdleSync()
        assertEquals(73, main { homePercent(viewModel) })
        main { viewModel.refresh() }
        instrumentation.waitForIdleSync()
        val actual = main { homePercent(viewModel).also { event("successful empty query: $it") } }
        assertEquals("Successful empty query must clear old projection and show server progress", 16, actual)
    }

    private fun home(repository: ContentRepository, query: ReaderPositionPresentationQuery): HomeViewModel =
        own(HomeViewModel(repository, request, application(), { error("Unexpected authorization callback") }, query))

    private fun detail(repository: ContentRepository, query: ReaderPositionPresentationQuery): WorkDetailViewModel =
        own(WorkDetailViewModel(
            repository, unusedShelves, request, application(), BOOK,
            { error("Unexpected authorization callback") }, BookContentTarget.ResourceDetail(RESOURCE),
            SavedStateHandle(), query,
        ))

    private fun application(): ErmaoLibraryApplication =
        ApplicationProvider.getApplicationContext<ErmaoLibraryApplication>().also {
            assertEquals("Instrumentation must use isolated UID", "com.ermao.library.releasecheck", it.packageName)
        }

    private fun <T : ViewModel> own(viewModel: T): T {
        stores += ViewModelStore().also { it.put("risk08", viewModel) }
        jobs += requireNotNull(viewModel.viewModelScope.coroutineContext[Job])
        return viewModel
    }

    private fun detailDisplay(viewModel: WorkDetailViewModel): Pair<String?, List<String?>> =
        viewModel.uiState.value.let { it.content?.book?.title to it.readingUnits?.units.orEmpty().map(ReadingUnit::title) }

    private fun homeTitle(viewModel: HomeViewModel): String? = viewModel.uiState.value.content?.continueReading?.book?.title
    private fun homePercent(viewModel: HomeViewModel): Int? = viewModel.uiState.value.content?.continueReading?.book?.progressPercent

    private fun query(
        expectedBooks: Set<String>,
        vararg replies: suspend () -> List<ReaderPositionPresentationSnapshot>,
    ): ReaderPositionPresentationQuery = object : ReaderPositionPresentationQuery {
        private val remaining = ArrayDeque(replies.toList())
        override suspend fun load(namespace: ReaderSyncNamespace, clientId: String, bookIds: Set<String>): List<ReaderPositionPresentationSnapshot> {
            assertEquals(ReaderSyncNamespace("risk08-server", "risk08-user", 1), namespace)
            assertTrue(clientId.isNotBlank())
            assertEquals(expectedBooks, bookIds)
            event("query call; remaining=${remaining.size}")
            return remaining.removeFirst().invoke()
        }
    }

    private fun pending(): List<ReaderPositionPresentationSnapshot> = listOf(
        ReaderPositionPresentationSnapshot(BOOK, RESOURCE, 1000, ReaderPositionPresentation(73.0, 0.73, null, null, null, null)),
    )

    private fun gate(): CompletableDeferred<Unit> = CompletableDeferred<Unit>().also { gates += it }
    private fun await(latch: CountDownLatch) { assertTrue("Controlled query did not reach requested boundary", latch.await(10, TimeUnit.SECONDS)) }

    private fun event(message: String) {
        check(Looper.myLooper() == Looper.getMainLooper())
        Log.i("Risk08QueryOrder", "${testName.methodName} ${++eventNumber}: $message")
    }

    private fun <T> main(action: () -> T): T {
        val result = AtomicReference<Result<T>>()
        instrumentation.runOnMainSync { result.set(runCatching(action)) }
        return result.get().getOrThrow()
    }

    private inner class OwnedContentRepository(
        homeTitles: List<String> = emptyList(),
        bookTitles: List<String> = emptyList(),
        unitTitles: List<String> = emptyList(),
    ) : ContentRepository {
        private val homes = ArrayDeque(homeTitles)
        private val books = ArrayDeque(bookTitles)
        private val units = ArrayDeque(unitTitles)

        override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> {
            assertEquals(request, context)
            val title = homes.removeFirst()
            event("repository Home $title")
            return ContentResult.Content(HomeSnapshot(
                HomeSection.Content(ContinueReadingItem(BOOK, title, null, "", "AUDIO", "audio", RESOURCE, 16.0, null, null, null, null)),
                HomeSection.Content(listOf(BookSummary(BOOK, title, null, "", 16.0))),
                HomeSection.Content(emptyList()),
            ))
        }

        override suspend fun loadBookDetail(context: ContentRequestContext, query: BookDetailQuery): ContentResult<BookDetailSummary> {
            assertEquals(request, context)
            assertEquals(BOOK, query.bookId)
            val title = books.removeFirst()
            event("repository Detail $title")
            return ContentResult.Content(BookDetailSummary(
                id = BOOK, sourceNodeId = "risk08-source", title = title, author = null,
                description = null, tags = emptyList(), seriesName = null, seriesIndex = null,
                coverStatus = "ready", coverUrl = "", continueResourceId = RESOURCE,
                continueResourceProgress = 16.0, completed = false, resources = listOf(resource()),
            ))
        }

        override suspend fun loadResourceReadingUnits(context: ContentRequestContext, query: ResourceReadingUnitsQuery): ContentResult<ResourceReadingUnitsPage> {
            assertEquals(request, context)
            assertEquals(RESOURCE, query.resourceId)
            val title = units.removeFirst()
            event("repository readingUnits $title")
            return ContentResult.Content(ResourceReadingUnitsPage(
                BOOK, RESOURCE, listOf(ReadingUnit(
                    id = title, resourceId = RESOURCE, assetId = null, unitType = "audio", title = title,
                    href = null, mediaType = "audio/mpeg", sortOrder = 0, startMillis = 0,
                    endMillis = 10000, durationMillis = 10000, width = null, height = null, sizeBytes = null,
                    metadata = ReadingUnitMetadata(null, null, null, null, null, null, null, null, null, null, null, null, null, null),
                    createdAt = null, updatedAt = null,
                )), query.page, query.pageSize, 1, 1, currentHref = null,
                currentChapterIndex = null, currentChapterTitle = title, currentChapterSortOrder = null,
                currentPageNumber = null, progress = 16.0,
            ))
        }

        override suspend fun loadContinueReading(context: ContentRequestContext): Nothing = error("Unexpected loadContinueReading")
        override suspend fun loadRecentReading(context: ContentRequestContext, limit: Int): Nothing = error("Unexpected loadRecentReading")
        override suspend fun loadRecentAdded(context: ContentRequestContext, limit: Int): Nothing = error("Unexpected loadRecentAdded")
        override suspend fun loadBooks(context: ContentRequestContext, query: BooksQuery): Nothing = error("Unexpected loadBooks")
        override suspend fun loadGroupings(context: ContentRequestContext, query: GroupingQuery): Nothing = error("Unexpected loadGroupings")
        override suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): Nothing = error("Unexpected loadFacet")
        override suspend fun loadCover(context: ContentRequestContext, apiPath: String, etag: String?): ContentResult<AuthenticatedCover> = error("Unexpected loadCover")
        override suspend fun invalidate(namespace: PrivateDataNamespace): Nothing = error("Unexpected invalidate")
    }

    private fun resource(): Resource = Resource(
        id = RESOURCE, bookId = BOOK, sourceNodeId = "risk08-resource-source", title = "Owned audio",
        description = null, resourceIndex = null, sortOrder = 0, format = "AUDIO", readerType = "audio",
        readable = true, kindleSendAvailable = false, publisher = null, publishedAt = null,
        language = null, isbn = null, identifier = null, narrator = null, abridged = null,
        importStatus = "READY", importError = null, coverStatus = "ready", coverPath = null,
        coverUrl = "", sizeBytes = 0, pageCount = null, chapterCount = 1, durationMillis = 10000,
        trackCount = 1, progress = 16.0, lastReadAt = null, hidden = false, completed = false, assets = emptyList(),
    )

    private val unusedShelves = object : ShelfRepository {
        override suspend fun loadShelves(context: ShelfRequestContext, bookId: String): Nothing = error("Unexpected loadShelves")
        override suspend fun updateMembership(context: ShelfRequestContext, change: ShelfMembershipChange): Nothing = error("Unexpected updateMembership")
    }

    private companion object {
        const val BOOK = "risk08-book"
        const val RESOURCE = "risk08-resource"
    }
}
