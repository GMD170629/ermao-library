package com.ermao.library.features.reader.presentation

import android.view.WindowManager
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.test.centerLeft
import androidx.compose.ui.test.centerRight
import androidx.compose.ui.test.swipe
import androidx.compose.runtime.mutableStateOf
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import com.ermao.library.R
import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderControl
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ReaderScreenContentsInstrumentedTest {
    @get:Rule
    val compose = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun contentsSheetOpensBeforeFirstLoadAndReusesTheLoadedLazyList() {
        val controller = DeferredContentsController()
        val done = instrumentation.targetContext.getString(R.string.reader_done)
        compose.setContent {
            ReaderScreen(
                title = "Large contents fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        compose.onNodeWithTag(READER_SHEET_TEST_TAG).assertIsDisplayed()
        compose.onNodeWithTag(READER_CONTENTS_LOADING_TEST_TAG).assertIsDisplayed()
        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG).assertDoesNotExist()
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).assertIsDisplayed()
        compose.onNodeWithTag("reader-notes").assertIsDisplayed()
        compose.onNodeWithTag("reader-appearance").assertIsDisplayed()
        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).assertIsDisplayed()
        assertEquals(1, controller.loadCalls.get())

        controller.releaseContents()
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithText("Chapter 1").fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText("Chapter 1").assertIsDisplayed()
        compose.onNodeWithText("Chapter 1000").assertDoesNotExist()

        compose.onNodeWithContentDescription(done).performClick()
        assertStableSheetAndProgress()
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        compose.onNodeWithText("Chapter 1").assertIsDisplayed()
        compose.onNodeWithTag(READER_CONTENTS_LOADING_TEST_TAG).assertDoesNotExist()
        assertEquals(1, controller.loadCalls.get())
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        assertStableSheetAndProgress()
    }

    @Test
    fun currentNavigationEntryIsCenteredAfterAsyncLoadAndOnlyRecenteredOnReopen() {
        val controller = DeferredContentsController(initialNavigationEntryId = "chapter-500.xhtml")
        compose.setContent {
            ReaderScreen(
                title = "Navigation selection fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        compose.onNodeWithTag(READER_CONTENTS_LOADING_TEST_TAG).assertIsDisplayed()
        controller.releaseContents()

        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithTag("reader-toc:chapter-500.xhtml")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        val list = compose.onNodeWithTag(READER_CONTENTS_LIST_TEST_TAG)
        val selected = compose.onNodeWithTag("reader-toc:chapter-500.xhtml")
        selected.assertIsDisplayed().assertIsSelected()
        val listBounds = list.getUnclippedBoundsInRoot()
        val selectedBounds = selected.getUnclippedBoundsInRoot()
        val listCenter = (listBounds.top.value + listBounds.bottom.value) / 2f
        val selectedCenter = (selectedBounds.top.value + selectedBounds.bottom.value) / 2f
        assertTrue(
            "TOC selection was not centered: list=$listCenter selected=$selectedCenter",
            abs(listCenter - selectedCenter) <= 96f,
        )

        // A user scroll must remain where the user left it; the one-time
        // centering effect is scoped to this sheet opening.
        list.performScrollToIndex(1)
        compose.onNodeWithTag("reader-toc:chapter-1.xhtml").assertIsDisplayed()
        compose.onAllNodesWithTag("reader-toc:chapter-500.xhtml").assertCountEquals(0)

        val done = instrumentation.targetContext.getString(R.string.reader_done)
        compose.onNodeWithContentDescription(done).performClick()
        assertStableSheetAndProgress()
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithTag("reader-toc:chapter-500.xhtml")
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        compose.onNodeWithTag("reader-toc:chapter-500.xhtml").assertIsDisplayed().assertIsSelected()
        assertStableSheetWithoutProgress()
    }

    @Test
    fun contentsSheetKeepsAllPanelTabsAvailableWhileSwitchingNativePanels() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Native panel fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        controller.releaseContents()
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithTag(READER_CONTENTS_LIST_TEST_TAG)
                .fetchSemanticsNodes()
                .isNotEmpty()
        }
        compose.onNodeWithTag(READER_CONTENTS_LIST_TEST_TAG).assertIsDisplayed()
        assertStableSheetWithoutProgress()
        assertPanelTabsDisplayed()

        compose.onNodeWithTag("reader-settings").performClick()
        compose.onNodeWithTag(READER_PREFERENCES_SCROLL_TEST_TAG).assertIsDisplayed()
        assertStableSheetWithoutProgress()
        assertPanelTabsDisplayed()

        compose.onNodeWithTag("reader-notes").performClick()
        compose.onNodeWithText(instrumentation.targetContext.getString(R.string.reader_annotations))
            .assertIsDisplayed()
        assertStableSheetWithoutProgress()
        assertPanelTabsDisplayed()
    }

    private fun assertPanelTabsDisplayed() {
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).assertIsDisplayed()
        compose.onNodeWithTag("reader-notes").assertIsDisplayed()
        compose.onNodeWithTag("reader-appearance").assertIsDisplayed()
        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).assertIsDisplayed()
    }

    private fun assertStableSheet() {
        compose.onAllNodesWithTag(READER_SHEET_TEST_TAG).assertCountEquals(1)
        compose.onNodeWithTag(READER_SHEET_TEST_TAG).assertIsDisplayed()
    }

    private fun assertStableSheetAndProgress() {
        assertStableSheet()
        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG).assertIsDisplayed()
    }

    @Test
    fun nativeSheetKeepsIdentityWhileSwitchingProgressAndPanelContent() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Persistent native sheet fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        assertStableSheetAndProgress()
        val sheetId = compose.onNodeWithTag(READER_SHEET_TEST_TAG).fetchSemanticsNode().id

        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        assertStableSheetWithoutProgress()
        assertEquals(sheetId, compose.onNodeWithTag(READER_SHEET_TEST_TAG).fetchSemanticsNode().id)

        val done = instrumentation.targetContext.getString(R.string.reader_done)
        compose.onNodeWithContentDescription(done).performClick()
        assertStableSheetAndProgress()
        assertEquals(sheetId, compose.onNodeWithTag(READER_SHEET_TEST_TAG).fetchSemanticsNode().id)
        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).performClick()
        assertStableSheetWithoutProgress()
        assertEquals(sheetId, compose.onNodeWithTag(READER_SHEET_TEST_TAG).fetchSemanticsNode().id)
    }

    private fun assertStableSheetWithoutProgress() {
        assertStableSheet()
        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG).assertDoesNotExist()
    }

    @Test
    fun nativeSheetExpandsBeforeScrollingAndCollapsesAtListStartWithoutTurningPages() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Native scroll fixture", controller = controller, opening = false,
                openError = null, controlsVisible = true, onControlsVisibleChange = {},
                onClose = {}, onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        controller.releaseContents()
        compose.waitUntil(5_000) { compose.onAllNodesWithTag(READER_CONTENTS_LIST_TEST_TAG).fetchSemanticsNodes().isNotEmpty() }
        val list = compose.onNodeWithTag(READER_CONTENTS_LIST_TEST_TAG)
        val partialTop = list.getUnclippedBoundsInRoot().top.value
        list.performTouchInput { swipe(Offset(width / 2f, height * 0.9f), Offset(width / 2f, height * 0.2f), 600) }
        compose.waitForIdle()
        val expandedTop = list.getUnclippedBoundsInRoot().top.value
        assertTrue("Sheet did not expand first", expandedTop < partialTop)
        compose.onNodeWithTag("reader-toc:chapter-1.xhtml").assertIsDisplayed()
        assertPanelTabsDisplayed()
        list.performTouchInput { swipe(Offset(width / 2f, height * 0.8f), Offset(width / 2f, height * 0.2f), 600) }
        compose.onAllNodesWithTag("reader-toc:chapter-1.xhtml").assertCountEquals(0)
        list.performScrollToIndex(0)
        list.performTouchInput { swipe(Offset(width / 2f, height * 0.15f), Offset(width / 2f, height * 0.75f), 600) }
        compose.waitForIdle()
        assertTrue("Sheet did not return to partial height", list.getUnclippedBoundsInRoot().top.value > expandedTop)
        assertPanelTabsDisplayed()
        assertEquals(0, controller.previousPageCalls.get())
        assertEquals(0, controller.nextPageCalls.get())
    }

    @Test
    fun nativeSheetFooterBoundsStayFixedAcrossIntermediateDragMoves() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Native drag bounds fixture", controller = controller, opening = false,
                openError = null, controlsVisible = true, onControlsVisibleChange = {},
                onClose = {}, onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        controller.releaseContents()
        compose.waitUntil(5_000) {
            compose.onAllNodesWithTag(READER_CONTENTS_LIST_TEST_TAG).fetchSemanticsNodes().isNotEmpty()
        }

        val footer = compose.onNodeWithTag(READER_CONTENTS_TEST_TAG)
        val initialFooter = footer.getUnclippedBoundsInRoot()
        fun assertFooterStable(step: String) {
            val actual = footer.getUnclippedBoundsInRoot()
            assertEquals("$step footer left", initialFooter.left.value, actual.left.value, 1f)
            assertEquals("$step footer top", initialFooter.top.value, actual.top.value, 1f)
            assertEquals("$step footer right", initialFooter.right.value, actual.right.value, 1f)
            assertEquals("$step footer bottom", initialFooter.bottom.value, actual.bottom.value, 1f)
        }

        val list = compose.onNodeWithTag(READER_CONTENTS_LIST_TEST_TAG)
        val listBounds = list.getUnclippedBoundsInRoot()
        val initialListTop = listBounds.top.value
        val density = instrumentation.targetContext.resources.displayMetrics.density
        val start = Offset(
            ((listBounds.left + listBounds.right) / 2f).value * density,
            listBounds.bottom.value * density - 24f * density,
        )
        val dragTargets = listOf(
            Offset(start.x, start.y - 40f * density),
            Offset(start.x, start.y - 80f * density),
            Offset(start.x, start.y - 120f * density),
        )
        compose.onRoot().performTouchInput { down(start) }
        var previousExpandTop = initialListTop
        try {
            dragTargets.forEachIndexed { index, target ->
                compose.onRoot().performTouchInput { moveTo(target, delayMillis = 32) }
                compose.waitForIdle()
                assertFooterStable("expand move ${index + 1}")
                val currentTop = list.getUnclippedBoundsInRoot().top.value
                if (index > 0) {
                    assertTrue(
                        "expand move ${index + 1} did not move the sheet upward: previous=$previousExpandTop current=$currentTop",
                        currentTop <= previousExpandTop,
                    )
                }
                previousExpandTop = currentTop
            }
        } finally {
            compose.onRoot().performTouchInput { up() }
        }
        compose.waitForIdle()
        assertFooterStable("expand end")
        assertTrue(
            "held expand did not move the sheet upward: initial=$initialListTop final=$previousExpandTop",
            previousExpandTop < initialListTop,
        )

        // Settle at the full-height anchor before sampling the downward drag.
        list.performTouchInput { swipe(Offset(width / 2f, height * 0.9f), Offset(width / 2f, height * 0.1f), 600) }
        list.performScrollToIndex(0)
        compose.waitForIdle()
        val expandedListBounds = list.getUnclippedBoundsInRoot()
        val expandedTopBeforeCollapse = expandedListBounds.top.value
        val collapseStart = Offset(
            ((expandedListBounds.left + expandedListBounds.right) / 2f).value * density,
            expandedListBounds.top.value * density + 24f * density,
        )
        val collapseTargets = listOf(
            Offset(collapseStart.x, collapseStart.y + 40f * density),
            Offset(collapseStart.x, collapseStart.y + 80f * density),
            Offset(collapseStart.x, collapseStart.y + 120f * density),
        )
        compose.onRoot().performTouchInput { down(collapseStart) }
        var previousCollapseTop = expandedTopBeforeCollapse
        try {
            collapseTargets.forEachIndexed { index, target ->
                compose.onRoot().performTouchInput { moveTo(target, delayMillis = 32) }
                compose.waitForIdle()
                assertFooterStable("collapse move ${index + 1}")
                val currentTop = list.getUnclippedBoundsInRoot().top.value
                if (index > 0) {
                    assertTrue(
                        "collapse move ${index + 1} did not move the sheet downward: previous=$previousCollapseTop current=$currentTop",
                        currentTop >= previousCollapseTop,
                    )
                }
                previousCollapseTop = currentTop
            }
        } finally {
            compose.onRoot().performTouchInput { up() }
        }
        compose.waitForIdle()
        assertFooterStable("collapse end")
        assertTrue(
            "held collapse did not move the sheet downward: initial=$expandedTopBeforeCollapse final=$previousCollapseTop",
            previousCollapseTop > expandedTopBeforeCollapse,
        )
    }

    @Test
    fun progressSliderCommitsOneSeekForACompletedUserChange() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Progress fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG)
            .assertIsEnabled()
            .performSemanticsAction(SemanticsActions.SetProgress) { setProgress -> setProgress(0.8f) }
        compose.waitUntil(timeoutMillis = 5_000) { controller.seekCalls.get() == 1 }
        assertEquals(1, controller.seekCalls.get())
        assertTrue(checkNotNull(controller.lastSeek.get()) > 0.5)
    }

    @Test
    fun reflowableProgressArrowsNavigateChaptersInsteadOfPages() {
        val controller = DeferredContentsController()
        val previousChapter = instrumentation.targetContext.getString(R.string.reader_previous_chapter)
        val nextChapter = instrumentation.targetContext.getString(R.string.reader_next_chapter)
        compose.setContent {
            ReaderScreen(
                title = "Chapter arrow fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        controller.releaseContents()
        compose.waitForIdle()
        compose.onNodeWithContentDescription(previousChapter).assertIsNotEnabled()
        compose.onNodeWithContentDescription(nextChapter).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 5_000) { controller.chapterNavigationCalls.get() == 1 }

        assertEquals(0, controller.previousPageCalls.get())
        assertEquals(0, controller.nextPageCalls.get())
        assertEquals("chapter-2.xhtml", controller.currentLocation.value?.let { (it as ReflowReaderLocation).resourceKey })
    }

    @Test
    fun progressSliderRespondsToARealDragGestureAndCommitsOnce() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Progress drag fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG).performTouchInput {
            swipe(
                start = centerLeft + Offset(30f, 0f),
                end = centerRight - Offset(30f, 0f),
                durationMillis = 500,
            )
        }

        val preview = compose.onNodeWithTag(READER_PROGRESS_TEST_TAG)
            .fetchSemanticsNode()
            .config[SemanticsProperties.ProgressBarRangeInfo]
        assertTrue("Slider preview remained at ${preview.current}", preview.current > 0.5f)
        compose.waitUntil(timeoutMillis = 5_000) { controller.seekCalls.get() == 1 }
        assertEquals(1, controller.seekCalls.get())
        assertTrue(checkNotNull(controller.lastSeek.get()) > 0.5)
    }

    @Test
    fun rejectedProgressSeekRestoresTheOriginalValueAndShowsAnError() {
        val controller = DeferredContentsController().apply { seekAccepted = false }
        val errorMessage = instrumentation.targetContext.getString(R.string.reader_progress_seek_failed)
        compose.setContent {
            ReaderScreen(
                title = "Rejected progress fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG)
            .performSemanticsAction(SemanticsActions.SetProgress) { setProgress -> setProgress(0.8f) }
        compose.onNodeWithText(errorMessage).assertIsDisplayed()
        val range = compose.onNodeWithTag(READER_PROGRESS_TEST_TAG)
            .fetchSemanticsNode()
            .config[SemanticsProperties.ProgressBarRangeInfo]
        assertEquals(0f, range.current, 0.0001f)
        assertEquals(1, controller.seekCalls.get())
    }

    @Test
    fun progressStatusLivesBelowTheReadingBodyAndNotInsideVisibleControls() {
        val controller = DeferredContentsController()
        val controlsVisible = mutableStateOf(false)
        val progress = instrumentation.targetContext.getString(R.string.reader_progress_percent, 0)
        compose.setContent {
            ReaderScreen(
                title = "Passive progress fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = controlsVisible.value,
                onControlsVisibleChange = { controlsVisible.value = it },
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_PASSIVE_STATUS_TEST_TAG).assertIsDisplayed()
        compose.onNodeWithText(progress).assertIsDisplayed()

        compose.runOnIdle { controlsVisible.value = true }
        compose.onNodeWithTag(READER_PASSIVE_STATUS_TEST_TAG).assertDoesNotExist()
        compose.onNodeWithText(progress).assertDoesNotExist()
        compose.onNodeWithTag(READER_PROGRESS_TEST_TAG).assertIsDisplayed()
    }

    @Test
    fun androidReaderSettingsFollowSharedReflowableSpreadCatalog() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Single-page settings fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).performClick()
        compose.onNodeWithTag("reader-setting-section-card-interface").assertIsDisplayed()
        val heading = compose.onNodeWithTag("reader-setting-section-heading-interface")
            .fetchSemanticsNode()
        assertTrue(heading.config.contains(SemanticsProperties.Heading))
        compose.onNodeWithTag("reader-setting-textSpread").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun fixedReaderControlsHideTechnicalDisabledReason() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Fixed control fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).performClick()
        val notImplemented = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog
            .availabilityReasons.getValue("notImplemented")
            .let { localized(it.chinese, it.english) }
        compose.onNodeWithTag("reader-setting-control-swipePageTurn")
            .performScrollTo()
            .assertIsDisplayed()
            .assertIsNotEnabled()

        assertTrue(compose.onAllNodesWithText(notImplemented).fetchSemanticsNodes().isEmpty())
    }

    @Test
    fun unsupportedAndTemporaryReaderControlsUseCanonicalReasons() {
        val controller = DeferredContentsController(unavailable = setOf(ReaderControl.TapZones))
        val notImplemented = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog
            .availabilityReasons.getValue("notImplemented")
            .let { localized(it.chinese, it.english) }
        val publicationConstraint = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog
            .availabilityReasons.getValue("publicationConstraint")
        val constraintCopy = if (
            instrumentation.targetContext.resources.configuration.locales[0].language == "zh"
        ) {
            publicationConstraint.chinese
        } else {
            publicationConstraint.english
        }
        compose.setContent {
            ReaderScreen(
                title = "Unavailable control fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).performClick()
        compose.onNodeWithTag("reader-setting-control-optimization")
            .performScrollTo()
            .assertIsDisplayed()
            .assertIsNotEnabled()
        assertTrue(compose.onAllNodesWithText(notImplemented).fetchSemanticsNodes().isEmpty())
        compose.onNodeWithTag("reader-setting-control-tapZones")
            .performScrollTo()
            .assertIsDisplayed()
        assertTrue(compose.onAllNodesWithText(constraintCopy).fetchSemanticsNodes().isEmpty())
    }

    @Test
    fun advancedReaderSettingsExposeExpandedStateAndGroupedSections() {
        val controller = DeferredContentsController()
        compose.setContent {
            ReaderScreen(
                title = "Advanced settings fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).performClick()
        val advanced = compose.onNodeWithTag("reader-advanced-settings")
            .performScrollTo()
            .assertIsDisplayed()
        val collapsed = instrumentation.targetContext.getString(R.string.reader_advanced_collapsed)
        val expanded = instrumentation.targetContext.getString(R.string.reader_advanced_expanded)
        assertTrue(advanced.fetchSemanticsNode().config.contains(SemanticsProperties.Heading))
        assertEquals(collapsed, advanced.fetchSemanticsNode().config[SemanticsProperties.StateDescription])
        advanced.performClick()
        assertEquals(expanded, advanced.fetchSemanticsNode().config[SemanticsProperties.StateDescription])
        compose.onNodeWithTag("reader-setting-section-card-textLayoutAdvanced")
            .performScrollTo()
            .assertIsDisplayed()
    }

    @Test
    fun readerSettingsPreserveSwitchSegmentedChoiceSheetAndResetInteractions() {
        val initial = ReaderPreferences().copy(
            display = ReaderPreferences().display.copy(showClock = false),
        )
        val controller = DeferredContentsController(initialPreferences = initial)
        val reversedTapZones = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.settings
            .first { it.id == "tapZones" }
            .options.first { it.value == "reversed" }
            .let { option -> localized(option.chinese, option.english) }
        val reset = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.settings
            .first { it.id == "reset" }
            .let { setting -> localized(setting.chinese, setting.english) }
        compose.setContent {
            ReaderScreen(
                title = "Settings interaction fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag(READER_SETTINGS_TEST_TAG).performClick()
        compose.onNodeWithTag("reader-setting-control-showClock").performClick()
        compose.waitUntil { controller.preferences.value.display.showClock }

        compose.onNodeWithTag("reader-setting-control-tapZones").performScrollTo()
        compose.onNodeWithText(reversedTapZones).performClick()
        compose.waitUntil {
            controller.preferences.value.interaction.tapZones.wireValue == "reversed"
        }

        val percent = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.settings
            .first { it.id == "progressStyle" }
            .options.first { it.value == "percent" }
            .let { option -> localized(option.chinese, option.english) }
        compose.onNodeWithTag("reader-setting-control-progressStyle").performScrollTo()
        compose.onNodeWithText(percent).performClick()
        compose.waitUntil {
            controller.preferences.value.display.progressStyle.wireValue == "percent"
        }

        compose.onNodeWithText(reset).performScrollTo().performClick()
        compose.waitUntil { controller.preferences.value == ReaderPreferences() }
    }

    @Test
    fun readerPageWidthUsesCanonicalNarrowViewportState() {
        val controller = DeferredContentsController()
        val pageWidth = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.settings
            .first { it.id == "textPageWidth" }
            .let { setting -> localized(setting.chinese, setting.english) }
        compose.setContent {
            ReaderScreen(
                title = "Number setting fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag("reader-appearance").performClick()
        compose.onNodeWithTag("reader-setting-textPageWidth").performScrollTo()
        compose.onNodeWithContentDescription(pageWidth).assertIsNotEnabled()
        val narrowViewport = com.ermao.library.shared.modules.reader.ReaderSettingsCatalog
            .availabilityReasons.getValue("narrowViewport")
            .let { localized(it.chinese, it.english) }
        compose.onNodeWithText(narrowViewport).assertDoesNotExist()
        assertEquals(ReaderPreferences().epub.pageWidth, controller.preferences.value.epub.pageWidth)
    }

    @Test
    fun notesTabsSwitchWhenAnnotationsAreSupported() {
        val controller = DeferredContentsController(supportsAnnotations = true)
        compose.setContent {
            ReaderScreen(
                title = "Notes fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = true,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()

        compose.onNodeWithTag("reader-notes").performClick()
        val annotations = instrumentation.targetContext.getString(R.string.reader_annotations)
        compose.onNodeWithText(annotations).performClick()
        compose.onNodeWithText(instrumentation.targetContext.getString(R.string.reader_annotations_empty))
            .assertIsDisplayed()
    }

    private fun showTestHostOverKeyguard() {
        instrumentation.runOnMainSync {
            listOf(Stage.RESUMED, Stage.PAUSED, Stage.STOPPED).forEach { stage ->
                ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(stage).forEach { activity ->
                    activity.setShowWhenLocked(true)
                    activity.setTurnScreenOn(true)
                    activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
            }
        }
        instrumentation.waitForIdleSync()
    }

    private fun localized(chinese: String, english: String): String =
        if (instrumentation.targetContext.resources.configuration.locales[0].language == "zh") chinese else english

    private class DeferredContentsController(
        private val unavailable: Set<ReaderControl> = emptySet(),
        initialPreferences: ReaderPreferences = ReaderPreferences(),
        supportsAnnotations: Boolean = false,
        initialNavigationEntryId: String? = null,
    ) : ReaderScreenController {
        private val loadGate = CompletableDeferred<Unit>()
        private val contentsMutex = Mutex()
        private var contentsLoaded = false
        val loadCalls = AtomicInteger()
        val seekCalls = AtomicInteger()
        val previousPageCalls = AtomicInteger()
        val nextPageCalls = AtomicInteger()
        val chapterNavigationCalls = AtomicInteger()
        val lastSeek = AtomicReference<Double?>()
        var seekAccepted = true
        private val entries = (1..1_000).map { number ->
            val href = "chapter-$number.xhtml"
            ReaderTocEntry(
                title = "Chapter $number",
                location = ReflowReaderLocation(
                    resourceKey = href,
                    progression = 0.0,
                    totalProgression = (number - 1).toDouble() / 999.0,
                    position = number,
                ),
                id = href,
                index = number - 1,
            )
        }

        override val morphology = ReaderMorphology.Reflowable
        override val capabilities = ReaderCapabilities.epub(supportsVolumeKeys = true, supportsCustomFonts = true)
            .copy(supportsAnnotations = supportsAnnotations)
        private val locationState = MutableStateFlow<ReaderLocation?>(entries.first().location)
        override val currentLocation: StateFlow<ReaderLocation?> = locationState
        private val preferenceState = MutableStateFlow(initialPreferences)
        override val preferences: StateFlow<ReaderPreferences> = preferenceState
        private val navigationEntryIdState = MutableStateFlow(initialNavigationEntryId)
        override val currentNavigationEntryId: StateFlow<String?>? = navigationEntryIdState
        override val resumeNotice: StateFlow<ReaderResumeNotice?> = MutableStateFlow(null)
        override val resumeActionFailed: StateFlow<Boolean> = MutableStateFlow(false)
        override val bookmarks: StateFlow<List<ReaderBookmark>> = MutableStateFlow(emptyList())
        override val bookmarkSyncPending: StateFlow<Boolean> = MutableStateFlow(false)
        override val tableOfContents: List<ReaderTocEntry> = emptyList()

        override suspend fun loadTableOfContents(): List<ReaderTocEntry> = contentsMutex.withLock {
            if (!contentsLoaded) {
                loadCalls.incrementAndGet()
                loadGate.await()
                contentsLoaded = true
            }
            entries
        }

        override fun unavailableControls(preferences: ReaderPreferences): Set<ReaderControl> = unavailable

        fun releaseContents() {
            loadGate.complete(Unit)
        }

        override fun goPrevious(): Boolean { previousPageCalls.incrementAndGet(); return false }
        override fun goNext(): Boolean { nextPageCalls.incrementAndGet(); return false }
        override fun goTo(location: ReaderLocation): Boolean {
            chapterNavigationCalls.incrementAndGet()
            locationState.value = location
            return true
        }
        override fun goToTotalProgression(totalProgression: Double): Boolean {
            seekCalls.incrementAndGet()
            lastSeek.set(totalProgression)
            return seekAccepted
        }
        override fun dismissResumeNotice() = Unit
        override fun returnToResumeNotice() = false
        override fun updatePreferences(updated: ReaderPreferences) {
            preferenceState.value = updated
        }
        override fun toggleCurrentBookmark(): ReaderBookmarkChange? = null
        override fun removeBookmark(id: String) = Unit
        override fun goToBookmark(id: String) = false
        override suspend fun flush() = Unit
        override suspend fun close() = Unit
    }
}
