package com.ermao.library.visual

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.SystemClock
import android.view.Choreographer
import android.view.InputDevice
import android.view.MotionEvent
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.R
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class VisualFixtureActivityTest {
    @get:Rule
    val composeRule = createEmptyComposeRule()

    @Test
    fun variantIntentContractRejectsMissingAndUnknownValuesAndRoundTripsMatrix() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val invalidIntents = listOf(
            Intent(context, VisualFixtureActivity::class.java),
            Intent(context, VisualFixtureActivity::class.java)
                .putExtra(VisualFixtureContract.EXTRA_SCENARIO, "unknown"),
            Intent(context, VisualFixtureActivity::class.java)
                .putExtra(VisualFixtureContract.EXTRA_SCENARIO, VisualFixtureScenario.HomeDefault.wireValue)
                .putExtra(VisualFixtureContract.EXTRA_LOCALE, "unknown")
                .putExtra(VisualFixtureContract.EXTRA_APPEARANCE, VisualFixtureAppearance.Light.wireValue),
            Intent(context, VisualFixtureActivity::class.java)
                .putExtra(VisualFixtureContract.EXTRA_SCENARIO, VisualFixtureScenario.HomeDefault.wireValue)
                .putExtra(VisualFixtureContract.EXTRA_LOCALE, VisualFixtureLocale.ZhCn.wireValue)
                .putExtra(VisualFixtureContract.EXTRA_APPEARANCE, "unknown"),
        )
        invalidIntents.forEach { intent ->
            assertEquals(null, VisualFixtureContract.variantFrom(intent))
        }
        visualFixtureVariants.forEach { variant ->
            assertEquals(variant, VisualFixtureContract.variantFrom(VisualFixtureContract.intent(context, variant)))
        }
    }

    @Test
    fun goldenComparisonProfilesAreExplicitAndUnknownDevicesFailClosed() {
        assertEquals(
            GoldenComparisonProfile.ReviewedEmulator,
            resolveGoldenComparisonProfile(
                CaptureDeviceProfile(width = 1080, height = 2400, densityDpi = 420, apiLevel = 36),
            ),
        )
        assertEquals(
            GoldenComparisonProfile.PhysicalApi31PendingReview,
            resolveGoldenComparisonProfile(
                CaptureDeviceProfile(width = 1440, height = 3200, densityDpi = 560, apiLevel = 31),
            ),
        )
        assertTrue(
            "An unknown capture profile must fail closed",
            runCatching {
                resolveGoldenComparisonProfile(
                    CaptureDeviceProfile(width = 1080, height = 2340, densityDpi = 440, apiLevel = 35),
                )
            }.exceptionOrNull() is AssertionError,
        )
        assertTrue(isDynamicSystemChromePixel(x = 720, y = 0, width = 1440, height = 3200))
        assertTrue(isDynamicSystemChromePixel(x = 720, y = 3199, width = 1440, height = 3200))
        assertFalse(isDynamicSystemChromePixel(x = 720, y = 256, width = 1440, height = 3200))
    }

    @Test
    fun sevenScenariosCaptureInBothLocalesAndAppearancesWithoutPromotingBaselines() {
        val outputDirectory = visualFixtureOutputDirectory()
        val outputNames = visualFixtureVariants.map(VisualFixtureVariant::outputName)
        outputDirectory.prepareCapturePaths(outputNames)
        assertEquals(EXPECTED_CAPTURE_COUNT, visualFixtureVariants.size)
        val captures = visualFixtureVariants.map { expected ->
            captureVariant(expected, outputDirectory, expected.outputName)
        }
        assertEquals(EXPECTED_CAPTURE_COUNT, captures.size)
        assertEquals(visualFixtureVariants.map(VisualFixtureVariant::outputName).toSet(), captures.map { it.name }.toSet())
    }

    @Test
    fun keyScreensRemainReachableAtTwoHundredPercentFontScaleInBothLocales() {
        val outputDirectory = visualFixtureOutputDirectory()
        val outputNames = largeFontFixtureVariants.map(::largeFontOutputName)
        outputDirectory.prepareCapturePaths(outputNames)
        val captures = largeFontFixtureVariants.map { expected ->
            captureVariant(
                variant = expected,
                outputDirectory = outputDirectory,
                outputName = largeFontOutputName(expected),
                fontScale = 2f,
                reachabilityTag = largeFontReachabilityTag(expected.scenario),
            )
        }
        assertEquals(EXPECTED_LARGE_FONT_CAPTURE_COUNT, captures.size)
    }

    @Test
    fun workDetailContinuousStatesCaptureForExternalReview() {
        val outputDirectory = visualFixtureOutputDirectory()
        val variants = listOf(
            VisualFixtureScenario.BookAbout,
            VisualFixtureScenario.BookResources,
            VisualFixtureScenario.BookSingleEbook,
        ).map { scenario ->
            VisualFixtureVariant(
                scenario = scenario,
                locale = VisualFixtureLocale.ZhCn,
                appearance = VisualFixtureAppearance.Light,
            )
        }
        outputDirectory.prepareCapturePaths(variants.map(VisualFixtureVariant::outputName))
        val captures = variants.map { expected ->
            captureVariant(expected, outputDirectory, expected.outputName)
        }
        assertEquals(variants.map(VisualFixtureVariant::outputName), captures.map(File::getName))
    }

    @Test
    fun englishWorkDetailPopupsKeepTheRequestedLocaleOutsideTheActivityWindow() {
        val variant = VisualFixtureVariant(
            scenario = VisualFixtureScenario.BookActions,
            locale = VisualFixtureLocale.EnUs,
            appearance = VisualFixtureAppearance.Light,
        )
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch<VisualFixtureActivity>(
            VisualFixtureContract.intent(instrumentation.targetContext, variant),
        ).use { scenario ->
            lateinit var fixtureActivity: VisualFixtureActivity
            scenario.onActivity { activity -> fixtureActivity = activity }
            composeRule.waitUntil(CAPTURE_READY_TIMEOUT_MILLIS) { fixtureActivity.isCaptureReady }
            assertScenarioRoot(variant)
            revealRequestedOverlay(variant, scenario)

            val addToShelf = scenario.localizedString(variant, R.string.work_control_add_shelf)
            awaitTextDisplayed(addToShelf)
            composeRule.onNode(
                matcher = hasText(addToShelf) and hasAnyAncestor(hasTestTag("work-book-control-menu")),
                useUnmergedTree = true,
            ).performClick()
            awaitTagDisplayed("work-shelf-picker-sheet")
            awaitTagDisplayed("work-shelf-picker-title")
            awaitTextDisplayed(scenario.localizedString(variant, R.string.work_shelf_picker_title))
            awaitTextDisplayed(scenario.localizedString(variant, R.string.work_shelf_save))
        }
    }

    @Test
    fun workDetailQuickControlsAndFullPathDialogAreInteractive() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val variant = VisualFixtureVariant(
            scenario = VisualFixtureScenario.BookResources,
            locale = VisualFixtureLocale.ZhCn,
            appearance = VisualFixtureAppearance.Light,
        )
        ActivityScenario.launch<VisualFixtureActivity>(
            VisualFixtureContract.intent(instrumentation.targetContext, variant),
        ).use { scenario ->
            lateinit var fixtureActivity: VisualFixtureActivity
            scenario.onActivity { activity -> fixtureActivity = activity }
            composeRule.waitUntil(CAPTURE_READY_TIMEOUT_MILLIS) { fixtureActivity.isCaptureReady }

            composeRule.onNodeWithTag("work-reading-status-action")
                .assertTextEquals(scenario.localizedString(variant, R.string.work_quick_reading_unread))
                .performClick()
                .assertTextEquals(scenario.localizedString(variant, R.string.work_quick_reading_read))

            composeRule.onNodeWithTag("work-download-action")
                .assertTextEquals(scenario.localizedString(variant, R.string.work_quick_downloaded))
                .performClick()
            awaitTextDisplayed(scenario.localizedString(variant, R.string.downloads_remove_title))
        }

        val pathVariant = variant.copy(scenario = VisualFixtureScenario.BookAbout)
        ActivityScenario.launch<VisualFixtureActivity>(
            VisualFixtureContract.intent(instrumentation.targetContext, pathVariant),
        ).use { scenario ->
            lateinit var fixtureActivity: VisualFixtureActivity
            scenario.onActivity { activity -> fixtureActivity = activity }
            composeRule.waitUntil(CAPTURE_READY_TIMEOUT_MILLIS) { fixtureActivity.isCaptureReady }
            val fullPath = "/library/三体系列/第二卷 黑暗森林.epub"
            composeRule.onNodeWithTag("work-detail-list").performScrollToIndex(5)
            composeRule.onNodeWithText(fullPath).performScrollTo().performClick()
            awaitTextDisplayed(scenario.localizedString(pathVariant, R.string.work_metadata_file_path_full_title))
        }
    }

    private fun visualFixtureOutputDirectory(): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        return checkNotNull(context.getExternalFilesDir("visual-fixtures"))
    }

    private fun captureVariant(
        variant: VisualFixtureVariant,
        outputDirectory: File,
        outputName: String,
        fontScale: Float = 1f,
        reachabilityTag: String? = null,
    ): File {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.setInTouchMode(true)
        val context = instrumentation.targetContext
        val intent = VisualFixtureContract.intent(context, variant).apply {
            putExtra(VisualFixtureContract.EXTRA_FONT_SCALE, fontScale)
        }
        return ActivityScenario.launch<VisualFixtureActivity>(intent).use { scenario ->
            lateinit var fixtureActivity: VisualFixtureActivity
            scenario.onActivity { activity -> fixtureActivity = activity }
            composeRule.waitUntil(CAPTURE_READY_TIMEOUT_MILLIS) { fixtureActivity.isCaptureReady }
            assertEquals(variant, fixtureActivity.renderedVariant)
            assertScenarioRoot(variant)
            revealRequestedOverlay(variant, scenario)
            instrumentation.movePointerToSystemBar()
            composeRule.waitForIdle()
            instrumentation.waitForIdleSync()
            val screenshot = when (visualFixtureCaptureSurface(variant.scenario)) {
                VisualFixtureCaptureSurface.WholeDisplay -> instrumentation.captureStableWholeDisplay()
            }
            try {
                assertTrue(screenshot.width > 0)
                assertTrue(screenshot.height > 0)
                assertTrue("$outputName rendered as a single-color frame", screenshot.sampledColorCount() > 1)
                reachabilityTag?.let(::assertReachabilityTarget)
                if (fontScale == DEFAULT_FONT_SCALE) {
                    screenshot.assertMatchesReviewedGoldenOrCapturePending(outputName)
                }
                val destination = File(outputDirectory, outputName)
                val temporary = File(outputDirectory, ".$outputName.tmp")
                FileOutputStream(temporary).use { output ->
                    assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG, 100, output))
                }
                assertTrue("Failed to publish $outputName atomically", temporary.renameTo(destination))
                assertTrue(destination.isFile)
                assertTrue(destination.length() > 0)
                destination
            } finally {
                screenshot.recycle()
            }
        }
    }

    private fun assertReachabilityTarget(tag: String) {
        when (tag) {
            HOME_LARGE_FONT_LAST_ITEM_TAG -> {
                composeRule.onNodeWithTag("home-recent-reading-list").performScrollToIndex(HOME_LARGE_FONT_LAST_ITEM_INDEX)
                composeRule.onNodeWithTag(tag).assertIsDisplayed()
            }
            LIBRARY_LARGE_FONT_LAST_ITEM_TAG -> {
                composeRule.onNodeWithTag("library-works-grid").performScrollToIndex(LIBRARY_LARGE_FONT_LAST_ITEM_INDEX)
                composeRule.onNodeWithTag(tag).assertIsDisplayed()
            }
            LIBRARY_FILTER_LARGE_FONT_APPLY_TAG -> assertFilterApplyReachable()
            BOOK_RESOURCE_LARGE_FONT_LAST_ITEM_TAG -> {
                composeRule.onNodeWithTag("work-detail-list").performScrollToIndex(BOOK_RESOURCE_GRID_ITEM_INDEX)
                composeRule.onNodeWithTag(tag).performScrollTo().assertIsDisplayed()
            }
            else -> composeRule.onNodeWithTag(tag).performScrollTo().assertIsDisplayed()
        }
    }

    private fun assertFilterApplyReachable() {
        val applyAction = composeRule.onNodeWithTag(LIBRARY_FILTER_LARGE_FONT_APPLY_TAG)
        applyAction.performScrollTo()
        repeat(FILTER_SCROLL_GESTURE_ATTEMPTS) {
            if (runCatching { applyAction.assertIsDisplayed() }.isSuccess) return
            composeRule.onNodeWithTag("library-filter-scroll").performTouchInput { swipeUp() }
            composeRule.waitForIdle()
        }
        applyAction.assertIsDisplayed()
    }

    private fun assertScenarioRoot(variant: VisualFixtureVariant) {
        val rootTag = when (variant.scenario) {
            VisualFixtureScenario.HomeDefault -> "home-continue"
            VisualFixtureScenario.LibraryBooks,
            VisualFixtureScenario.LibraryFilter,
            -> "tab-library"
            VisualFixtureScenario.BookAbout,
            VisualFixtureScenario.BookResources,
            VisualFixtureScenario.BookSingleEbook,
            VisualFixtureScenario.BookActions,
            -> "work-detail"
        }
        composeRule.onNodeWithTag(rootTag).assertIsDisplayed()
    }

    private fun revealRequestedOverlay(
        variant: VisualFixtureVariant,
        scenario: ActivityScenario<VisualFixtureActivity>,
    ) {
        when (variant.scenario) {
            VisualFixtureScenario.LibraryFilter -> {
                val filterTitle = scenario.localizedString(variant, R.string.library_filter_title)
                awaitTagDisplayed("library-filter-sheet")
                awaitTagDisplayed("library-filter-title")
                composeRule.onNodeWithTag("library-filter-title").assertTextEquals(filterTitle)
            }
            VisualFixtureScenario.BookActions -> {
                composeRule.onNodeWithTag("work-more-action").performClick()
                composeRule.waitForIdle()
                awaitTagDisplayed("work-book-control-menu")
            }
            VisualFixtureScenario.BookAbout,
            VisualFixtureScenario.BookResources,
            VisualFixtureScenario.BookSingleEbook,
            -> Unit
            else -> Unit
        }
    }

    private fun awaitTagDisplayed(tag: String) {
        composeRule.waitUntil(CAPTURE_READY_TIMEOUT_MILLIS) {
            runCatching {
                composeRule.onNodeWithTag(tag).assertIsDisplayed()
            }.isSuccess
        }
        composeRule.onNodeWithTag(tag).assertIsDisplayed()
    }

    private fun awaitTextDisplayed(text: String) {
        composeRule.waitUntil(CAPTURE_READY_TIMEOUT_MILLIS) {
            runCatching {
                composeRule.onNodeWithText(text, useUnmergedTree = true).assertIsDisplayed()
            }.isSuccess
        }
        composeRule.onNodeWithText(text, useUnmergedTree = true).assertIsDisplayed()
    }
}

