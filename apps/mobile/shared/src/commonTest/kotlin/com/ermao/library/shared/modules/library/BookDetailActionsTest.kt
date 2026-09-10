package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.downloads.DownloadManagementItem
import com.ermao.library.shared.modules.downloads.DownloadManagementPolicy
import com.ermao.library.shared.modules.downloads.DownloadTaskStatus

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertNotNull

class BookDetailActionsTest {
    @Test fun detailIdentityDoesNotFollowTheReadingTarget() {
        assertEquals(BookDetailIdentitySource.Book, resolveBookDetailIdentitySource(true, true))
        assertEquals(BookDetailIdentitySource.Book, resolveBookDetailIdentitySource(true, false))
        assertEquals(BookDetailIdentitySource.Resource, resolveBookDetailIdentitySource(false, true))
        assertEquals(BookDetailIdentitySource.Directory, resolveBookDetailIdentitySource(false, false))
        assertEquals(false, hasVersionedCover("/api/books/b/cover"))
        assertEquals(false, hasVersionedCover("/api/books/b/cover?v="))
        assertEquals(true, hasVersionedCover("/api/books/b/cover?size=small&v=revision"))
        assertEquals("/api/books/b/cover?v=revision&size=small", smallCoverRequestPath("/api/books/b/cover?size=large&v=revision"))
    }

    @Test
    fun managementEntryCountTracksVerifiedCopiesAndRemoval() {
        val completed = DownloadManagementPolicy.project(DownloadManagementItem(
            "valid", DownloadTaskStatus.Completed, verified = true, active = false, available = false,
        ))
        val invalid = DownloadManagementPolicy.project(DownloadManagementItem(
            "invalid", DownloadTaskStatus.Completed, verified = false, active = false, available = true,
        ))
        assertEquals(BookDetailDownloadSummary(BookDetailDownloadState.Failed, 1),
            summarizeManagedBookDownloads(listOf(completed, completed, invalid)))
        assertEquals(BookDetailDownloadSummary(BookDetailDownloadState.Downloaded, 1),
            summarizeManagedBookDownloads(listOf(completed)))
        assertEquals(BookDetailDownloadSummary(BookDetailDownloadState.NotDownloaded, 0),
            summarizeManagedBookDownloads(emptyList()))
    }

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
