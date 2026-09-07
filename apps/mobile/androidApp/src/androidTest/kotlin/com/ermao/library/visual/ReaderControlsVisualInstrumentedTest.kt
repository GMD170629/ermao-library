package com.ermao.library.visual

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.app.KeyguardManager
import android.os.SystemClock
import android.view.KeyEvent
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.swipeRight
import androidx.compose.ui.test.swipeUp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.R
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.deleteLocalReaderV5Position
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.keepReaderTestFixtureVisible
import com.ermao.library.features.reader.loadLocalReaderV5Position
import com.ermao.library.features.reader.presentation.READER_CONTENTS_TEST_TAG
import com.ermao.library.features.reader.presentation.READER_PASSIVE_STATUS_TEST_TAG
import com.ermao.library.features.reader.presentation.READER_PANEL_WORKSPACE_TEST_TAG
import com.ermao.library.features.reader.presentation.READER_SETTINGS_TEST_TAG
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgressTiming
import com.ermao.library.shared.modules.reader.ReaderTheme
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.ReaderComicDirection
import com.ermao.library.shared.modules.reader.ReaderComicImageFit
import com.ermao.library.shared.modules.reader.ReaderComicPreferences
import com.ermao.library.shared.modules.reader.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.ReaderCommandCompleted
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.adapter.pdfium.navigator.PdfiumNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi

/**
 * Deterministic local Comic/PDF publications for physical-device visual review.
 * The fixtures remain original CBZ/PDF inputs and never enter production Reader
 * bootstrap, download, conversion or restoration paths.
 */
@RunWith(AndroidJUnit4::class)
class ReaderControlsVisualInstrumentedTest {
    @get:Rule
    val composeRule = createEmptyComposeRule()

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val comicResourceId = "visual-comic-${UUID.randomUUID()}"
    private val pdfResourceId = "visual-pdf-${UUID.randomUUID()}"
    private val epubResourceId = "visual-epub-${UUID.randomUUID()}"
    private lateinit var comicSource: LocalReaderSource
    private lateinit var pdfSource: LocalReaderSource
    private lateinit var epubSource: LocalReaderSource

    @Before
    fun publishLocalVisualPublications() = runBlocking {
        comicSource = ByteArrayInputStream(buildComicArchive()).use { input ->
            publicationStore.publishLocalPublication(
                resourceId = comicResourceId,
                displayTitle = "Local comic controls",
                input = input,
                sourceFormat = ReaderSourceFormat.Cbz,
            )
        }
        pdfSource = ByteArrayInputStream(buildPdf()).use { input ->
            publicationStore.publishLocalPublication(
                resourceId = pdfResourceId,
                displayTitle = "Local PDF controls",
                input = input,
                sourceFormat = ReaderSourceFormat.Pdf,
            )
        }
        epubSource = instrumentation.context.assets.open("reader-v2.epub").use { input ->
            publicationStore.publishLocalEpub(
                resourceId = epubResourceId,
                displayTitle = "Local EPUB controls",
                input = input,
            )
        }
    }

    @After
    fun removeLocalVisualPublications() = runBlocking {
        if (this@ReaderControlsVisualInstrumentedTest::comicSource.isInitialized) {
            deleteLocalReaderV5Position(context, comicSource)
        }
        if (this@ReaderControlsVisualInstrumentedTest::pdfSource.isInitialized) {
            deleteLocalReaderV5Position(context, pdfSource)
        }
        if (this@ReaderControlsVisualInstrumentedTest::epubSource.isInitialized) {
            deleteLocalReaderV5Position(context, epubSource)
        }
        publicationStore.delete(comicResourceId)
        publicationStore.delete(pdfResourceId)
        publicationStore.delete(epubResourceId)
    }