private fun File.prepareCapturePaths(outputNames: List<String>) {
    outputNames.forEach { outputName ->
        listOf(File(this, outputName), File(this, ".$outputName.tmp")).forEach { output ->
            assertTrue("Failed to clear stale fixture ${output.name}", !output.exists() || output.delete())
        }
    }
}

private fun largeFontOutputName(variant: VisualFixtureVariant): String =
    "${variant.scenario.wireValue}-${variant.locale.wireValue}-fontScale-2.png"

private fun largeFontReachabilityTag(scenario: VisualFixtureScenario): String = when (scenario) {
    VisualFixtureScenario.HomeDefault -> HOME_LARGE_FONT_LAST_ITEM_TAG
    VisualFixtureScenario.LibraryBooks -> LIBRARY_LARGE_FONT_LAST_ITEM_TAG
    VisualFixtureScenario.LibraryFilter -> LIBRARY_FILTER_LARGE_FONT_APPLY_TAG
    VisualFixtureScenario.BookResources -> BOOK_RESOURCE_LARGE_FONT_LAST_ITEM_TAG
    else -> error("No large-font reachability target for ${scenario.wireValue}")
}

private const val HOME_LARGE_FONT_LAST_ITEM_TAG = "work-work-3"
private const val HOME_LARGE_FONT_LAST_ITEM_INDEX = 2
private const val LIBRARY_LARGE_FONT_LAST_ITEM_TAG = "work-work-6"
private const val LIBRARY_LARGE_FONT_LAST_ITEM_INDEX = 5
private const val LIBRARY_FILTER_LARGE_FONT_APPLY_TAG = "library-filter-apply"
private const val FILTER_SCROLL_GESTURE_ATTEMPTS = 4
private const val BOOK_RESOURCE_LARGE_FONT_LAST_ITEM_TAG = "work-resource-resource-4"
private const val BOOK_RESOURCE_GRID_ITEM_INDEX = 3

