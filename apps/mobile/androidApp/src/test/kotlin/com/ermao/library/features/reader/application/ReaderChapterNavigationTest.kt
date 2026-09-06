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
        val adjacent = resolveAdjacentChapters(chapters, "two.xhtml")

        assertEquals("one.xhtml", adjacent.previous?.id)
        assertEquals("three.xhtml", adjacent.next?.id)
    }

    @Test
    fun exposesFirstAndLastChapterBoundariesWithoutLooping() {
        val first = resolveAdjacentChapters(chapters, "one.xhtml")
        val last = resolveAdjacentChapters(chapters, "three.xhtml")

        assertNull(first.previous)
        assertEquals("two.xhtml", first.next?.id)
        assertEquals("two.xhtml", last.previous?.id)
        assertNull(last.next)
    }

    @Test
    fun unknownChapterDoesNotGuessFromProgression() {
        val adjacent = resolveAdjacentChapters(
            chapters,
            null,
        )

        assertNull(adjacent.previous)
        assertNull(adjacent.next)
    }

    @Test
    fun skipsGroupsButPreservesTheirChildren() {
        val group = chapter("group", 0.0, listOf(chapter("one.xhtml", 0.0)))
            .copy(target = com.ermao.library.shared.modules.reader.ReaderNavigationTargetInvalid())
        val adjacent = resolveAdjacentChapters(listOf(group, chapter("two.xhtml", 0.5)), "one.xhtml")
        assertNull(adjacent.previous)
        assertEquals("two.xhtml", adjacent.next?.id)
        assertNull(resolveAdjacentChapters(listOf(group), "group").next)
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
