package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ReaderChapterStateTest {
    private val anchored = listOf(
        ReaderChapterUnit("Text/all.xhtml#chapter-1", 1, navigationKey = "chapter-0"),
        ReaderChapterUnit("Text/all.xhtml#chapter-2", 2, navigationKey = "chapter-1"),
        ReaderChapterUnit("Text/all.xhtml#chapter-3", 3, navigationKey = "chapter-2"),
    )

    @Test
    fun serverSortOrderMarksPreviousCurrentAndUnread() {
        assertEquals(
            listOf(ReaderChapterState.Read, ReaderChapterState.Current, ReaderChapterState.Unread),
            resolveReaderChapterStates(
                anchored,
                2,
                42.0,
            ),
        )
    }

    @Test
    fun missingSortOrderDoesNotGuessFromHrefOrPercent() {
        assertEquals(
            List(3) { ReaderChapterState.Unread },
            resolveReaderChapterStates(
                anchored,
                null,
                60.0,
            ),
        )
    }

    @Test
    fun completedBookMarksNavigableChaptersReadAndGroupsUnread() {
        val units = listOf(
            ReaderChapterUnit("chapter-1.xhtml", 1, navigationKey = "chapter-0"),
            ReaderChapterUnit(null, 2, navigationKey = "group-1"),
            ReaderChapterUnit("chapter-2.xhtml", 3, navigationKey = "chapter-2"),
        )
        assertEquals(
            listOf(ReaderChapterState.Read, ReaderChapterState.Unread, ReaderChapterState.Read),
            resolveReaderChapterStates(
                units,
                null,
                100.0,
            ),
        )
    }

    @Test
    fun presentationNavigationKeySelectsUnitByCoreIdentity() {
        val units = listOf(
            ReaderChapterUnit("chapter-a.xhtml", 50, navigationKey = "chapter-0"),
            ReaderChapterUnit("chapter-b.xhtml", 10, navigationKey = "chapter-1"),
            ReaderChapterUnit("chapter-c.xhtml", 20, navigationKey = "chapter-2"),
        )
        val presentation = ReaderPositionPresentation(
            displayPercent = 42.0,
            totalProgression = 0.42,
            currentHref = "chapter-c.xhtml",
            chapter = ReaderChapterPresentation("chapter-c.xhtml", "C", 1, "chapter-2"),
            page = null,
            playback = null,
        )

        assertEquals(
            listOf(ReaderChapterState.Unread, ReaderChapterState.Read, ReaderChapterState.Current),
            resolveReaderChapterStatesFromPresentation(units, presentation),
        )
    }

    @Test
    fun presentationHrefAndIndexCannotInferCurrentChapter() {
        val presentation = ReaderPositionPresentation(
            displayPercent = 42.0,
            totalProgression = 0.42,
            currentHref = "Text/all.xhtml#chapter-2",
            chapter = ReaderChapterPresentation("Text/all.xhtml#chapter-2", "第二章", 1),
            page = null,
            playback = null,
        )

        assertEquals(
            List(3) { ReaderChapterState.Unread },
            resolveReaderChapterStatesFromPresentation(anchored, presentation),
        )
    }

    @Test
    fun canonicalNavigationProjectsChapterProgressionOntoTheWholePublication() {
        val hrefs = MutableList(811) { index -> "Text/chapter-$index.xhtml" }
        hrefs[66] = "OEBPS/Text/Vol02-Chapter017.xhtml"

        assertEquals(
            0.08173338,
            checkNotNull(
                resolveReflowableTotalProgressionFromNavigation(
                    orderedResourceHrefs = hrefs,
                    resourceHref = "./OEBPS/Text/Vol02-Chapter017.xhtml#visible",
                    resourceProgression = 0.2857709863068069,
                    totalProgression = null,
                ),
            ),
            absoluteTolerance = 0.00000001,
        )
    }

    @Test
    fun totalProgressionWinsOverCanonicalNavigationProjection() {
        assertEquals(
            0.42,
            resolveReflowableTotalProgressionFromNavigation(
                orderedResourceHrefs = listOf("chapter.xhtml"),
                resourceHref = "chapter.xhtml",
                resourceProgression = 0.9,
                totalProgression = 0.42,
            ),
        )
    }

    @Test
    fun chapterProgressionAloneIsNeverReportedAsWholePublicationProgress() {
        assertNull(
            resolveReflowableTotalProgressionFromNavigation(
                orderedResourceHrefs = listOf("known.xhtml"),
                resourceHref = "missing.xhtml",
                resourceProgression = 0.2857709863068069,
                totalProgression = null,
            ),
        )
        assertNull(
            resolveReflowableTotalProgressionFromNavigation(
                orderedResourceHrefs = emptyList(),
                resourceHref = "known.xhtml",
                resourceProgression = 0.2857709863068069,
                totalProgression = null,
            ),
        )
    }

    @Test
    fun presentationUpdateCarriesOpaqueLocatorAndIndependentPresentation() {
        val locatorJson = """{"href":"Text/all.xhtml","type":"application/xhtml+xml","locations":{"position":4}}"""
        val position = ReaderPositionReport(
            locator = ReaderOpaqueLocator.parse(locatorJson),
            presentation = ReaderPositionPresentation(
                displayPercent = 42.0,
                totalProgression = 0.42,
                currentHref = "Text/all.xhtml",
                chapter = ReaderChapterPresentation("Text/all.xhtml#chapter-2", "第二章", 1),
                page = null,
                playback = null,
            ),
        )

        val update = createReaderProgressPresentationUpdate(
            namespaceKey = "server:user",
            bookId = "book-1",
            resourceId = "resource-1",
            position = position,
            capturedAtEpochMillis = 123_456,
        )

        assertEquals(123_456, update.capturedAtEpochMillis)
        assertEquals(position, update.position)
        assertEquals(42.0, update.presentation.displayPercent)
        assertTrue(update.position.locator.canonicalJson.contains("Text/all.xhtml"))
    }
}