private fun android.app.Instrumentation.movePointerToSystemBar() {
    val now = SystemClock.uptimeMillis()
    val displayMetrics = targetContext.resources.displayMetrics
    val cancel = MotionEvent.obtain(
        now,
        now,
        MotionEvent.ACTION_CANCEL,
        displayMetrics.widthPixels / 2f,
        displayMetrics.heightPixels / 2f,
        0,
    ).apply {
        source = InputDevice.SOURCE_TOUCHSCREEN
    }
    val event = MotionEvent.obtain(
        now,
        now,
        MotionEvent.ACTION_HOVER_MOVE,
        displayMetrics.widthPixels / 2f,
        1f,
        0,
    ).apply {
        source = InputDevice.SOURCE_MOUSE
    }
    try {
        uiAutomation.injectInputEvent(cancel, true)
        uiAutomation.injectInputEvent(event, true)
        waitForIdleSync()
    } finally {
        cancel.recycle()
        event.recycle()
    }
}

private val visualFixtureScenarioOrder: List<VisualFixtureScenario> =
    listOf(
        VisualFixtureScenario.BookAbout,
        VisualFixtureScenario.BookResources,
        VisualFixtureScenario.BookSingleEbook,
        VisualFixtureScenario.HomeDefault,
        VisualFixtureScenario.LibraryBooks,
        // Modal fixtures run last so their exit transitions cannot cover the
        // first frame of a subsequent full-screen golden.
        VisualFixtureScenario.LibraryFilter,
        VisualFixtureScenario.BookActions,
    )

