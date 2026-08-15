package com.ermao.library.features.reader

import android.content.Context
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.navigator.epub.EpubNavigatorFragment

@RunWith(AndroidJUnit4::class)
class ReaderMobiInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val sourceId = "instrumented-mobi-${UUID.randomUUID()}"
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val progressStore = AndroidReaderProgressStore(context)
    private lateinit var source: com.ermao.library.shared.modules.reader.LocalReaderSource

    @Before
    fun publishMobiWithoutEpubConversion() = runBlocking {
        source = instrumentation.context.assets.open("01-basic-mobi6.mobi").use { input ->
            publicationStore.publishLocalPublication(
                sourceId = sourceId,
                displayTitle = "MOBI product fixture",
                input = input,
                sourceFormat = ReaderSourceFormat.Mobi,
                volumeId = "mobi-volume",
            )
        }
    }

    @After
    fun removeReaderArtifacts() = runBlocking {
        progressStore.delete(sourceId)
        publicationStore.delete(sourceId)
    }

    @Test
    fun opensMobiThroughTheProductReaderAndKeepsTheOriginalContainer() {
        assertEquals(ReaderFormat.Mobi, source.format)
        assertEquals(ReaderSourceFormat.Mobi, source.sourceFormat)
        val stored = publicationStore.resolve(source)
        assertEquals("mobi", stored.extension)
        assertFalse(stored.resolveSibling("${stored.nameWithoutExtension}.epub").exists())

        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            val deadline = SystemClock.uptimeMillis() + TEST_TIMEOUT_MILLIS
            var ready = false
            while (SystemClock.uptimeMillis() < deadline) {
                instrumentation.waitForIdleSync()
                val readerReady = AtomicBoolean(false)
                scenario.onActivity { activity ->
                    readerReady.set(
                        activity.controllerForTesting?.tableOfContents?.isNotEmpty() == true &&
                            activity.supportFragmentManager.fragments
                                .filterIsInstance<EpubNavigatorFragment>()
                                .singleOrNull()?.view != null,
                    )
                }
                if (readerReady.get()) {
                    ready = true
                    break
                }
                SystemClock.sleep(POLL_MILLIS)
            }
            if (!ready) throw AssertionError("Timed out waiting for the MOBI product Reader")

            scenario.onActivity { activity ->
                checkNotNull(activity.controllerForTesting).updatePreferences(
                    ReaderPreferences(epub = ReaderEpubPreferences(fontSize = 24)),
                )
            }
            val preferenceDeadline = SystemClock.uptimeMillis() + TEST_TIMEOUT_MILLIS
            while (SystemClock.uptimeMillis() < preferenceDeadline) {
                instrumentation.waitForIdleSync()
                val applied = AtomicBoolean(false)
                scenario.onActivity { activity ->
                    applied.set(
                        activity.supportFragmentManager.fragments
                            .filterIsInstance<EpubNavigatorFragment>()
                            .singleOrNull()
                            ?.settings
                            ?.value
                            ?.fontSize
                            ?.let { abs(it - (24.0 / 18.0)) < 0.01 } == true,
                    )
                }
                if (applied.get()) return@use
                SystemClock.sleep(POLL_MILLIS)
            }
            throw AssertionError("Timed out waiting for MOBI reader preferences")
        }
    }

    private companion object {
        const val TEST_TIMEOUT_MILLIS = 20_000L
        const val POLL_MILLIS = 100L
    }
}