    @Test
    fun comicAndPdfControlsCaptureFromOriginalLocalPublications() {
        val outputDirectory = checkNotNull(context.getExternalFilesDir("reader-controls"))
        val comicRequests = listOf(
            CaptureRequest("comic-controls-warm.png", ReaderPanelCapture.Controls, ReaderTheme.Warm),
            CaptureRequest("comic-controls-day.png", ReaderPanelCapture.Controls, ReaderTheme.Day),
            CaptureRequest("comic-controls-night.png", ReaderPanelCapture.Controls, ReaderTheme.Night),
            CaptureRequest("comic-controls-black.png", ReaderPanelCapture.Controls, ReaderTheme.Black),
            CaptureRequest("comic-appearance.png", ReaderPanelCapture.Appearance, ReaderTheme.Warm),
            CaptureRequest("comic-settings.png", ReaderPanelCapture.Settings, ReaderTheme.Warm),
            CaptureRequest("comic-settings-advanced.png", ReaderPanelCapture.AdvancedSettings, ReaderTheme.Warm),
            CaptureRequest("comic-contents.png", ReaderPanelCapture.Contents, ReaderTheme.Warm),
            CaptureRequest("comic-notes.png", ReaderPanelCapture.Notes, ReaderTheme.Warm),
        )
        val pdfRequests = listOf(
            CaptureRequest("pdf-controls.png", ReaderPanelCapture.Controls, ReaderTheme.Warm),
            CaptureRequest("pdf-appearance.png", ReaderPanelCapture.Appearance, ReaderTheme.Warm),
            CaptureRequest("pdf-settings.png", ReaderPanelCapture.Settings, ReaderTheme.Warm),
            CaptureRequest("pdf-settings-advanced.png", ReaderPanelCapture.AdvancedSettings, ReaderTheme.Warm),
            CaptureRequest("pdf-contents.png", ReaderPanelCapture.Contents, ReaderTheme.Warm),
            CaptureRequest("pdf-notes.png", ReaderPanelCapture.Notes, ReaderTheme.Warm),
        )
        val epubRequests = listOf(
            CaptureRequest("epub-controls.png", ReaderPanelCapture.Controls, ReaderTheme.Warm),
            CaptureRequest("epub-contents.png", ReaderPanelCapture.Contents, ReaderTheme.Warm),
            CaptureRequest("epub-notes.png", ReaderPanelCapture.Notes, ReaderTheme.Warm),
            CaptureRequest("epub-appearance.png", ReaderPanelCapture.Appearance, ReaderTheme.Warm),
            CaptureRequest("epub-settings.png", ReaderPanelCapture.Settings, ReaderTheme.Warm),
            CaptureRequest("epub-settings-advanced.png", ReaderPanelCapture.AdvancedSettings, ReaderTheme.Warm),
            CaptureRequest("epub-settings-night.png", ReaderPanelCapture.Settings, ReaderTheme.Night),
            CaptureRequest("epub-settings-advanced-night.png", ReaderPanelCapture.AdvancedSettings, ReaderTheme.Night),
            CaptureRequest("epub-page-width.png", ReaderPanelCapture.AppearancePageWidth, ReaderTheme.Day),
        )
        val passiveStatusRequests = listOf(
            CaptureRequest("comic-reading-footer-day.png", ReaderPanelCapture.PassiveStatus, ReaderTheme.Day),
        )
        val captures = captureSource(comicSource, passiveStatusRequests, outputDirectory) +
            captureSource(comicSource, comicRequests, outputDirectory) +
            captureSource(pdfSource, pdfRequests, outputDirectory) +
            captureSource(epubSource, epubRequests, outputDirectory)

        assertTrue(captures.all { it.isFile && it.length() > 0 })
    }