private val visualFixtureVariants: List<VisualFixtureVariant> =
    visualFixtureScenarioOrder.flatMap { scenario ->
        VisualFixtureLocale.entries.flatMap { locale ->
            VisualFixtureAppearance.entries.map { appearance ->
                VisualFixtureVariant(scenario, locale, appearance)
            }
        }
    }

private val largeFontFixtureVariants: List<VisualFixtureVariant> =
    listOf(
        VisualFixtureScenario.HomeDefault,
        VisualFixtureScenario.LibraryBooks,
        VisualFixtureScenario.LibraryFilter,
        VisualFixtureScenario.BookResources,
    ).flatMap { scenario ->
        VisualFixtureLocale.entries.map { locale ->
            VisualFixtureVariant(scenario, locale, VisualFixtureAppearance.Light)
        }
    }

private fun ActivityScenario<VisualFixtureActivity>.localizedString(
    variant: VisualFixtureVariant,
    resourceId: Int,
): String {
    var value: String? = null
    onActivity { activity ->
        val fixtureConfiguration = variant.overrideConfiguration(
            base = activity.resources.configuration,
            fontScale = 1f,
        )
        value = activity.createConfigurationContext(fixtureConfiguration).getString(resourceId)
    }
    return checkNotNull(value)
}

private fun android.app.Instrumentation.captureStableWholeDisplay(): Bitmap {
    var previous: Bitmap? = null
    var stableTransitions = 0
    val deadline = SystemClock.uptimeMillis() + CAPTURE_STABLE_TIMEOUT_MILLIS
    try {
        while (SystemClock.uptimeMillis() < deadline) {
            awaitUiFrame()
            waitForIdleSync()
            val current = checkNotNull(uiAutomation.takeScreenshot())
            val prior = previous
            stableTransitions = if (prior != null && prior.applicationPixelsMatch(current)) {
                stableTransitions + 1
            } else {
                0
            }
            if (stableTransitions >= REQUIRED_STABLE_FRAME_TRANSITIONS) {
                prior?.recycle()
                previous = null
                return current
            }
            prior?.recycle()
            previous = current
        }
        throw AssertionError("Whole-display capture did not settle before timeout")
    } finally {
        previous?.recycle()
    }
}

