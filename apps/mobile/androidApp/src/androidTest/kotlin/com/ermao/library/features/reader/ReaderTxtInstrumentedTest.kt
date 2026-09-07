package com.ermao.library.features.reader

import android.content.Context
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.TxtReadiumPublicationFactory
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderCommandCompleted
import com.ermao.library.shared.modules.reader.ReaderNavigationCompleted
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import java.io.ByteArrayInputStream
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.services.positions

@OptIn(ExperimentalReadiumApi::class)
@RunWith(AndroidJUnit4::class)
class ReaderTxtInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val sourceId = "txt-reader-${UUID.randomUUID()}"
    private val publicationStore = AndroidReaderPublicationStore(context)
    private lateinit var source: com.ermao.library.shared.modules.reader.LocalReaderSource

    @Before
    fun publishTxt() = runBlocking {
        source = ByteArrayInputStream(
            "第一章 开始\r\n正文 & <内容>\r\n\r\nChapter 2: Next\r\nSecond chapter".toByteArray(),
        ).use { input ->
            publicationStore.publishLocalPublication(
                resourceId = sourceId,
                displayTitle = "TXT Book",
                input = input,
                sourceFormat = ReaderSourceFormat.Txt,
            )
        }
    }

    @After
    fun removeArtifacts() = runBlocking {
        if (this@ReaderTxtInstrumentedTest::source.isInitialized) {
            deleteLocalReaderV5Position(context, source)
        }
        publicationStore.delete(sourceId)
    }

    @Test
    fun publicationProvidesProgressTargetsAcrossChapters() = runBlocking {
        val publication = TxtReadiumPublicationFactory().open(publicationStore.resolve(source), "Reading")
        try {
            val positions = publication.positions()
            assertTrue(positions.size >= 2)
            assertEquals(setOf("text/chapter-0001.xhtml", "text/chapter-0002.xhtml"), positions.map { it.href.toString() }.toSet())
            assertNotNull(positions.last().locations.totalProgression)
        } finally {
            publication.close()
        }
    }

    @Test
    fun opensRendersNavigatesAndCapturesExactLocationWithEpubNavigator() {
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitUntil(scenario, "TXT reader") {
                it.controllerForTesting != null && it.navigatorOrNull()?.view != null
            }
            val controller = AtomicReference<com.ermao.library.features.reader.application.ReaderScreenController>()
                .also { reference -> scenario.onActivity { reference.set(checkNotNull(it.controllerForTesting)) } }
                .get()
            val tableOfContents = runBlocking { controller.loadTableOfContents() }
            scenario.onActivity { activity ->
                assertEquals(2, tableOfContents.size)
                assertTrue(checkNotNull(activity.controllerForTesting).goTo(tableOfContents.last().location))
            }
            waitUntil(scenario, "second TXT chapter") {
                (it.controllerForTesting?.currentLocation?.value as? ReflowReaderLocation)
                    ?.resourceKey == "text/chapter-0002.xhtml"
            }
            assertTrue(renderedText(scenario).contains("Second chapter"))
            scenario.onActivity { activity ->
                val location = activity.controllerForTesting?.currentLocation?.value as? ReflowReaderLocation
                assertNotNull(location?.resourceKey)
                checkNotNull(activity.controllerForTesting).updatePreferences(
                    ReaderPreferences(epub = ReaderEpubPreferences(fontSize = 23)),
                )
            }
            waitUntil(scenario, "TXT reader preferences") { activity ->
                activity.navigatorOrNull()?.settings?.value?.fontSize?.let {
                    abs(it - (23.0 / 16.0)) < 0.01
                } == true
            }
        }
    }

    @Test
    fun ordinaryTocSelectionFromSecondChapterCompletesAtLongFirstChapterHeading() {
        withLongTxtReader { controller, navigator ->
            val entries = runBlocking { controller.loadTableOfContents() }
            assertEquals(2, entries.size)
            val first = entries.first()
            val second = entries.last()
            runBlocking {
                withContext(Dispatchers.Main) {
                    assertTrue(controller.goTo(second.location))
                }
            }
            val secondVisible = awaitSettledVisibleLocator(navigator, "text/chapter-0002.xhtml", 18)
            assertEquals(second.title, secondVisible.text.highlight?.trim())

            // Exercise the ordinary TOC command, including its completion verification.
            val result = runBlocking {
                withTimeout(20_000L) {
                    withContext(Dispatchers.Main) { controller.navigateTo(first) }
                }
            }
            val firstVisible = awaitSettledVisibleLocator(navigator, "text/chapter-0001.xhtml", 18)
            assertTrue("Backward TOC selection did not complete: $result; visible=$firstVisible", result is ReaderNavigationCompleted)
            assertEquals(
                "TOC must show the heading, not paragraphs at the chapter end",
                first.title,
                firstVisible.text.highlight?.trim(),
            )
        }
    }

    @Test
    fun changingFontFrom18To19InPlaceRetainsTheVisibleNumberedParagraph() {
        withLongTxtReader { controller, navigator ->
            val start = awaitSettledVisibleLocator(navigator, "text/chapter-0001.xhtml", 18)
            runBlocking {
                withContext(Dispatchers.Main) {
                    // Set up a late passage with the real SDK and the fixture's authored block ID.
                    assertTrue(navigator.go(
                        start.copy(
                            locations = Locator.Locations(fragments = listOf("block-001137")),
                            text = Locator.Text(),
                        ),
                        animated = false,
                    ))
                }
            }
            val before = awaitSettledVisibleLocator(navigator, "text/chapter-0001.xhtml", 18)
            val engineBefore = navigator.currentLocator.value
            val paragraph = requireNotNull(before.text.highlight).trim()
            val number = Regex("^长章段落 (\\d{4}):").find(paragraph)
                ?.groupValues?.get(1)?.toIntOrNull()
            assertTrue("Expected a visible late numbered paragraph, got: $paragraph", number != null && number in 1100..1200)
            val selector = requireNotNull(before.locations["cssSelector"] as? String)
            val selectionCollapsed = runBlocking { withContext(Dispatchers.Main) {
                navigator.evaluateJavascript("getSelection().isCollapsed") == "true"
            } }
            assertTrue("Ordinary appearance changes start after leaving text selection", selectionCollapsed)

            // A single ordinary preference submission; do not reopen or navigate afterwards.
            val result = runBlocking {
                withContext(Dispatchers.Main) {
                    val preferences = controller.preferences.value
                    controller.applyPreferences(preferences.copy(epub = preferences.epub.copy(fontSize = 19)))
                }
            }
            assertEquals(ReaderCommandCompleted, result)
            val after = awaitSettledVisibleLocator(navigator, "text/chapter-0001.xhtml", 19)
            val retained = runBlocking {
                withContext(Dispatchers.Main) {
                    // Repagination may put an earlier block at the page edge. The captured
                    // semantic paragraph must still intersect the viewport, not just exist in DOM.
                    navigator.evaluateJavascript("""
                        (() => {
                          const paragraph = document.querySelector(${JSONObject.quote(selector)});
                          return paragraph && paragraph.textContent.trim() === ${JSONObject.quote(paragraph)} &&
                            [...paragraph.getClientRects()].some(rect =>
                              rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
                              rect.left < window.innerWidth && rect.top < window.innerHeight);
                        })()
                    """.trimIndent()) == "true"
                }
            }
            assertTrue(
                "Font reflow lost visible paragraph $number; first visible afterwards: ${after.text.highlight}; SDK before=$engineBefore; SDK after=${navigator.currentLocator.value}",
                retained,
            )
        }
    }

    private fun withLongTxtReader(assertions: (ReaderScreenController, EpubNavigatorFragment) -> Unit) {
        val text = buildString {
            append("第 1 章 长章起点\r\n\r\n")
            for (number in 1..1200) {
                append("长章段落 ${number.toString().padStart(4, '0')}: 中文与 English 混排，目录跳转应找到真实章节位置，原文件保持不变。\r\n\r\n")
            }
            append("第 2 章 终点核对\r\n\r\n末章正文。\r\n")
        }
        runBlocking {
            // Replace only this test's UUID-scoped publication; @After removes it and its progress.
            ByteArrayInputStream(byteArrayOf(0xFE.toByte(), 0xFF.toByte()) + text.toByteArray(Charsets.UTF_16BE)).use { input ->
                source = publicationStore.publishLocalPublication(
                    resourceId = sourceId,
                    displayTitle = "TXT long UTF-16BE regression",
                    input = input,
                    sourceFormat = ReaderSourceFormat.Txt,
                )
            }
        }
        // The existing local-source launch supplies no account preferences store. Preferences
        // belong to this Activity session and disappear on close; never reset host user settings.
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitUntil(scenario, "long TXT reader") {
                it.controllerForTesting != null && it.navigatorOrNull()?.view != null
            }
            val controller = AtomicReference<ReaderScreenController>()
            val navigator = AtomicReference<EpubNavigatorFragment>()
            scenario.onActivity {
                controller.set(checkNotNull(it.controllerForTesting))
                navigator.set(checkNotNull(it.navigatorOrNull()))
            }
            runBlocking {
                withContext(Dispatchers.Main) {
                    assertEquals(
                        ReaderCommandCompleted,
                        controller.get().applyPreferences(ReaderPreferences(epub = ReaderEpubPreferences(fontSize = 18))),
                    )
                }
            }
            awaitSettledVisibleLocator(navigator.get(), "text/chapter-0001.xhtml", 18)
            assertions(controller.get(), navigator.get())
        }
    }

    private fun awaitSettledVisibleLocator(navigator: EpubNavigatorFragment, href: String, fontSize: Int): Locator {
        val deadline = SystemClock.uptimeMillis() + 20_000L
        var previous: Locator? = null
        var stableSince = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() < deadline) {
            instrumentation.waitForIdleSync()
            val visible = runBlocking {
                withTimeout(5_000L) {
                    withContext(Dispatchers.Main) {
                        // Settings emission precedes CSS application. Check computed typography
                        // and font loading too, then sample the SDK's visible block, not body text.
                        val styled = navigator.evaluateJavascript("""
                            (() => {
                              const paragraph = document.querySelector('p');
                              return paragraph && document.fonts.status === 'loaded' &&
                                Math.abs(parseFloat(getComputedStyle(paragraph).fontSize) - $fontSize) < 0.6;
                            })()
                        """.trimIndent()) == "true"
                        if (styled && abs(navigator.settings.value.fontSize - fontSize / 16.0) < 0.01) {
                            navigator.firstVisibleElementLocator()
                        } else null
                    }
                }
            }?.takeIf { it.href.toString() == href && !it.text.highlight.isNullOrBlank() }
            val now = SystemClock.uptimeMillis()
            if (visible == null || visible != previous) stableSince = now
            if (visible != null && now - stableSince >= 1_000L) return visible
            previous = visible
            SystemClock.sleep(100L)
        }
        throw AssertionError("Visible TXT locator did not settle at $href / ${fontSize}px; last=$previous")
    }

    private fun waitUntil(
        scenario: ActivityScenario<ReaderActivity>,
        label: String,
        condition: (ReaderActivity) -> Boolean,
    ) {
        val deadline = SystemClock.uptimeMillis() + 20_000L
        while (SystemClock.uptimeMillis() < deadline) {
            instrumentation.waitForIdleSync()
            val matched = AtomicReference(false)
            scenario.onActivity { matched.set(condition(it)) }
            if (matched.get()) return
            SystemClock.sleep(100L)
        }
        throw AssertionError("Timed out waiting for $label")
    }

    private fun renderedText(scenario: ActivityScenario<ReaderActivity>): String {
        val navigator = AtomicReference<EpubNavigatorFragment>().also { result ->
            scenario.onActivity { result.set(checkNotNull(it.navigatorOrNull())) }
        }.get()
        return runBlocking {
            withContext(Dispatchers.Main) {
                navigator.evaluateJavascript("document.body ? document.body.innerText : ''").orEmpty()
            }
        }
    }

    private fun ReaderActivity.navigatorOrNull(): EpubNavigatorFragment? =
        supportFragmentManager.fragments.filterIsInstance<EpubNavigatorFragment>().singleOrNull()
}
