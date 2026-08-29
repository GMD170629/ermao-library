package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

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

    @Test
    fun fullPublicationLocationUsesTheMatchingFragment() {
        val location = reflowableLocation(
            href = "Text/all.xhtml",
            fragments = listOf("runtime-marker", "chapter-2"),
            position = 4,
        )

        assertEquals(
            listOf(ReaderChapterState.Read, ReaderChapterState.Current, ReaderChapterState.Unread),
            resolveReaderChapterStatesFromLocation(anchored, location, 42.0),
        )
    }

    @Test
    fun uniqueResourceMatchIsSafeWhenRuntimeFragmentDiffers() {
        val units = listOf(
            ReaderChapterUnit("Text/one.xhtml#toc-anchor", 0, 1),
            ReaderChapterUnit("Text/two.xhtml#toc-anchor", 1, 2),
        )

        assertEquals(
            listOf(ReaderChapterState.Read, ReaderChapterState.Current),
            resolveReaderChapterStatesFromLocation(
                units,
                reflowableLocation("text/two.xhtml", listOf("runtime-anchor"), 2),
                50.0,
            ),
        )
    }

    @Test
    fun readingOrderPositionResolvesSplitResourceRange() {
        val units = listOf(
            ReaderChapterUnit("text/part0003.html", 1, 3),
            ReaderChapterUnit("text/part0008_split_000.html", 4, 10),
            ReaderChapterUnit("text/part0009.html", 5, 13),
        )

        assertEquals(
            listOf(ReaderChapterState.Read, ReaderChapterState.Current, ReaderChapterState.Unread),
            resolveReaderChapterStatesFromLocation(
                units,
                reflowableLocation("text/part0008_split_001.html", listOf("visible"), 11),
                15.2,
            ),
        )
    }

    @Test
    fun duplicateAnchorAndDuplicatePositionNeverGuess() {
        val duplicateAnchors = listOf(
            ReaderChapterUnit("text/all.xhtml#same", 0, 4),
            ReaderChapterUnit("text/all.xhtml#same", 1, 4),
        )
        val duplicatePositions = listOf(
            ReaderChapterUnit("text/all.xhtml#one", 0, 4),
            ReaderChapterUnit("text/all.xhtml#two", 1, 4),
        )

        assertEquals(
            List(2) { ReaderChapterState.Unread },
            resolveReaderChapterStatesFromLocation(
                duplicateAnchors,
                reflowableLocation("text/all.xhtml", listOf("same"), 4),
                50.0,
            ),
        )
        assertEquals(
            List(2) { ReaderChapterState.Unread },
            resolveReaderChapterStatesFromLocation(
                duplicatePositions,
                reflowableLocation("text/all.xhtml", listOf("unmatched"), 4),
                50.0,
            ),
        )
    }

    @Test
    fun nonReflowableLocationsNeverSelectAChapter() {
        val units = listOf(ReaderChapterUnit("chapter.xhtml", 0, 1))
        val locations = listOf<PublicationLocation>(
            PdfPublicationLocation(pageIndex = 0, pageProgression = 0.25),
            ComicPublicationLocation(resourceHref = "page-1.jpg", pageIndex = 0),
            AudioPublicationLocation(assetId = "asset-1", positionMillis = 5_000),
        )

        locations.forEach { location ->
            assertEquals(
                listOf(ReaderChapterState.Unread),
                resolveReaderChapterStatesFromLocation(units, location, 50.0),
            )
        }
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
    fun presentationUpdateFactoryCarriesTheCompletePublicationLocation() {
        val engineLocator = reflowableEngineLocator(
            href = "Text/all.xhtml",
            fragments = listOf("chapter-2", "epubcfi(/6/4)"),
            position = 4,
        )
        val progress = ReaderProgress(
            resourceId = "reader-resource",
            location = ReflowReaderLocation(engineLocator = engineLocator),
            updatedAtEpochMillis = 123_456,
            deviceId = "device-1",
        )

        val update = createReaderProgressPresentationUpdate(
            namespaceKey = "server:user",
            bookId = "book-1",
            resourceId = "resource-1",
            percent = 42.0,
            progress = progress,
            chapterTitle = "第二章",
        )

        val location = assertIs<ReflowablePublicationLocation>(update.location)
        assertEquals(123_456, update.capturedAtEpochMillis)
        assertEquals(engineLocator, location.engineLocator)
        assertTrue(location.canonicalJson().contains("chapter-2"))
        assertTrue(location.canonicalJson().contains("epubcfi(/6/4)"))
    }

    private fun reflowableLocation(
        href: String,
        fragments: List<String>,
        position: Int,
    ): ReflowablePublicationLocation = ReflowablePublicationLocation(
        reflowableEngineLocator(href, fragments, position),
    )

    private fun reflowableEngineLocator(
        href: String,
        fragments: List<String>,
        position: Int,
    ): EngineLocator {
        val fragmentsJson = fragments.joinToString(prefix = "[", postfix = "]") { "\"$it\"" }
        return createEngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Android,
            "readium-kotlin:test",
            """{"href":"$href","type":"application/xhtml+xml","locations":{"cssSelector":"body","fragments":$fragmentsJson,"position":$position}}""",
        )
    }

}