private fun android.app.Instrumentation.awaitUiFrame() {
    val completed = CountDownLatch(1)
    runOnMainSync {
        Choreographer.getInstance().postFrameCallback { completed.countDown() }
    }
    assertTrue(
        "Timed out while waiting for the next UI frame",
        completed.await(UI_FRAME_TIMEOUT_SECONDS, TimeUnit.SECONDS),
    )
}

private fun Bitmap.applicationPixelsMatch(other: Bitmap): Boolean {
    if (width != other.width || height != other.height) return false
    val firstContentRow = visualFixtureStatusBarMaskHeight(height)
    val contentEnd = height - visualFixtureNavigationBarMaskHeight(height)
    val previousPixels = IntArray(width * CAPTURE_COMPARISON_CHUNK_ROWS)
    val currentPixels = IntArray(width * CAPTURE_COMPARISON_CHUNK_ROWS)
    var y = firstContentRow
    while (y < contentEnd) {
        val chunkHeight = minOf(CAPTURE_COMPARISON_CHUNK_ROWS, contentEnd - y)
        getPixels(previousPixels, 0, width, 0, y, width, chunkHeight)
        other.getPixels(currentPixels, 0, width, 0, y, width, chunkHeight)
        if (
            !applicationPixelsMatch(
                previous = previousPixels,
                current = currentPixels,
                width = width,
                height = chunkHeight,
                statusBarHeight = 0,
                navigationBarHeight = 0,
            )
        ) {
            return false
        }
        y += chunkHeight
    }
    return true
}

