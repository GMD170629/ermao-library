package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ReaderNavigationSelectionTest {
    private val entries = listOf(
        ReaderNavigationEntry("volume", "text/chapter.xhtml", 0),
        ReaderNavigationEntry("parent", "text/chapter.xhtml#one", 1),
        ReaderNavigationEntry("child", "text/chapter.xhtml#one", 2),
        ReaderNavigationEntry("other", "text/chapter.xhtml#two", 1),
    )

    @Test
    fun duplicateAnchorsRemainAmbiguousRegardlessOfDepth() {
        assertNull(resolveCurrentReaderNavigationEntryId(entries, "./text/chapter.xhtml#one", emptySet(), null))
        assertEquals("other", resolveCurrentReaderNavigationEntryId(entries, "text/chapter.xhtml", setOf("two"), null))
        assertEquals("other", resolveCurrentReaderNavigationEntryId(entries, "text/chapter.xhtml", emptySet(), "#two > p"))
    }

    @Test
    fun conflictingFragmentEvidenceDoesNotSelectAChapter() {
        assertNull(resolveCurrentReaderNavigationEntryId(entries, "text/chapter.xhtml#two", setOf("one"), null))
    }

    @Test
    fun unmatchedOrUnavailableLocationDoesNotGuessFromFileNameOrOrder() {
        assertNull(resolveCurrentReaderNavigationEntryId(entries, null, emptySet(), null))
        assertNull(resolveCurrentReaderNavigationEntryId(entries, "elsewhere/chapter.xhtml#one", emptySet(), null))
        assertNull(resolveCurrentReaderNavigationEntryId(entries.drop(1), "text/chapter.xhtml", emptySet(), null))
        assertNull(resolveCurrentReaderNavigationEntryId(emptyList(), "text/chapter.xhtml", emptySet(), null))
    }

    @Test
    fun unanchoredTargetStillMatchesAndDuplicatePeersRemainAmbiguous() {
        assertNull(resolveCurrentReaderNavigationEntryId(entries, "text/chapter.xhtml", emptySet(), null))
        assertEquals("volume", resolveCurrentReaderNavigationEntryId(entries.take(1), "text/chapter.xhtml", emptySet(), null))
        val peers = listOf(ReaderNavigationEntry("a", "chapter.xhtml", 0), ReaderNavigationEntry("b", "chapter.xhtml", 0))
        assertNull(resolveCurrentReaderNavigationEntryId(peers, "chapter.xhtml", emptySet(), null))
        val anchoredPeers = peers.map { it.copy(href = "chapter.xhtml#same") }
        assertNull(resolveCurrentReaderNavigationEntryId(anchoredPeers, "chapter.xhtml#same", emptySet(), null))
    }
}
