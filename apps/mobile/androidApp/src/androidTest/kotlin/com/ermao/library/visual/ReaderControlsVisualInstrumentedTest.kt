package com.ermao.library.visual

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.app.KeyguardManager
import android.os.SystemClock
import android.view.KeyEvent
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
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

    private fun buildComicArchive(): ByteArray = ByteArrayOutputStream().use { output ->
        ZipOutputStream(output).use { archive ->
            COMIC_PAGE_COLORS.forEachIndexed { index, background ->
                archive.putNextEntry(ZipEntry("pages/page-${index + 1}.png"))
                val bitmap = createIllustratedPage(index + 1, background)
                try {
                    assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, archive))
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