private fun Bitmap.sampledColorCount(): Int {
    val colors = mutableSetOf<Int>()
    val stepX = (width / 12).coerceAtLeast(1)
    val stepY = (height / 20).coerceAtLeast(1)
    var y = 0
    while (y < height) {
        var x = 0
        while (x < width) {
            colors += getPixel(x, y)
            x += stepX
        }
        y += stepY
    }
    return colors.size
}

private data class CaptureDeviceProfile(
    val width: Int,
    val height: Int,
    val densityDpi: Int,
    val apiLevel: Int,
)

private sealed interface GoldenComparisonProfile {
    data object ReviewedEmulator : GoldenComparisonProfile

    /**
     * Capture-only until the 28 physical-device images pass blind review and
     * are deliberately promoted into a dedicated asset directory.
     */
    data object PhysicalApi31PendingReview : GoldenComparisonProfile
}

private fun resolveGoldenComparisonProfile(profile: CaptureDeviceProfile): GoldenComparisonProfile = when (profile) {
    CaptureDeviceProfile(width = 1080, height = 2400, densityDpi = 420, apiLevel = 36) ->
        GoldenComparisonProfile.ReviewedEmulator
    CaptureDeviceProfile(width = 1440, height = 3200, densityDpi = 560, apiLevel = 31) ->
        GoldenComparisonProfile.PhysicalApi31PendingReview
    else -> throw AssertionError(
        "No reviewed or explicitly pending golden profile for " +
            "${profile.width}x${profile.height}, ${profile.densityDpi} dpi, API ${profile.apiLevel}",
    )
}