    @Test
    fun comicLongPagesPreserveFitAndReachEdges() {
        val resourceId = "comic-geometry-${UUID.randomUUID()}"
        val source = runBlocking {
            val pages = listOf(400 to 3200, 3200 to 400, 400 to 400).map { (width, height) ->
                Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).also { bitmap ->
                    val canvas = Canvas(bitmap)
                    canvas.drawColor(Color.WHITE)
                    val paint = Paint()
                    listOf(Color.RED, Color.GREEN, Color.BLUE).forEachIndexed { index, color ->
                        paint.color = color
                        // Keep vertical edge markers clear of the real system-bar
                        // overlays; otherwise PixelCopy measures an occluded square.
                        val start = if (height > width) {
                            listOf(200f, 1400f, 2600f)[index]
                        } else index * 1400f
                        if (width > height) canvas.drawRect(start, 0f, start + 400f, 400f, paint)
                        else canvas.drawRect(0f, start, 400f, start + 400f, paint)
                    }
                }
            }
            ByteArrayInputStream(buildComicArchive(pages, Bitmap.CompressFormat.JPEG)).use { input ->
                publicationStore.publishLocalPublication(
                    resourceId = resourceId,
                    displayTitle = "Comic geometry regression",
                    input = input,
                    sourceFormat = ReaderSourceFormat.Cbz,
                )
            }
        }
        try {
            ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
                scenario.keepReaderTestFixtureVisible()
                awaitReaderReady(scenario)
                for (direction in ReaderComicDirection.entries) {
                    val preferences = ReaderComicPreferences(direction = direction, pageWidth = 600)
                    setComicGeometryPage(scenario, preferences, 0)
                    val top = checkNotNull(comicColorBounds(Color.RED))
                    assertComicSquare(top, "Width TOP ($direction)")
                    assertTrue("Width became Contain", top.width() > comicViewportSize().second / 4)
                    assertTrue("Width compressed END into the viewport", comicColorBounds(Color.BLUE) == null)
                    dragComicToEdge(Color.BLUE, horizontal = false, forward = true)
                    assertComicSquare(checkNotNull(comicColorBounds(Color.BLUE)), "Width END ($direction)")
                    assertComicPage(scenario, 0)
                    dragComicToEdge(Color.RED, horizontal = false, forward = false)
                    assertComicSquare(checkNotNull(comicColorBounds(Color.RED)), "Width TOP return ($direction)")

                    // Non-overflowing fits must still display the entire tall original.
                    for (fit in listOf(ReaderComicImageFit.Height, ReaderComicImageFit.Contain, ReaderComicImageFit.Original)) {
                        setComicGeometryPage(scenario, preferences.copy(imageFit = fit), 0)
                        val red = checkNotNull(comicColorBounds(Color.RED))
                        assertComicSquare(red, "$fit TOP ($direction)")
                        assertComicSquare(checkNotNull(comicColorBounds(Color.BLUE)), "$fit END ($direction)")
                        val expectedSide = if (fit == ReaderComicImageFit.Original) {
                            minOf(400, comicViewportSize().second / 8)
                        } else comicViewportSize().second / 8
                        assertTrue("$fit changed its scale", kotlin.math.abs(red.width() - expectedSide) <= 3)
                    }

                    // Height fit has the symmetric horizontal-overflow case.
                    setComicGeometryPage(scenario, preferences.copy(imageFit = ReaderComicImageFit.Height), 1)
                    assertTrue("Height compressed END into the viewport", comicColorBounds(Color.BLUE) == null)
                    dragComicToEdge(Color.BLUE, horizontal = true, forward = true)
                    assertComicPage(scenario, 1)
                    dragComicToEdge(Color.RED, horizontal = true, forward = false)
                    assertComicPage(scenario, 1)

                    // An ordinary image still fits, and its horizontal swipe turns a page.
                    setComicGeometryPage(scenario, preferences, 2)
                    assertComicSquare(checkNotNull(comicColorBounds(Color.RED)), "Normal Width ($direction)")
                    composeRule.onNodeWithTag("comic-viewport").performTouchInput {
                        if (direction == ReaderComicDirection.LeftToRight) swipeRight() else swipeLeft()
                    }
                    composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) { comicPageIndex(scenario) == 1 }

                    // Existing enlarged-page panning must coexist with the new overflow scroll.
                    setComicGeometryPage(scenario, preferences.copy(zoom = 1.5), 0)
                    dragComicToEdge(Color.BLUE, horizontal = false, forward = true)
                    assertComicPage(scenario, 0)
                    dragComicToEdge(Color.RED, horizontal = false, forward = false)
                    assertComicPage(scenario, 0)
                }
                // LazyColumn remains the sole vertical scroller in continuous mode.
                setComicGeometryPage(scenario, ReaderComicPreferences(pageWidth = 600, flow = ReaderReadingMode.ContinuousScroll), 0)
                assertComicSquare(checkNotNull(comicColorBounds(Color.RED)), "Continuous TOP")
                dragComicToEdge(Color.BLUE, horizontal = false, forward = true)
            }
        } finally {
            runBlocking {
                try {
                    deleteLocalReaderV5Position(context, source)
                } finally {
                    publicationStore.delete(resourceId)
                }
            }
        }
    }

    @Test
    fun comicContinuousModeKeepsCurrentPage() {
        val resourceId = "comic-flow-${UUID.randomUUID()}"
        val source = runBlocking {
            val pages = (0 until 6).map { index ->
                createIllustratedPage(index + 1, if (index == 3) Color.RED else Color.BLUE)
            }
            ByteArrayInputStream(buildComicArchive(pages)).use { input ->
                publicationStore.publishLocalPublication(
                    resourceId = resourceId,
                    displayTitle = "Comic flow position regression",
                    input = input,
                    sourceFormat = ReaderSourceFormat.Cbz,
                )
            }
        }
        try {
            ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
                scenario.keepReaderTestFixtureVisible()
                awaitReaderReady(scenario)
                lateinit var controller: ReaderScreenController
                scenario.onActivity { activity -> controller = checkNotNull(activity.controllerForTesting) }
                val paginated = controller.preferences.value.let { preferences ->
                    preferences.copy(
                        comic = preferences.comic.copy(
                            direction = ReaderComicDirection.RightToLeft,
                            spreadMode = ReaderComicSpreadMode.Single,
                            flow = ReaderReadingMode.Paged,
                        ),
                    )
                }
                runBlocking {
                    withContext(Dispatchers.Main) {
                        assertEquals(ReaderCommandCompleted, controller.applyPreferences(paginated))
                        assertTrue(controller.goTo(ComicReaderLocation(resourceHref = "pages/3", pageIndex = 3)))
                    }
                }
                composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
                    comicPageIndex(scenario) == 3 && comicColorBounds(Color.RED) != null &&
                        runBlocking { loadLocalReaderV5Position(context, source) }
                            ?.position?.presentation?.currentHref == "pages/3"
                }
                // The regression changes only flow; a second goTo would repair the lost anchor.
                val continuous = paginated.copy(comic = paginated.comic.copy(flow = ReaderReadingMode.ContinuousScroll))
                runBlocking {
                    withContext(Dispatchers.Main) {
                        assertEquals(ReaderCommandCompleted, controller.applyPreferences(continuous))
                    }
                }
                composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
                    comicColorBounds(Color.RED) != null ||
                        (comicPageIndex(scenario) != 3 && comicColorBounds(Color.BLUE) != null)
                }
                // Allow decoded images to settle, while checking that the fourth image stays visible.
                repeat(10) {
                    composeRule.waitForIdle()
                    assertEquals("Changing flow moved away from the fourth image", 3, comicPageIndex(scenario))
                    assertTrue("The fourth image is not visible after changing flow", comicColorBounds(Color.RED) != null)
                    SystemClock.sleep(100L)
                }
                val persisted = runBlocking { loadLocalReaderV5Position(context, source) }
                assertEquals("Flow change persisted a different image", "pages/3", persisted?.position?.presentation?.currentHref)
                assertEquals("Flow change persisted a different page number", 4, persisted?.position?.presentation?.page?.number)
                assertEquals(
                    "Flow change persisted a different locator",
                    "pages/3",
                    org.json.JSONObject(checkNotNull(persisted).position.locator.canonicalJson).getString("href"),
                )
            }
        } finally {
            runBlocking {
                try {
                    deleteLocalReaderV5Position(context, source)
                } finally {
                    publicationStore.delete(resourceId)
                }
            }
        }
    }

    private fun setComicGeometryPage(
        scenario: ActivityScenario<ReaderActivity>,
        preferences: ReaderComicPreferences,
        pageIndex: Int,
    ) {
        scenario.onActivity { activity ->
            val controller = checkNotNull(activity.controllerForTesting)
            controller.updatePreferences(controller.preferences.value.copy(comic = preferences))
            controller.goTo(ComicReaderLocation(resourceHref = "pages/$pageIndex", pageIndex = pageIndex))
        }
        composeRule.waitForIdle()
        composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
            comicPageIndex(scenario) == pageIndex &&
                composeRule.onAllNodesWithTag("comic-viewport").fetchSemanticsNodes().isNotEmpty() &&
                comicColorBounds(Color.RED) != null
        }
        composeRule.waitForIdle()
    }

    private fun comicPageIndex(scenario: ActivityScenario<ReaderActivity>): Int? {
        var pageIndex: Int? = null
        scenario.onActivity { activity ->
            pageIndex = (activity.controllerForTesting?.currentLocation?.value as? ComicReaderLocation)?.pageIndex
        }
        return pageIndex
    }

    private fun assertComicPage(scenario: ActivityScenario<ReaderActivity>, pageIndex: Int) {
        assertTrue("Image pan turned the page", comicPageIndex(scenario) == pageIndex)
    }

    private fun comicViewportSize(): Pair<Int, Int> {
        val bounds = composeRule.onNodeWithTag("comic-viewport").fetchSemanticsNode().boundsInRoot
        return bounds.width.toInt() to bounds.height.toInt()
    }

    private fun assertComicSquare(bounds: Rect, label: String) {
        assertTrue("$label distorted: $bounds", kotlin.math.abs(bounds.width() - bounds.height()) <= 3)
    }

    private fun dragComicToEdge(color: Int, horizontal: Boolean, forward: Boolean) {
        // Slow drags avoid fling-dependent checkpoints; keep pulling after first
        // exposure so the entire edge marker, not a clipped sliver, is reached.
        repeat(32) {
            val marker = comicColorBounds(color)
            val viewport = comicViewportSize()
            if (marker != null && (if (horizontal) marker.width() else marker.height()) >=
                minOf(viewport.first, viewport.second) - 4
            ) return
            composeRule.onNodeWithTag("comic-viewport").performTouchInput {
                if (horizontal) {
                    // Start inside the image, not at the viewport's outermost
                    // pixel, which may be a rounded layout gutter owned by Pager.
                    if (forward) swipeLeft(startX = right * 0.8f, endX = right * 0.2f, durationMillis = 1000)
                    else swipeRight(startX = right * 0.2f, endX = right * 0.8f, durationMillis = 1000)
                } else {
                    // Leave overlapping viewports so continuous scrolling cannot
                    // jump entirely past the checkpoint between pixel samples.
                    if (forward) swipeUp(startY = bottom * 0.7f, endY = bottom * 0.3f, durationMillis = 1000)
                    else swipeDown(startY = bottom * 0.3f, endY = bottom * 0.7f, durationMillis = 1000)
                }
            }
            composeRule.waitForIdle()
        }
        throw AssertionError("Comic edge marker $color is unreachable")
    }

    private fun comicColorBounds(color: Int): Rect? {
        val bitmap = composeRule.onNodeWithTag("comic-viewport").captureToImage().asAndroidBitmap()
        try {
            val pixels = IntArray(bitmap.width * bitmap.height)
            bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
            var left = bitmap.width
            var top = bitmap.height
            var right = -1
            var bottom = -1
            pixels.forEachIndexed { index, pixel ->
                // Measure the half-coverage edge of the scaled primary-color square.
                // Counting only fully saturated pixels erodes interpolated edges but
                // not edges against the image boundary, biasing the measured aspect.
                if (kotlin.math.abs(Color.red(pixel) - Color.red(color)) < 128 &&
                    kotlin.math.abs(Color.green(pixel) - Color.green(color)) < 128 &&
                    kotlin.math.abs(Color.blue(pixel) - Color.blue(color)) < 128 &&
                    maxOf(Color.red(pixel), Color.green(pixel), Color.blue(pixel)) -
                    minOf(Color.red(pixel), Color.green(pixel), Color.blue(pixel)) > 128
                ) {
                    val x = index % bitmap.width
                    val y = index / bitmap.width
                    left = minOf(left, x)
                    top = minOf(top, y)
                    right = maxOf(right, x)
                    bottom = maxOf(bottom, y)
                }
            }
            return if (right < left) null else Rect(left, top, right + 1, bottom + 1)
        } finally {
            bitmap.recycle()
        }
    }

    @OptIn(ExperimentalReadiumApi::class)
    @Test
    fun pdfPositionPersistsDuringContinuousNavigation() {
        val resourceId = "continuous-pdf-${UUID.randomUUID()}"
        val source = runBlocking {
            ByteArrayInputStream(buildPdf(pageCount = 3)).use { input ->
                publicationStore.publishLocalPublication(
                    resourceId = resourceId,
                    displayTitle = "Continuous PDF position",
                    input = input,
                    sourceFormat = ReaderSourceFormat.Pdf,
                )
            }
        }
        try {
            ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
                scenario.keepReaderTestFixtureVisible()
                awaitReaderReady(scenario)
                lateinit var controller: ReaderScreenController
                lateinit var navigator: PdfiumNavigatorFragment
                composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
                    var ready = false
                    scenario.onActivity { activity ->
                        val pdf = activity.supportFragmentManager.fragments
                            .filterIsInstance<PdfiumNavigatorFragment>().singleOrNull()
                        val currentController = activity.controllerForTesting
                        if (pdf?.view != null && currentController != null &&
                            pdf.currentLocator.value.locations.position == 1
                        ) {
                            navigator = pdf
                            controller = currentController
                            ready = true
                        }
                    }
                    ready
                }
                runBlocking {
                    val windowMillis = ReaderProgressTiming.maxUnsavedIntervalMillis
                    // Let the initial page save naturally; never flush to satisfy a checkpoint.
                    val baseline = withTimeout(READER_READY_TIMEOUT_MILLIS) {
                        var saved = loadLocalReaderV5Position(context, source)
                        while (saved == null) {
                            delay(50L)
                            saved = loadLocalReaderV5Position(context, source)
                        }
                        saved
                    }
                    var previousCapture = baseline.capturedAtEpochMillis
                    // All SDK observations are owned/read on Main. The 500 ms bound
                    // reproduces the removed debounce, not the generated save window.
                    val observations = mutableListOf<Pair<Long, Int>>()
                    val observer = launch(Dispatchers.Main) {
                        navigator.currentLocator.collect { locator ->
                            val page = checkNotNull(locator.locations.position)
                            if (observations.lastOrNull()?.second != page) {
                                observations.add(SystemClock.elapsedRealtime() to page)
                            }
                        }
                    }
                    val startedAt = SystemClock.elapsedRealtime()
                    val startedAtEpochMillis = System.currentTimeMillis()
                    val navigation = launch(Dispatchers.Main) {
                        var pageIndex = 1
                        while (isActive) {
                            assertTrue("PDF navigation was rejected", controller.goTo(PdfReaderLocation(pageIndex, 0.0)))
                            pageIndex = 3 - pageIndex
                            delay(200L)
                        }
                    }
                    try {
                        for (checkpoint in 1..2) {
                            val deadline = startedAt + checkpoint * windowMillis
                            delay((deadline - SystemClock.elapsedRealtime()).coerceAtLeast(0L))
                            val saved = loadLocalReaderV5Position(context, source)
                            val checkedAtEpochMillis = System.currentTimeMillis()
                            withContext(Dispatchers.Main) {
                                val checkedAt = SystemClock.elapsedRealtime()
                                assertTrue("Navigation stopped before checkpoint $checkpoint", navigation.isActive)
                                assertTrue("SDK observer stopped", observer.isActive)
                                assertTrue("Missed checkpoint $checkpoint", checkedAt - deadline < 500L)
                                assertTrue("SDK did not visit both target pages", observations.map { it.second }.containsAll(listOf(2, 3)))
                                assertTrue("SDK locator changes started too late", observations.first().first - startedAt < 500L)
                                assertTrue(
                                    "SDK locator changes left a debounce-sized idle gap",
                                    observations.zipWithNext().all { (before, after) -> after.first - before.first < 500L },
                                )
                                assertTrue("SDK locator stopped changing", checkedAt - observations.last().first < 500L)
                                val captured = checkNotNull(saved) { "No durable PDF position at checkpoint $checkpoint" }
                                assertTrue("No new capture at checkpoint $checkpoint", captured.capturedAtEpochMillis > previousCapture)
                                assertTrue("Capture predates continuous navigation", captured.capturedAtEpochMillis >= startedAtEpochMillis)
                                assertTrue(
                                    "Durable capture exceeds the generated save window",
                                    checkedAtEpochMillis - captured.capturedAtEpochMillis in 0L..windowMillis,
                                )
                                assertTrue("Saved page was not observed by the SDK", captured.position.presentation.page?.number in setOf(2, 3))
                                previousCapture = captured.capturedAtEpochMillis
                            }
                        }
                    } finally {
                        withContext(NonCancellable) {
                            navigation.cancelAndJoin()
                            observer.cancelAndJoin()
                        }
                    }
                }
            }
        } finally {
            runBlocking {
                try {
                    deleteLocalReaderV5Position(context, source)
                } finally {
                    publicationStore.delete(resourceId)
                }
            }
        }
    }

    private fun captureSource(
        source: LocalReaderSource,
        requests: List<CaptureRequest>,
        outputDirectory: File,
    ): List<File> = ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            awaitReaderReady(scenario)
            assertFalse(
                "Unlock the physical device before capturing Reader screenshots",
                context.getSystemService(KeyguardManager::class.java).isKeyguardLocked,
            )
            requests.map { request ->
                if (source == comicSource && request.panel == ReaderPanelCapture.Contents) {
                    scenario.onActivity { activity -> activity.controllerForTesting?.goNext() }
                    composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
                        var onSecondPage = false
                        scenario.onActivity { activity ->
                            onSecondPage = (activity.controllerForTesting?.currentLocation?.value as? ComicReaderLocation)
                                ?.pageIndex == 1
                        }
                        onSecondPage
                    }
                }
                scenario.onActivity { activity ->
                    val controller = checkNotNull(activity.controllerForTesting)
                    controller.updatePreferences(
                        controller.preferences.value.copy(
                            appearance = controller.preferences.value.appearance.copy(theme = request.theme),
                            display = controller.preferences.value.display.copy(
                                showClock = request.panel == ReaderPanelCapture.PassiveStatus,
                            ),
                        ),
                    )
                }
                composeRule.waitForIdle()
                if (request.panel == ReaderPanelCapture.PassiveStatus) {
                    composeRule.onNodeWithTag(READER_PASSIVE_STATUS_TEST_TAG).assertIsDisplayed()
                } else {
                    showControls(scenario)
                }
                when (request.panel) {
                    ReaderPanelCapture.PassiveStatus -> Unit
                    ReaderPanelCapture.Controls -> Unit
                    ReaderPanelCapture.Appearance -> openPanel("reader-appearance")
                    ReaderPanelCapture.Notes -> openPanel("reader-notes")
                    ReaderPanelCapture.AppearancePageWidth -> {
                        openPanel("reader-appearance")
                        composeRule.onNodeWithTag("reader-setting-textPageWidth")
                            .performScrollTo()
                        composeRule.waitForIdle()
                    }
                    ReaderPanelCapture.Settings -> openPanel(READER_SETTINGS_TEST_TAG)
                    ReaderPanelCapture.AdvancedSettings -> {
                        openPanel(READER_SETTINGS_TEST_TAG)
                        composeRule.onNodeWithTag("reader-advanced-settings")
                            .performScrollTo()
                            .performClick()
                        composeRule.waitForIdle()
                    }
                    ReaderPanelCapture.Contents -> openPanel(READER_CONTENTS_TEST_TAG)
                }
                val destination = captureCurrent(request, outputDirectory)
                if (
                    request.panel != ReaderPanelCapture.Controls &&
                    request.panel != ReaderPanelCapture.PassiveStatus
                ) {
                    scenario.onActivity { activity -> activity.onBackPressedDispatcher.onBackPressed() }
                    composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
                        // The home console remains in the standard bottom sheet after closing
                        // a panel. Its workspace, not the entire console, must disappear.
                        composeRule.onAllNodesWithTag(READER_PANEL_WORKSPACE_TEST_TAG).fetchSemanticsNodes().isEmpty()
                    }
                }
                destination
            }
        }

    private fun captureCurrent(request: CaptureRequest, outputDirectory: File): File {
        val destination = File(outputDirectory, request.outputName)
        val temporary = File(outputDirectory, ".${request.outputName}.tmp")
        listOf(destination, temporary).forEach { file ->
            assertTrue("Failed to clear stale ${file.name}", !file.exists() || file.delete())
        }
        instrumentation.waitForIdleSync()
        val screenshot = instrumentation.captureStableWholeDisplay()
        try {
            FileOutputStream(temporary).use { output ->
                assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG, 100, output))
            }
            assertTrue("Failed to publish ${request.outputName}", temporary.renameTo(destination))
            return destination
        } finally {
            screenshot.recycle()
        }
    }

    private fun awaitReaderReady(scenario: ActivityScenario<ReaderActivity>) {
        composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
            var ready = false
            scenario.onActivity { ready = it.controllerForTesting != null }
            ready
        }
        composeRule.waitForIdle()
    }

    private fun showControls(scenario: ActivityScenario<ReaderActivity>) {
        scenario.onActivity { activity ->
            activity.dispatchKeyEvent(KeyEvent(SystemClock.uptimeMillis(), SystemClock.uptimeMillis(), KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ESCAPE, 0))
        }
        composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
            var visible = false
            scenario.onActivity { visible = it.controlsVisibleForTesting }
            visible
        }
        composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
            runCatching { composeRule.onNodeWithTag(READER_SETTINGS_TEST_TAG).assertIsDisplayed() }.isSuccess
        }
        composeRule.onNodeWithTag(READER_SETTINGS_TEST_TAG).assertIsDisplayed()
        composeRule.waitForIdle()
    }

    private fun openPanel(tag: String) {
        composeRule.onNodeWithTag(tag).assertIsDisplayed().performClick()
        composeRule.waitUntil(READER_READY_TIMEOUT_MILLIS) {
            runCatching { composeRule.onNodeWithTag(READER_PANEL_WORKSPACE_TEST_TAG).assertIsDisplayed() }.isSuccess
        }
        composeRule.onNodeWithTag(READER_PANEL_WORKSPACE_TEST_TAG).assertIsDisplayed()
    }

    private fun buildComicArchive(
        pages: List<Bitmap> = COMIC_PAGE_COLORS.mapIndexed { index, color -> createIllustratedPage(index + 1, color) },
        format: Bitmap.CompressFormat = Bitmap.CompressFormat.PNG,
    ): ByteArray = ByteArrayOutputStream().use { output ->
        ZipOutputStream(output).use { archive ->
            pages.forEachIndexed { index, bitmap ->
                val extension = if (format == Bitmap.CompressFormat.JPEG) "jpg" else "png"
                archive.putNextEntry(ZipEntry("pages/page-${index + 1}.$extension"))
                try {
                    assertTrue(bitmap.compress(format, 100, archive))
                } finally {
                    bitmap.recycle()
                }
                archive.closeEntry()
            }
        }
        output.toByteArray()
    }

    private fun buildPdf(pageCount: Int = PDF_PAGE_COLORS.size): ByteArray = ByteArrayOutputStream().use { output ->
        val document = PdfDocument()
        try {
            repeat(pageCount) { index ->
                val background = PDF_PAGE_COLORS[index % PDF_PAGE_COLORS.size]
                val page = document.startPage(PdfDocument.PageInfo.Builder(PAGE_WIDTH, PAGE_HEIGHT, index + 1).create())
                drawIllustratedPage(page.canvas, index + 1, background, "LOCAL PDF")
                document.finishPage(page)
            }
            document.writeTo(output)
        } finally {
            document.close()
        }
        output.toByteArray()
    }

    private fun createIllustratedPage(pageNumber: Int, background: Int): Bitmap =
        Bitmap.createBitmap(PAGE_WIDTH, PAGE_HEIGHT, Bitmap.Config.ARGB_8888).also { bitmap ->
            drawIllustratedPage(Canvas(bitmap), pageNumber, background, "LOCAL COMIC")
        }

    private fun drawIllustratedPage(canvas: Canvas, pageNumber: Int, background: Int, title: String) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        canvas.drawColor(background)
        paint.color = Color.argb(210, 255, 255, 255)
        canvas.drawRoundRect(72f, 80f, 1008f, 330f, 36f, 36f, paint)
        paint.color = Color.rgb(45, 36, 31)
        paint.typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        paint.textSize = 62f
        canvas.drawText(title, 120f, 190f, paint)
        paint.textSize = 40f
        canvas.drawText("PAGE ${pageNumber.toString().padStart(2, '0')}", 120f, 270f, paint)

        paint.color = Color.argb(185, 255, 255, 255)
        canvas.drawRoundRect(72f, 390f, 646f, 1030f, 32f, 32f, paint)
        paint.color = Color.argb(150, 30, 30, 30)
        canvas.drawCircle(360f, 640f, 150f, paint)
        paint.color = Color.argb(210, 255, 255, 255)
        canvas.drawCircle(310f, 610f, 22f, paint)
        canvas.drawCircle(410f, 610f, 22f, paint)

        paint.color = Color.argb(220, 255, 255, 255)
        canvas.drawRoundRect(692f, 390f, 1008f, 710f, 32f, 32f, paint)
        canvas.drawRoundRect(692f, 760f, 1008f, 1030f, 32f, 32f, paint)
        canvas.drawRoundRect(72f, 1090f, 1008f, 1510f, 32f, 32f, paint)
        paint.color = Color.argb(130, 45, 36, 31)
        repeat(5) { line ->
            val right = if (line == 4) 690f else 910f
            canvas.drawRoundRect(130f, 1180f + line * 58f, right, 1200f + line * 58f, 10f, 10f, paint)
        }
    }
}

private data class CaptureRequest(
    val outputName: String,
    val panel: ReaderPanelCapture,
    val theme: ReaderTheme,
)

private enum class ReaderPanelCapture {
    PassiveStatus,
    Controls,
    Appearance,
    Notes,
    AppearancePageWidth,
    Settings,
    AdvancedSettings,
    Contents,
}

private val COMIC_PAGE_COLORS = listOf(
    Color.rgb(218, 137, 93),
    Color.rgb(76, 135, 144),
)
private val PDF_PAGE_COLORS = listOf(
    Color.rgb(237, 226, 207),
)
private const val PAGE_WIDTH = 1080
private const val PAGE_HEIGHT = 1600
private const val READER_READY_TIMEOUT_MILLIS = 30_000L
