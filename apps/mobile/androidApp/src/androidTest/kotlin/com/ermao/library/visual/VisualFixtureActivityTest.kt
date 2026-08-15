package com.ermao.library.visual

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import android.view.PixelCopy
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
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
    fun sevenScenariosRenderInBothLocalesAndAppearances() {
        val outputDirectory = visualFixtureOutputDirectory()
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
        val captures = largeFontFixtureVariants.map { expected ->
            captureVariant(
                variant = expected,
                outputDirectory = outputDirectory,
                outputName = "${expected.scenario.wireValue}-${expected.locale.wireValue}-fontScale-2.png",
                fontScale = 2f,
            )
        }
        assertEquals(EXPECTED_LARGE_FONT_CAPTURE_COUNT, captures.size)
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
            revealRequestedOverlay(variant, scenario)
            instrumentation.movePointerToSystemBar()
            composeRule.waitForIdle()
            instrumentation.waitForIdleSync()
            val screenshot = if (variant.scenario in visualFixtureOverlayScenarios) {
                checkNotNull(instrumentation.uiAutomation.takeScreenshot())
            } else {
                scenario.captureWindow()
            }
            assertTrue(screenshot.width > 0)
            assertTrue(screenshot.height > 0)
            assertTrue("$outputName rendered as a single-color frame", screenshot.sampledColorCount() > 1)
            val destination = File(outputDirectory, outputName)
            FileOutputStream(destination).use { output ->
                assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG, 100, output))
            }
            assertTrue(destination.isFile)
            assertTrue(destination.length() > 0)
            if (fontScale == DEFAULT_FONT_SCALE) {
                screenshot.assertMatchesGolden(outputName)
            }
            screenshot.recycle()
            destination
        }
    }

    private fun revealRequestedOverlay(
        variant: VisualFixtureVariant,
        scenario: ActivityScenario<VisualFixtureActivity>,
    ) {
        when (variant.scenario) {
            VisualFixtureScenario.LibraryFilter -> {
                val filterTitle = scenario.localizedString(R.string.library_filter_title)
                composeRule.onNodeWithText(filterTitle).assertIsDisplayed()
            }
            VisualFixtureScenario.WorkActions -> {
                composeRule.onNodeWithTag("work-identity").performScrollTo()
                val moreActions = scenario.localizedString(R.string.work_more_actions)
                composeRule.onNodeWithContentDescription(moreActions).performClick()
                composeRule.waitForIdle()
                val actionsTitle = scenario.localizedString(R.string.work_actions_title)
                composeRule.onNodeWithText(actionsTitle).assertIsDisplayed()
            }
            VisualFixtureScenario.WorkAbout,
            VisualFixtureScenario.WorkVolumes,
            VisualFixtureScenario.WorkSingleEbook,
            -> composeRule.onNodeWithTag("work-identity").performScrollTo()
            else -> Unit
        }
    }
}

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
        VisualFixtureScenario.WorkAbout,
        VisualFixtureScenario.WorkVolumes,
        VisualFixtureScenario.WorkSingleEbook,
        VisualFixtureScenario.HomeDefault,
        VisualFixtureScenario.LibraryWorks,
        // Modal fixtures run last so their exit transitions cannot cover the
        // first frame of a subsequent full-screen golden.
        VisualFixtureScenario.LibraryFilter,
        VisualFixtureScenario.WorkActions,
    )

private val visualFixtureOverlayScenarios: Set<VisualFixtureScenario> =
    setOf(VisualFixtureScenario.LibraryFilter, VisualFixtureScenario.WorkActions)

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
        VisualFixtureScenario.LibraryWorks,
        VisualFixtureScenario.WorkVolumes,
    ).flatMap { scenario ->
        VisualFixtureLocale.entries.map { locale ->
            VisualFixtureVariant(scenario, locale, VisualFixtureAppearance.Light)
        }
    }

private fun ActivityScenario<VisualFixtureActivity>.localizedString(resourceId: Int): String {
    var value: String? = null
    onActivity { activity -> value = activity.getString(resourceId) }
    return checkNotNull(value)
}

private fun ActivityScenario<VisualFixtureActivity>.captureWindow(): Bitmap {
    val completed = CountDownLatch(1)
    var capture: Bitmap? = null
    var result = PixelCopy.ERROR_UNKNOWN
    onActivity { activity ->
        val decorView = activity.window.decorView
        val target = Bitmap.createBitmap(decorView.width, decorView.height, Bitmap.Config.ARGB_8888)
        capture = target
        PixelCopy.request(
            activity.window,
            target,
            { copyResult ->
                result = copyResult
                completed.countDown()
            },
            Handler(Looper.getMainLooper()),
        )
    }
    assertTrue("PixelCopy timed out", completed.await(PIXEL_COPY_TIMEOUT_SECONDS, TimeUnit.SECONDS))
    assertEquals("PixelCopy failed", PixelCopy.SUCCESS, result)
    return checkNotNull(capture)
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

private fun Bitmap.assertMatchesGolden(assetName: String) {
    val instrumentation = InstrumentationRegistry.getInstrumentation()
    val expected = instrumentation.context.assets.open("warm-page-goldens/$assetName").use { input ->
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
                if (isDynamicStatusIconPixel(x, y, width)) continue
                comparedPixels += 1
                if (maximumChannelDifference(actualPixels[rowOffset + x], expectedPixels[rowOffset + x]) > MAX_CHANNEL_DIFFERENCE) {
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

private fun isDynamicStatusIconPixel(x: Int, y: Int, width: Int): Boolean =
    y < STATUS_BAR_MASK_HEIGHT_PX &&
        (x < STATUS_BAR_SIDE_MASK_WIDTH_PX || x >= width - STATUS_BAR_SIDE_MASK_WIDTH_PX)

private fun maximumChannelDifference(actual: Int, expected: Int): Int =
    maxOf(
        abs(((actual shr 24) and 0xff) - ((expected shr 24) and 0xff)),
        abs(((actual shr 16) and 0xff) - ((expected shr 16) and 0xff)),
        abs(((actual shr 8) and 0xff) - ((expected shr 8) and 0xff)),
        abs((actual and 0xff) - (expected and 0xff)),
    )

private const val EXPECTED_CAPTURE_COUNT = 28
private const val EXPECTED_LARGE_FONT_CAPTURE_COUNT = 6
private const val CAPTURE_READY_TIMEOUT_MILLIS = 5_000L
private const val PIXEL_COPY_TIMEOUT_SECONDS = 5L
private const val DEFAULT_FONT_SCALE = 1f
private const val MAX_CHANNEL_DIFFERENCE = 8
private const val MAX_DIFFERENT_PIXEL_RATIO = 0.005
private const val STATUS_BAR_MASK_HEIGHT_PX = 128
private const val STATUS_BAR_SIDE_MASK_WIDTH_PX = 360
