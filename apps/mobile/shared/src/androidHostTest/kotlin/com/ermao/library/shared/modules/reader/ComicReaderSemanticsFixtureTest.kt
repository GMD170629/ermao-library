package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.ComicPairingPolicy
import com.ermao.library.shared.modules.reader.domain.ComicPresentationInput
import com.ermao.library.shared.modules.reader.domain.ComicViewport
import com.ermao.library.shared.modules.reader.domain.ReaderComicDirection
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageFit
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.domain.ReaderComicPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.domain.ReaderPageTurnAnimation
import com.ermao.library.shared.modules.reader.domain.ReaderReadingMode
import com.ermao.library.shared.modules.reader.domain.comicPageForProgress
import com.ermao.library.shared.modules.reader.domain.comicPresentationPlan
import com.ermao.library.shared.modules.reader.domain.comicVisualPages
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.Test
import kotlin.test.assertEquals

@Serializable
private data class ComicSemanticsFixture(
    val schemaVersion: Int,
    val name: String,
    val description: String,
    val cases: List<ComicSemanticsCase>,
    val progressCases: List<ComicProgressCase>,
)

@Serializable
private data class ComicSemanticsCase(
    val id: String,
    val pageCount: Int,
    val currentPageIndex: Int,
    val reducedMotion: Boolean = false,
    val preferences: ComicPreferencesFixture,
    val viewport: ComicViewportFixture,
    val expected: ComicExpected,
)

@Serializable
private data class ComicPreferencesFixture(
    val flow: String,
    val spreadMode: String,
    val coverSingle: Boolean,
    val direction: String,
    val imageFit: String,
    val imageVariant: String,
    val zoom: Double,
    val pageWidth: Int,
    val pageGap: Int,
    val pageTurnAnimation: String,
)

@Serializable
private data class ComicViewportFixture(
    val width: Int,
    val height: Int,
    val wide: Boolean,
)

@Serializable
private data class ComicExpected(
    val spreadMode: String,
    val pairingPolicy: String,
    val currentPageIndex: Int,
    val anchorPageIndex: Int,
    val logicalPageIndices: List<Int>,
    val visualPageIndices: List<Int>,
    val previousAnchor: Int?,
    val nextAnchor: Int?,
    val progress: Double,
    val effectiveImageFit: String,
    val effectivePageWidth: Int,
    val pageGap: Int,
    val animatePageTurn: Boolean,
    val cachePageIndices: List<Int>,
    val preloadPageIndices: List<Int>,
)

@Serializable
private data class ComicProgressCase(
    val pageCount: Int,
    val progression: Double,
    val pageIndex: Int,
)

class ComicReaderSemanticsFixtureTest {
    @Test
    fun sharedRulesMatchVersionedCrossPlatformFixture() {
        val fixture = Json.decodeFromString<ComicSemanticsFixture>(fixtureText())
        assertEquals(1, fixture.schemaVersion)
        assertEquals("comic-reader-semantics-v1", fixture.name)

        fixture.cases.forEach { testCase ->
            val plan = comicPresentationPlan(
                ComicPresentationInput(
                    pageCount = testCase.pageCount,
                    currentPageIndex = testCase.currentPageIndex,
                    preferences = testCase.preferences.toDomain(),
                    viewport = testCase.viewport.toDomain(),
                    reducedMotion = testCase.reducedMotion,
                ),
            )
            val expected = testCase.expected
            assertEquals(expected.spreadMode, plan.spreadMode.wireValue, testCase.id)
            assertEquals(expected.pairingPolicy, plan.pairingPolicy.wireValue(), testCase.id)
            assertEquals(expected.currentPageIndex, plan.currentPageIndex, testCase.id)
            assertEquals(expected.anchorPageIndex, plan.anchorPageIndex, testCase.id)
            assertEquals(expected.logicalPageIndices, plan.logicalPageIndices, testCase.id)
            assertEquals(
                expected.visualPageIndices,
                comicVisualPages(
                    (0 until testCase.pageCount).toList(),
                    plan.anchorPageIndex,
                    plan.spreadMode,
                    plan.direction,
                    plan.pairingPolicy,
                ),
                testCase.id,
            )
            assertEquals(expected.previousAnchor, plan.previousAnchor, testCase.id)
            assertEquals(expected.nextAnchor, plan.nextAnchor, testCase.id)
            assertEquals(expected.progress, plan.progress, 0.000000001, testCase.id)
            assertEquals(expected.effectiveImageFit, plan.imageFit.wireValue, testCase.id)
            assertEquals(expected.effectivePageWidth, plan.effectivePageWidth, testCase.id)
            assertEquals(expected.pageGap, plan.pageGap, testCase.id)
            assertEquals(expected.animatePageTurn, plan.animatePageTurn, testCase.id)
            assertEquals(expected.cachePageIndices, plan.cachePageIndices, testCase.id)
            assertEquals(expected.preloadPageIndices, plan.preloadPageIndices, testCase.id)
        }

        fixture.progressCases.forEach { progressCase ->
            assertEquals(
                progressCase.pageIndex,
                comicPageForProgress(progressCase.progression, (0 until progressCase.pageCount).toList()),
                "progress-${progressCase.pageCount}-${progressCase.progression}",
            )
        }
    }

    private fun fixtureText(): String {
        val path = Path.of(
            requireNotNull(System.getProperty("readerComicSemanticsFixturePath")) {
                "readerComicSemanticsFixturePath was not configured"
            },
        )
        require(Files.isRegularFile(path)) { "Comic semantics fixture does not exist: $path" }
        return Files.readString(path)
    }
}

private fun ComicPreferencesFixture.toDomain(): ReaderComicPreferences = ReaderComicPreferences(
    direction = ReaderComicDirection.entries.first { it.wireValue == direction },
    spreadMode = ReaderComicSpreadMode.entries.first { it.wireValue == spreadMode },
    pageTurnAnimation = ReaderPageTurnAnimation.entries.first { it.wireValue == pageTurnAnimation },
    imageFit = ReaderComicImageFit.entries.first { it.wireValue == imageFit },
    imageVariant = ReaderComicImageVariant.entries.first { it.wireValue == imageVariant },
    zoom = zoom,
    pageWidth = pageWidth,
    flow = ReaderReadingMode.entries.first { it.wireValue == flow },
    coverSingle = coverSingle,
    pageGap = pageGap,
)

private fun ComicViewportFixture.toDomain(): ComicViewport = ComicViewport(width, height, wide)

private fun ComicPairingPolicy.wireValue(): String = when (this) {
    ComicPairingPolicy.PairedFromFirst -> "paired-from-first"
    ComicPairingPolicy.CoverSingle -> "cover-single"
}
