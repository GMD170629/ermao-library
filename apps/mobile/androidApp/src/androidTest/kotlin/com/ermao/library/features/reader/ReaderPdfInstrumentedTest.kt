package com.ermao.library.features.reader

import android.content.Context
import android.os.SystemClock
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidPdfiumFeatureFlags
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPdfFit
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.adapter.pdfium.navigator.PdfiumNavigatorFragment
import org.readium.r2.navigator.preferences.Fit
import org.readium.r2.shared.ExperimentalReadiumApi

@OptIn(ExperimentalReadiumApi::class)
@RunWith(AndroidJUnit4::class)
class ReaderPdfInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val sourceId = "pdf-reader-${UUID.randomUUID()}"
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val progressStore = AndroidReaderProgressStore(context)
    private lateinit var source: com.ermao.library.shared.modules.reader.LocalReaderSource

    @Before
    fun publishRealPdf() = runBlocking {
        source = instrumentation.context.assets.open("reading-notes.pdf").use { input ->
            publicationStore.publishLocalPublication(
                resourceId = sourceId,
                displayTitle = "Reading notes",
                input = input,
                sourceFormat = ReaderSourceFormat.Pdf,
            )
        }
    }

    @After
    fun removeArtifacts() = runBlocking {
        progressStore.delete(sourceId)
        publicationStore.delete(sourceId)
    }

    @Test
    fun nativePdfiumRangeRolloutIsAvailable() {
        assertEquals(true, AndroidPdfiumFeatureFlags.NATIVE_PDFIUM_RANGE_V1)
    }

    @Test
    fun parserPageCountWinsWhenServerMetadataDisagrees() {
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source, pageCount = 99)).use { scenario ->
            waitUntil(scenario, "PDF navigator and canonical first page") { activity ->
                activity.pdfNavigatorOrNull()?.view != null &&
                    (activity.controllerForTesting?.currentLocation?.value as? PdfReaderLocation)?.let { location ->
                        location.pageIndex == 0 && location.pageProgression == 0.0
                    } == true
            }

            scenario.onActivity { activity ->
                val controller = checkNotNull(activity.controllerForTesting)
                controller.updatePreferences(
                    controller.preferences.value.copy(
                        pdf = controller.preferences.value.pdf.copy(fit = ReaderPdfFit.Width),
                    ),
                )
            }
            waitUntil(scenario, "PDF width fit preference") { activity ->
                activity.pdfNavigatorOrNull()?.settings?.value?.fit == Fit.WIDTH
            }

            runBlocking { controller(scenario).flush() }
            val persisted = runBlocking { progressStore.load(sourceId) }
            val persistedLocation = persisted?.location as? PdfReaderLocation
            assertNotNull(persistedLocation)
            assertEquals(0, persistedLocation?.pageIndex)
            assertEquals(0.0, persistedLocation?.pageProgression ?: -1.0, 0.0)

            scenario.moveToState(Lifecycle.State.CREATED)
            scenario.recreate()
            scenario.moveToState(Lifecycle.State.RESUMED)
            waitUntil(scenario, "recreated PDF exact location recapture") { activity ->
                (activity.controllerForTesting?.currentLocation?.value as? PdfReaderLocation)?.let { recaptured ->
                    recaptured.pageIndex == persistedLocation?.pageIndex &&
                        recaptured.pageProgression == 0.0 &&
                        activity.controllerForTesting?.restoreWarning?.value == null
                } == true
            }
        }

        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { reopened ->
            waitUntil(reopened, "new PDF session exact restoration") { activity ->
                (activity.controllerForTesting?.currentLocation?.value as? PdfReaderLocation)?.let { restored ->
                    restored.pageIndex == 0 && restored.pageProgression == 0.0
                } == true
            }
        }
    }

    private fun waitUntil(
        scenario: ActivityScenario<ReaderActivity>,
        label: String,
        condition: (ReaderActivity) -> Boolean,
    ) {
        val deadline = SystemClock.uptimeMillis() + 30_000L
        while (SystemClock.uptimeMillis() < deadline) {
            instrumentation.waitForIdleSync()
            if (condition(activity(scenario))) return
            SystemClock.sleep(100L)
        }
        throw AssertionError("Timed out waiting for $label")
    }

    private fun controller(scenario: ActivityScenario<ReaderActivity>) =
        checkNotNull(activity(scenario).controllerForTesting)

    private fun activity(scenario: ActivityScenario<ReaderActivity>): ReaderActivity =
        AtomicReference<ReaderActivity>().also { result -> scenario.onActivity(result::set) }.get()

    private fun ReaderActivity.pdfNavigatorOrNull(): PdfiumNavigatorFragment? =
        supportFragmentManager.fragments.filterIsInstance<PdfiumNavigatorFragment>().singleOrNull()
}