private fun Bitmap.assertMatchesReviewedGoldenOrCapturePending(assetName: String) {
    val instrumentation = InstrumentationRegistry.getInstrumentation()
    val profile = resolveGoldenComparisonProfile(
        CaptureDeviceProfile(
            width = width,
            height = height,
            densityDpi = instrumentation.targetContext.resources.configuration.densityDpi,
            apiLevel = Build.VERSION.SDK_INT,
        ),
    )
    when (profile) {
        GoldenComparisonProfile.ReviewedEmulator -> assertMatchesGolden(assetName, REVIEWED_EMULATOR_GOLDEN_DIRECTORY)
        GoldenComparisonProfile.PhysicalApi31PendingReview -> Unit
    }
}

private fun Bitmap.assertMatchesGolden(assetName: String, assetDirectory: String) {
    val instrumentation = InstrumentationRegistry.getInstrumentation()
    val expected = instrumentation.context.assets.open("$assetDirectory/$assetName").use { input ->
        checkNotNull(BitmapFactory.decodeStream(input)) { "Unable to decode golden $assetName" }
    }
    try {
        assertEquals("$assetName width", expected.width, width)
        assertEquals("$assetName height", expected.height, height)

        val actualPixels = IntArray(width * height)
        val expectedPixels = IntArray(width * height)
        getPixels(actualPixels, 0, width, 0, 0, width, height)
        expected.getPixels(expectedPixels, 0, width, 0, 0, width, height)

        var comparedPixels = 0L
        var differentPixels = 0L
        for (y in 0 until height) {
            val rowOffset = y * width
            for (x in 0 until width) {
                if (isDynamicSystemChromePixel(x, y, width, height)) continue
                comparedPixels += 1
                if (
                    maximumChannelDifference(actualPixels[rowOffset + x], expectedPixels[rowOffset + x]) >
                    MAX_CHANNEL_DIFFERENCE
                ) {
                    differentPixels += 1
                }
            }
        }
        val differenceRatio = differentPixels.toDouble() / comparedPixels.toDouble()
        assertTrue(
            "$assetName differs in ${"%.4f".format(differenceRatio * 100)}% of compared pixels; " +
                "limit is ${MAX_DIFFERENT_PIXEL_RATIO * 100}%",
            differenceRatio <= MAX_DIFFERENT_PIXEL_RATIO,
        )
    } finally {
        expected.recycle()
    }
}

private fun maximumChannelDifference(actual: Int, expected: Int): Int =
    maxOf(
        abs(((actual shr 24) and 0xff) - ((expected shr 24) and 0xff)),
        abs(((actual shr 16) and 0xff) - ((expected shr 16) and 0xff)),
        abs(((actual shr 8) and 0xff) - ((expected shr 8) and 0xff)),
        abs((actual and 0xff) - (expected and 0xff)),
    )

private const val EXPECTED_CAPTURE_COUNT = 28
private const val EXPECTED_LARGE_FONT_CAPTURE_COUNT = 8
private const val CAPTURE_READY_TIMEOUT_MILLIS = 5_000L
private const val CAPTURE_STABLE_TIMEOUT_MILLIS = 5_000L
private const val UI_FRAME_TIMEOUT_SECONDS = 1L
private const val REQUIRED_STABLE_FRAME_TRANSITIONS = 2
private const val CAPTURE_COMPARISON_CHUNK_ROWS = 128
private const val DEFAULT_FONT_SCALE = 1f
private const val REVIEWED_EMULATOR_GOLDEN_DIRECTORY = "warm-page-goldens"
private const val MAX_CHANNEL_DIFFERENCE = 8
private const val MAX_DIFFERENT_PIXEL_RATIO = 0.005
