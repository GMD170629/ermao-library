package com.ermao.library.shared.modules.reader.domain

import kotlin.test.Test
import kotlin.test.assertEquals

class ReaderBookmarksTest {
    private val first = ReaderBookmark(
        id = "first",
        location = ReaderBookmarkLocation("chapter-1.xhtml", 0.25),
        label = "Chapter 1",
        percent = 10.0,
        createdAt = "2026-08-13T00:00:00Z",
    )
    private val second = ReaderBookmark(
        id = "second",
        location = ReaderBookmarkLocation("chapter-2.xhtml", 0.5),
        label = "Chapter 2",
        percent = 30.0,
        createdAt = "2026-08-13T01:00:00Z",
    )

    @Test
    fun remoteCollectionMergesOnlyWithoutPendingLocalChanges() {
        assertEquals(listOf(first, second), mergeReaderBookmarks(listOf(first), listOf(second), false))
        assertEquals(listOf(first), mergeReaderBookmarks(listOf(first), listOf(second), true))
    }

    @Test
    fun newerMutationReplacesWholePendingSnapshot() {
        assertEquals(
            listOf(second),
            replacePendingReaderBookmarkSnapshot(listOf(first), listOf(second)),
        )
    }

    @Test
    fun allServerBookmarkLocationMorphologiesRetainTheirWireFields() {
        val locations = listOf(
            ReaderBookmarkLocation.reflow("chapter-1.xhtml", 0.25),
            ReaderBookmarkLocation.comic(3),
            ReaderBookmarkLocation.pdf(4),
            ReaderBookmarkLocation.audio("asset-1", "chapter-2", 42_000),
        )

        assertEquals(listOf("reflow", "comic", "pdf", "audio"), locations.map { it.kind })
        assertEquals(3, locations[1].pageIndex)
        assertEquals(4, locations[2].pageNumber)
        assertEquals(42_000, locations[3].positionMs)
    }
}
