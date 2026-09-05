package com.ermao.library.features.reader.infrastructure

import androidx.test.core.app.ApplicationProvider
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderPagePresentation
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4

@RunWith(AndroidJUnit4::class)
class AndroidReaderBookmarkCoordinatorInstrumentedTest {
    @Test
    fun persistsReloadsNavigatesAndDeletesAComicPosition() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val namespace = ReaderSyncNamespace(
            serverIdentity = "bookmark-test-${UUID.randomUUID()}",
            userId = "instrumented-user",
            authorizationVersion = 0,
        )
        val resourceId = "comic-${UUID.randomUUID()}"
        val store = AndroidReaderBookmarkStore(context, namespace, resourceId)
        try {
            val position = comicPosition()
            var navigated: ReaderPositionReport? = null
            val first = AndroidReaderBookmarkCoordinator(
                bookmarkStore = store,
                bookmarkSyncPort = null,
                bookmarkSyncTarget = null,
                currentPosition = { position },
                bookmarkLabel = { "第 2 页" },
                bookmarkId = { "comic:position:pages/2.jpg:1" },
                navigateToPosition = {
                    navigated = it
                    true
                },
            )

            first.load()
            val change = first.toggleCurrentBookmark()
            assertNotNull(change)
            assertTrue(change!!.added)
            assertEquals(1, first.bookmarks.value.size)
            assertEquals(1, store.load().bookmarks.size)
            assertEquals(null, store.load().pending)

            val reloaded = AndroidReaderBookmarkCoordinator(
                bookmarkStore = store,
                bookmarkSyncPort = null,
                bookmarkSyncTarget = null,
                currentPosition = { position },
                bookmarkLabel = { "第 2 页" },
                bookmarkId = { "comic:position:pages/2.jpg:1" },
                navigateToPosition = {
                    navigated = it
                    true
                },
            )
            reloaded.load()
            assertEquals(listOf(change.bookmarkId), reloaded.bookmarks.value.map { it.id })
            assertTrue(reloaded.goToBookmark(change.bookmarkId))
            assertEquals(position, navigated)

            reloaded.removeBookmark(change.bookmarkId)
            assertTrue(reloaded.bookmarks.value.isEmpty())
            assertTrue(store.load().bookmarks.isEmpty())
        } finally {
            AndroidReaderBookmarkStore.clearNamespace(context, namespace)
        }
    }

    @Test
    fun persistsReloadsNavigatesAndDeletesAPdfPosition() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val namespace = ReaderSyncNamespace(
            serverIdentity = "bookmark-test-${UUID.randomUUID()}",
            userId = "instrumented-user",
            authorizationVersion = 0,
        )
        val resourceId = "pdf-${UUID.randomUUID()}"
        val store = AndroidReaderBookmarkStore(context, namespace, resourceId)
        try {
            val position = pdfPosition()
            var navigated: ReaderPositionReport? = null
            val coordinator = AndroidReaderBookmarkCoordinator(
                bookmarkStore = store,
                bookmarkSyncPort = null,
                bookmarkSyncTarget = null,
                currentPosition = { position },
                bookmarkLabel = { "第 3 页" },
                bookmarkId = { "pdf:position:2" },
                navigateToPosition = {
                    navigated = it
                    true
                },
            )

            coordinator.load()
            val change = coordinator.toggleCurrentBookmark()
            assertNotNull(change)
            assertTrue(change!!.added)
            assertEquals(1, coordinator.bookmarks.value.size)

            val reloaded = AndroidReaderBookmarkCoordinator(
                bookmarkStore = store,
                bookmarkSyncPort = null,
                bookmarkSyncTarget = null,
                currentPosition = { position },
                bookmarkLabel = { "第 3 页" },
                bookmarkId = { "pdf:position:2" },
                navigateToPosition = {
                    navigated = it
                    true
                },
            )
            reloaded.load()
            assertEquals(listOf(change.bookmarkId), reloaded.bookmarks.value.map { it.id })
            assertTrue(reloaded.goToBookmark(change.bookmarkId))
            assertEquals(position, navigated)

            reloaded.removeBookmark(change.bookmarkId)
            assertTrue(reloaded.bookmarks.value.isEmpty())
            assertTrue(store.load().bookmarks.isEmpty())
        } finally {
            AndroidReaderBookmarkStore.clearNamespace(context, namespace)
        }
    }

    private fun comicPosition(): ReaderPositionReport = ReaderPositionReport(
        locator = ReaderOpaqueLocator.parse(
            """{"href":"pages/2.jpg","type":"image/jpeg","locations":{"position":2,"progression":0}}""",
        ),
        presentation = ReaderPositionPresentation(
            displayPercent = 50.0,
            totalProgression = 0.5,
            currentHref = "pages/2.jpg",
            chapter = null,
            page = ReaderPagePresentation(number = 2, total = 4),
            playback = null,
        ),
    )

    private fun pdfPosition(): ReaderPositionReport = ReaderPositionReport(
        locator = ReaderOpaqueLocator.parse(
            """{"href":"publication.pdf","type":"application/pdf","locations":{"position":3,"progression":0.4}}""",
        ),
        presentation = ReaderPositionPresentation(
            displayPercent = 40.0,
            totalProgression = 0.4,
            currentHref = "publication.pdf",
            chapter = null,
            page = ReaderPagePresentation(number = 3, total = 6),
            playback = null,
        ),
    )
}
