package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals

class ReaderChapterStateTest {
    private val anchored = listOf(
        ReaderChapterUnit("Text/all.xhtml#chapter-1", 1),
        ReaderChapterUnit("Text/all.xhtml#chapter-2", 2),
        ReaderChapterUnit("Text/all.xhtml#chapter-3", 3),
    )

    @Test
    fun exactFragmentMarksPreviousCurrentAndUnread() {
        assertEquals(
            listOf(ReaderChapterState.Read, ReaderChapterState.Current, ReaderChapterState.Unread),
            resolveReaderChapterStates(
                anchored,
                "text/all.xhtml#chapter-2",
                2,
                42.0,
                ReaderChapterListMetadata(pageSize = 3),
            ),
        )
    }

    @Test
    fun ambiguousResourceDoesNotGuessFromPercent() {
        assertEquals(
            List(3) { ReaderChapterState.Unread },
            resolveReaderChapterStates(
                anchored,
                "Text/all.xhtml",
                null,
                60.0,
                ReaderChapterListMetadata(pageSize = 3),
            ),
        )
    }

    @Test
    fun exactGlobalIndexWorksAcrossPages() {
        val later = (10..14).map { ReaderChapterUnit("chapter-$it.xhtml", it) }
        assertEquals(
            List(5) { ReaderChapterState.Unread },
            resolveReaderChapterStates(
                later,
                null,
                null,
                20.0,
                ReaderChapterListMetadata(page = 3, pageSize = 5, currentIndex = 9),
            ),
        )
    }

    @Test
    fun completedBookMarksEveryChapterRead() {
        assertEquals(
            List(3) { ReaderChapterState.Read },
            resolveReaderChapterStates(
                anchored,
                "Text/all.xhtml#chapter-3",
                3,
                100.0,
                ReaderChapterListMetadata(pageSize = 3),
            ),
        )
    }
}
