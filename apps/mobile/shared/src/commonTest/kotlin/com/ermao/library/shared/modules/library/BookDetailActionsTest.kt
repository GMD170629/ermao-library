package com.ermao.library.shared.modules.library

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertNotNull

class BookDetailActionsTest {
    @Test
    fun bookActionsNeverBecomeContinueResourceActions() {
        for (readingId in listOf(null, "last-read", "another-volume")) {
            val scope = assertNotNull(resolveBookDetailActionScope(true, "book", null, readingId))
            assertEquals(BookDetailObjectKind.Book, scope.objectKind)
            assertEquals("book", scope.objectId)
            assertEquals(readingId, scope.readingResourceId)
            assertEquals(true, scope.includesBookActions)
        }
    }

    @Test
    fun resourceBoundBookStillOwnsBookActions() {
        val scope = assertNotNull(resolveBookDetailActionScope(true, "book", "bound", "other"))
        assertEquals(BookDetailObjectKind.Book, scope.objectKind)
        assertEquals("book", scope.objectId)
        assertEquals("bound", scope.readingResourceId)
    }

    @Test
    fun resourcePageActsOnThatResourceAndDoesNotOfferBookActions() {
        val scope = assertNotNull(resolveBookDetailActionScope(false, "book", "volume", "other"))
        assertEquals(BookDetailObjectKind.Resource, scope.objectKind)
        assertEquals("volume", scope.objectId)
        assertEquals("volume", scope.readingResourceId)
        assertEquals(false, scope.includesBookActions)
    }

    @Test
    fun childDirectoryDoesNotAcquireTheBookActionBar() {
        assertNull(resolveBookDetailActionScope(false, "book", null, "last-read"))
    }

    @Test
    fun bookDownloadStateIncludesEveryResourceAndReportsOnlyVerifiedCount() {
        assertEquals(BookDetailDownloadSummary(BookDetailDownloadState.NotDownloaded, 0), summarizeBookDetailDownloads(emptyList()))
        assertEquals(BookDetailDownloadSummary(BookDetailDownloadState.Downloaded, 2), summarizeBookDetailDownloads(listOf(BookDetailDownloadState.Downloaded, BookDetailDownloadState.Downloaded)))
        for (state in listOf(BookDetailDownloadState.Downloading, BookDetailDownloadState.Failed, BookDetailDownloadState.Paused)) {
            assertEquals(BookDetailDownloadSummary(state, 1), summarizeBookDetailDownloads(listOf(BookDetailDownloadState.Downloaded, state)))
        }
        assertEquals(BookDetailDownloadState.Downloading, summarizeBookDetailDownloads(listOf(BookDetailDownloadState.Paused, BookDetailDownloadState.Failed, BookDetailDownloadState.Downloading)).state)
    }
}
