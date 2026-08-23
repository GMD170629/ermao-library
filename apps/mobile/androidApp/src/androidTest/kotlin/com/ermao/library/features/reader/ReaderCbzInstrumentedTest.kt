package com.ermao.library.features.reader

import android.content.Context
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.navigator.image.ImageNavigatorFragment

@RunWith(AndroidJUnit4::class)
class ReaderCbzInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val testContext: Context = instrumentation.context
    private val sourceId = "cbz-reader-${UUID.randomUUID()}"
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val progressStore = AndroidReaderProgressStore(context)
    private val mismatchedServerHints = listOf(
        ReaderComicPage(0, "server/not-local.png", "image/png", title = "Server title"),
    )
    private lateinit var source: com.ermao.library.shared.modules.reader.LocalReaderSource

    @Before
    fun publishCbz() = runBlocking {
        source = ByteArrayInputStream(buildArchive()).use { input ->
            publicationStore.publishLocalPublication(
                resourceId = sourceId,
                displayTitle = "CBZ Book",
                input = input,
                sourceFormat = ReaderSourceFormat.Cbz,
            )
        }
    }

    @After
    fun removeArtifacts() = runBlocking {
        progressStore.delete(sourceId)
        publicationStore.delete(sourceId)
    }

    @Test
    fun localArchiveDefinesPageOrderEvenWhenServerHintsDisagree() {
        ActivityScenario.launch<ReaderActivity>(
            ReaderActivity.createIntent(context, source, mismatchedServerHints),
        ).use { scenario ->
            waitUntil(scenario, "CBZ first page") {
                it.imageNavigatorOrNull()?.view != null &&
                    (it.controllerForTesting?.currentLocation?.value as? ComicReaderLocation)?.pageIndex == 0
            }
            scenario.onActivity { activity -> assertTrue(checkNotNull(activity.controllerForTesting).goNext()) }
            waitUntil(scenario, "CBZ second page") {
                (it.controllerForTesting?.currentLocation?.value as? ComicReaderLocation)?.let { location ->
                    location.pageIndex == 1 && location.resourceHref == "images/page-002.png"
                } == true
            }
            runBlocking { scenarioActivity(scenario).controllerForTesting?.flush() }
        }

        val persisted = runBlocking { progressStore.load(sourceId) }
        assertEquals(1, (persisted?.location as? ComicReaderLocation)?.pageIndex)
        assertEquals("images/page-002.png", (persisted?.location as? ComicReaderLocation)?.resourceHref)

        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            waitUntil(scenario, "restored CBZ second page") {
                (it.controllerForTesting?.currentLocation?.value as? ComicReaderLocation)?.let { location ->
                    location.pageIndex == 1 && location.resourceHref == "images/page-002.png"
                } == true
            }
        }
    }

    private fun buildArchive(): ByteArray = ByteArrayOutputStream().use { output ->
        ZipOutputStream(output).use { archive ->
            listOf("page-001.png", "page-002.png").forEach { name ->
                archive.putNextEntry(ZipEntry("images/$name"))
                testContext.assets.open("starship-pages/$name").use { it.copyTo(archive) }
                archive.closeEntry()
            }
        }
        output.toByteArray()
    }

    private fun waitUntil(
        scenario: ActivityScenario<ReaderActivity>,
        label: String,
        condition: (ReaderActivity) -> Boolean,
    ) {
        val deadline = SystemClock.uptimeMillis() + 20_000L
        while (SystemClock.uptimeMillis() < deadline) {
            instrumentation.waitForIdleSync()
            if (condition(scenarioActivity(scenario))) return
            SystemClock.sleep(100L)
        }
        throw AssertionError("Timed out waiting for $label")
    }

    private fun scenarioActivity(scenario: ActivityScenario<ReaderActivity>): ReaderActivity =
        AtomicReference<ReaderActivity>().also { result -> scenario.onActivity(result::set) }.get()

    private fun ReaderActivity.imageNavigatorOrNull(): ImageNavigatorFragment? =
        supportFragmentManager.fragments.filterIsInstance<ImageNavigatorFragment>().singleOrNull()
}
