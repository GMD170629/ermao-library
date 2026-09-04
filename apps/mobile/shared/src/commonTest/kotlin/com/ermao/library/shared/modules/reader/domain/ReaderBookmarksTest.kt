package com.ermao.library.shared.modules.reader.domain

import kotlin.test.Test
import kotlin.test.assertEquals

class ReaderBookmarksTest {
    private fun report(href: String, progression: Double): ReaderPositionReport = ReaderPositionReport(
        locator = ReaderOpaqueLocator.parse("{\"href\":\"$href\"}"),
        presentation = ReaderPositionPresentation(
            displayPercent = progression * 100.0,
            totalProgression = progression,
            currentHref = href,
            chapter = ReaderChapterPresentation(href, href, null),
            page = null,
            playback = null,
        ),
    )

    private val first = ReaderBookmark(
        id = "first",
        position = report("chapter-1.xhtml", 0.25),
        label = "Chapter 1",
        createdAt = "2026-08-13T00:00:00Z",
    )
    private val second = ReaderBookmark(
        id = "second",
        position = report("chapter-2.xhtml", 0.5),
        label = "Chapter 2",
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
    fun bookmarksExposeTheSharedPresentationProjection() {
        assertEquals("chapter-1.xhtml", first.currentHref)
        assertEquals(25.0, first.displayPercent)
    }
}
