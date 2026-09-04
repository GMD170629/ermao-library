package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.ComicNavigationCommand
import com.ermao.library.shared.modules.reader.domain.ComicNavigationOutcome
import com.ermao.library.shared.modules.reader.domain.ComicPresentationInput
import com.ermao.library.shared.modules.reader.domain.ComicReaderRuntime
import com.ermao.library.shared.modules.reader.domain.ComicViewport
import com.ermao.library.shared.modules.reader.domain.ReaderComicCapabilities
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageFit
import com.ermao.library.shared.modules.reader.domain.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.domain.ReaderComicPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.domain.ReaderControl
import com.ermao.library.shared.modules.reader.domain.ReaderPageTurnAnimation
import com.ermao.library.shared.modules.reader.domain.ReaderReadingMode
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderCapabilities
import com.ermao.library.shared.modules.reader.domain.changedReaderControls
import com.ermao.library.shared.modules.reader.domain.supportedControls
import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ComicReaderSemanticsTest {
    private val wideViewport = ComicViewport(width = 1_440, height = 2_000, wide = true)

    @Test
    fun navigationReturnsToZeroAndRepeatingFirstIsNoOp() {
        val runtime = ComicReaderRuntime(
            ComicPresentationInput(
                pageCount = 5,
                currentPageIndex = 3,
                viewport = wideViewport,
                preferences = ReaderComicPreferences(spreadMode = ReaderComicSpreadMode.Double),
            ),
        )

        assertEquals(0, runtime.dispatch(ComicNavigationCommand.First).plan.currentPageIndex)
        assertEquals(ComicNavigationOutcome.NoOp, runtime.dispatch(ComicNavigationCommand.First).outcome)
        assertEquals(ComicNavigationOutcome.NoOp, runtime.dispatch(ComicNavigationCommand.GoToProgress(0.0)).outcome)
    }

    @Test
    fun runtimeKeepsFocalPageWhenSpreadAnchorDiffers() {
        val runtime = ComicReaderRuntime(
            ComicPresentationInput(
                pageCount = 5,
                currentPageIndex = 3,
                viewport = wideViewport,
                resourceHrefs = (0..4).map { "pages/$it" },
                preferences = ReaderComicPreferences(spreadMode = ReaderComicSpreadMode.Double),
            ),
        )
        assertEquals(3, runtime.plan.currentPageIndex)
        assertEquals(2, runtime.plan.anchorPageIndex)

        val restored = runtime.dispatch(
            ComicNavigationCommand.RestoreLocation(ComicReaderLocation("pages/3", 3)),
        )
        assertEquals(ComicNavigationOutcome.NoOp, restored.outcome)
        assertEquals(3, restored.plan.currentPageIndex)

        val changed = runtime.update(preferences = ReaderComicPreferences())
        assertEquals(3, changed.currentPageIndex)
        assertEquals(3, changed.anchorPageIndex)
    }

    @Test
    fun restoreRequiresMatchingCanonicalResourceHrefAndRetryIsDistinct() {
        val runtime = ComicReaderRuntime(
            ComicPresentationInput(
                pageCount = 2,
                viewport = wideViewport,
                resourceHrefs = listOf("pages/0", "pages/1"),
            ),
        )
        val invalid = runtime.dispatch(
            ComicNavigationCommand.RestoreLocation(ComicReaderLocation("pages/0", 1)),
        )
        assertEquals(ComicNavigationOutcome.InvalidLocation, invalid.outcome)
        assertEquals(0, runtime.plan.currentPageIndex)

        assertEquals(
            ComicNavigationOutcome.RetryRequested,
            runtime.dispatch(ComicNavigationCommand.Retry).outcome,
        )
    }

    @Test
    fun comicCapabilitiesExposeOnlyImplementedControlsAndChangesIncludeEveryComicField() {
        val capabilities = ReaderCapabilities.epub(supportsVolumeKeys = false).copy(
            comic = ReaderComicCapabilities(
                supportsFlow = true,
                supportsSpread = true,
                supportsDirection = true,
                supportsCoverSingle = true,
                supportsPageGap = true,
                supportsZoom = true,
                supportsFit = true,
                supportsQuality = true,
                supportsAnimation = true,
                supportsPageWidth = true,
            ),
        )
        assertTrue(ReaderControl.ComicZoom in capabilities.supportedControls)
        assertTrue(ReaderControl.ComicFit in capabilities.supportedControls)
        assertTrue(ReaderControl.ComicQuality in capabilities.supportedControls)

        val before = ReaderPreferences()
        val after = before.copy(comic = before.comic.copy(
            zoom = 1.2,
            imageFit = ReaderComicImageFit.Height,
            imageVariant = ReaderComicImageVariant.DataSaver,
            pageWidth = 1_200,
        ))
        assertEquals(
            setOf(ReaderControl.ComicZoom, ReaderControl.ComicFit, ReaderControl.ComicQuality, ReaderControl.PageWidth),
            changedReaderControls(before, after),
        )
    }

    @Test
    fun pageGapRequiresBothPaginatedFlowAndDoubleSpread() {
        val capabilities = readerPlatformCapabilities(
            ReaderMorphology.Comic,
            volumeKeys = false,
            pdfZoom = false,
            pdfFit = false,
            comic = ReaderComicCapabilities(supportsFit = true, supportsPageGap = true),
        )
        val setting = ReaderSettingsCatalog.settings.first { it.id == "comicPageGap" }
        val fitSetting = ReaderSettingsCatalog.settings.first { it.id == "comicFit" }
        val single = ReaderPreferences(comic = ReaderComicPreferences(
            spreadMode = ReaderComicSpreadMode.Single,
            pageGap = 8,
        ))
        assertEquals(
            ReaderControlAvailability.TemporarilyUnavailable,
            ReaderSettingsCatalog.resolveReaderSetting(
                setting,
                ReaderMorphology.Comic,
                capabilities,
                single,
                ready = true,
            ).availability,
        )
        val scrolling = single.copy(comic = single.comic.copy(
            flow = ReaderReadingMode.ContinuousScroll,
            spreadMode = ReaderComicSpreadMode.Double,
        ))
        assertEquals(
            "scrollingMode",
            ReaderSettingsCatalog.resolveReaderSetting(
                setting,
                ReaderMorphology.Comic,
                capabilities,
                scrolling,
                ready = true,
            ).reasonId,
        )
        assertEquals(
            "scrollingMode",
            ReaderSettingsCatalog.resolveReaderSetting(
                fitSetting,
                ReaderMorphology.Comic,
                capabilities,
                scrolling,
                ready = true,
            ).reasonId,
        )
        val pagedDouble = single.copy(comic = single.comic.copy(spreadMode = ReaderComicSpreadMode.Double))
        assertEquals(
            ReaderControlAvailability.Available,
            ReaderSettingsCatalog.resolveReaderSetting(
                setting,
                ReaderMorphology.Comic,
                capabilities,
                pagedDouble,
                ready = true,
            ).availability,
        )
    }

}
