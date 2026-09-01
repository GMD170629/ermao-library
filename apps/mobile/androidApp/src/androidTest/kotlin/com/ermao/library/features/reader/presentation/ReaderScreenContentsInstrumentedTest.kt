package com.ermao.library.features.reader.presentation

import android.view.WindowManager
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTouchInput
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
        assertEquals(1, controller.loadCalls.get())

        controller.releaseContents()
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithText("Chapter 1").fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText("Chapter 1").assertIsDisplayed()
        compose.onNodeWithText("Chapter 1000").assertDoesNotExist()

        compose.onNodeWithContentDescription(done).performClick()
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithTag(READER_SHEET_TEST_TAG).fetchSemanticsNodes().isEmpty()
        }
        compose.onNodeWithTag(READER_CONTENTS_TEST_TAG).performClick()
        compose.onNodeWithText("Chapter 1").assertIsDisplayed()
        compose.onNodeWithTag(READER_CONTENTS_LOADING_TEST_TAG).assertDoesNotExist()
        assertEquals(1, controller.loadCalls.get())
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
    fun androidReaderSettingsDoNotExposeDoublePageMode() {
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
        compose.onNodeWithTag("reader-setting-textSpread").assertDoesNotExist()
    }

    @Test
    fun restoreWarningCanBeDismissed() {
        compose.mainClock.autoAdvance = false
        val controller = DeferredContentsController().apply { showRestoreWarning() }
        val dismiss = instrumentation.targetContext.getString(R.string.reader_restore_warning_dismiss)
        compose.setContent {
            ReaderScreen(
                title = "Restore warning fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = false,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()
        compose.mainClock.advanceTimeByFrame()

        compose.onNodeWithTag(READER_RESTORE_WARNING_TEST_TAG).assertIsDisplayed()
        compose.onNodeWithContentDescription(dismiss).performClick()
        compose.mainClock.advanceTimeByFrame()
        compose.waitForIdle()
        compose.onNodeWithTag(READER_RESTORE_WARNING_TEST_TAG).assertDoesNotExist()
        assertEquals(null, controller.restoreWarning.value)
    }

    @Test
    fun restoreWarningAutomaticallyDisappears() {
        compose.mainClock.autoAdvance = false
        val controller = DeferredContentsController().apply { showRestoreWarning() }
        compose.setContent {
            ReaderScreen(
                title = "Restore warning timeout fixture",
                controller = controller,
                opening = false,
                openError = null,
                controlsVisible = false,
                onControlsVisibleChange = {},
                onClose = {},
                onNavigatorContainerReady = {},
            )
        }
        showTestHostOverKeyguard()
        compose.mainClock.advanceTimeByFrame()
        compose.onNodeWithTag(READER_RESTORE_WARNING_TEST_TAG).assertIsDisplayed()

        compose.mainClock.advanceTimeBy(RESTORE_WARNING_AUTO_DISMISS_MILLIS + 1)
        compose.waitForIdle()
        compose.onNodeWithTag(READER_RESTORE_WARNING_TEST_TAG).assertDoesNotExist()
        assertEquals(null, controller.restoreWarning.value)
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

    private class DeferredContentsController : ReaderScreenController {
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
        private val locationState = MutableStateFlow<ReaderLocation?>(entries.first().location)
        override val currentLocation: StateFlow<ReaderLocation?> = locationState
        override val preferences: StateFlow<ReaderPreferences> = MutableStateFlow(ReaderPreferences())
        private val restoreWarningState = MutableStateFlow<ReaderError?>(null)
        override val restoreWarning: StateFlow<ReaderError?> = restoreWarningState
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
        fun showRestoreWarning() {
            restoreWarningState.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        }
        override fun dismissRestoreWarning() {
            restoreWarningState.value = null
        }
        override fun dismissResumeNotice() = Unit
        override fun returnToResumeNotice() = false
        override fun updatePreferences(updated: ReaderPreferences) = Unit
        override fun toggleCurrentBookmark(): ReaderBookmarkChange? = null
        override fun removeBookmark(id: String) = Unit
        override fun goToBookmark(id: String) = false
        override suspend fun flush() = Unit
        override suspend fun close() = Unit
    }
}
