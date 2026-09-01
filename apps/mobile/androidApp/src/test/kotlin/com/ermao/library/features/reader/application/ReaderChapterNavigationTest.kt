package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ReaderChapterNavigationTest {
    private val chapters = listOf(
        chapter("one.xhtml", 0.0, children = listOf(chapter("two.xhtml", 0.3))),
        chapter("three.xhtml", 0.7),
    )

    @Test
    fun resolvesAdjacentChaptersInDisplayedDepthFirstOrder() {
        val adjacent = resolveAdjacentChapters(chapters, location("two.xhtml", 0.5))

        assertEquals("one.xhtml", adjacent.previous?.id)
        assertEquals("three.xhtml", adjacent.next?.id)
    }

    @Test
    fun exposesFirstAndLastChapterBoundariesWithoutLooping() {
        val first = resolveAdjacentChapters(chapters, location("one.xhtml", 0.1))
        val last = resolveAdjacentChapters(chapters, location("three.xhtml", 0.9))

        assertNull(first.previous)
        assertEquals("two.xhtml", first.next?.id)
        assertEquals("two.xhtml", last.previous?.id)
        assertNull(last.next)
    }

    @Test
    fun fallsBackToChapterStartProgressionWhenTheCurrentHrefIsUnavailable() {
        val adjacent = resolveAdjacentChapters(
            chapters,
            ReflowReaderLocation(progression = 0.4, totalProgression = 0.5),
        )

        assertEquals("one.xhtml", adjacent.previous?.id)
        assertEquals("three.xhtml", adjacent.next?.id)
    }

    private fun chapter(
        href: String,
        totalProgression: Double,
        children: List<ReaderTocEntry> = emptyList(),
    ) = ReaderTocEntry(
        title = href,
        location = location(href, totalProgression),
        children = children,
        id = href,
    )

    private fun location(href: String, totalProgression: Double) = ReflowReaderLocation(
        resourceKey = href,
        progression = 0.0,
        totalProgression = totalProgression,
    )
}
