package com.ermao.library.features.reader

import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.content.Context
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.lifecycle.Lifecycle
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.EngineLocator
import com.ermao.library.shared.modules.reader.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.ReaderEngine
import com.ermao.library.shared.modules.reader.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderAppearancePreferences
import com.ermao.library.shared.modules.reader.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderSpreadMode
import com.ermao.library.shared.modules.reader.ReaderTheme
import com.ermao.library.shared.modules.reader.ReadiumLocatorEnvelope
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.TextQuote
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.preferences.Theme
import org.readium.r2.shared.ExperimentalReadiumApi

@OptIn(ExperimentalReadiumApi::class)
@RunWith(AndroidJUnit4::class)
class ReaderEpubInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val sourceId = "instrumented-reader-${UUID.randomUUID()}"
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val progressStore = AndroidReaderProgressStore(context)
    private lateinit var source: com.ermao.library.shared.modules.reader.LocalReaderSource

    @Before
    fun publishRealEpub() = runBlocking {
        source = instrumentation.context.assets.open("reader-v2.epub").use { input ->
            publicationStore.publishLocalEpub(
                resourceId = sourceId,
                displayTitle = "Reader v2 fixture",
                input = input,
            )
        }
    }

    @After
    fun removeReaderArtifacts() = runBlocking {
        progressStore.delete(sourceId)
        publicationStore.delete(sourceId)
    }

    @Test
    fun opensRendersNavigatesAndAppliesPreferencesWithReadium() {
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitForReader(scenario)
            scenario.onActivity { activity -> assertFalse(activity.controlsVisibleForTesting) }
            val initial = currentLocation(scenario)
            assertNotNull(initial.engineLocator)
            assertTrue(renderedText(scenario).contains("第一章"))
            val tableOfContents = runBlocking { controller(scenario).loadTableOfContents() }

            scenario.onActivity { activity ->
                val controller = checkNotNull(activity.controllerForTesting)
                assertTrue(tableOfContents.isNotEmpty())
                val secondChapter = tableOfContents.last().location
                assertTrue(controller.goTo(secondChapter))
            }
            waitUntil(scenario, "second chapter location") {
                (it.controllerForTesting?.currentLocation?.value as? ReflowReaderLocation)
                    ?.resourceKey
                    ?.contains("chapter2.xhtml") == true
            }
            waitUntilValue("second chapter rendering") { renderedText(scenario).contains("第二章") }

            val previous = currentLocation(scenario)
            scenario.onActivity { activity ->
                assertTrue(checkNotNull(activity.controllerForTesting).goPrevious())
            }
            waitUntil(scenario, "previous navigation") { currentLocationOrNull(it) != previous }
            scenario.onActivity { activity ->
                checkNotNull(activity.controllerForTesting).updatePreferences(
                    ReaderPreferences(
                        appearance = ReaderAppearancePreferences(theme = ReaderTheme.Night),
                        epub = ReaderEpubPreferences(
                            fontSize = 25,
                            lineHeight = 1.6,
                            fontFamily = com.ermao.library.shared.modules.reader.ReaderFontFamily.Songti,
                        ),
                    ),
                )
            }
            waitUntil(scenario, "Readium preferences") { activity ->
                val navigator = activity.navigatorOrNull() ?: return@waitUntil false
                abs(navigator.settings.value.fontSize - (25.0 / 16.0)) < 0.01 &&
                    navigator.settings.value.theme == Theme.DARK &&
                    abs((navigator.settings.value.lineHeight ?: 0.0) - 1.6) < 0.01
            }
            try {
                waitUntilValue("computed WebView preferences") {
                    evaluateJavascript(
                        scenario,
                        """
                        (() => {
                          const viewport = document.querySelector('meta[name="viewport"]');
                          const paragraph = document.querySelector('p');
                          if (!viewport || !paragraph) return false;
                          const rootStyle = getComputedStyle(document.documentElement);
                          const paragraphStyle = getComputedStyle(paragraph);
                          const fontSize = Number.parseFloat(paragraphStyle.fontSize);
                          const lineHeight = Number.parseFloat(paragraphStyle.lineHeight);
                          return viewport.content.includes('width=device-width') &&
                            window.innerWidth < 600 &&
                            Math.abs(fontSize - 25) < 0.6 &&
                            Math.abs(lineHeight / fontSize - 1.6) < 0.05 &&
                            paragraphStyle.fontFamily.includes('Shuku Songti') &&
                            [...document.fonts].some(font => font.family.includes('Shuku Songti') && font.status === 'loaded') &&
                            paragraphStyle.color === 'rgb(226, 232, 240)' &&
                            rootStyle.backgroundColor === 'rgb(15, 23, 42)';
                        })()
                        """.trimIndent(),
                    ) == "true"
                }
            } catch (error: AssertionError) {
                val diagnostic = evaluateJavascript(
                    scenario,
                    """
                        (() => {
                          const viewport = document.querySelector('meta[name="viewport"]');
                          const paragraph = document.querySelector('p');
                          const rootStyle = getComputedStyle(document.documentElement);
                          const paragraphStyle = paragraph && getComputedStyle(paragraph);
                          return JSON.stringify({
                            viewport: viewport && viewport.content,
                            innerWidth: window.innerWidth,
                            fontSize: paragraphStyle && paragraphStyle.fontSize,
                            lineHeight: paragraphStyle && paragraphStyle.lineHeight,
                            fontFamily: paragraphStyle && paragraphStyle.fontFamily,
                            fonts: [...document.fonts].map(font => ({family: font.family, status: font.status})),
                            baseUri: document.baseURI,
                            fontFaces: [...document.styleSheets].flatMap(sheet => {
                              try { return [...sheet.cssRules].filter(rule => rule.type === CSSRule.FONT_FACE_RULE).map(rule => rule.cssText); }
                              catch (_) { return []; }
                            }),
                            fontResources: performance.getEntriesByType('resource')
                              .map(entry => entry.name)
                              .filter(name => name.includes('/fonts/')),
                            color: paragraphStyle && paragraphStyle.color,
                            backgroundColor: rootStyle.backgroundColor
                          });
                        })()
                    """.trimIndent(),
                )
                throw AssertionError("Computed WebView preferences did not settle: $diagnostic", error)
            }

            scenario.onActivity { activity ->
                val preferences = checkNotNull(activity.controllerForTesting).preferences.value
                assertEquals(1.6, preferences.epub.lineHeight, 0.01)
                val controller = checkNotNull(activity.controllerForTesting)
                assertTrue(controller.goTo(tableOfContents.last().location))
            }
            waitUntil(scenario, "security fixture chapter location") {
                currentLocationOrNull(it)?.resourceKey?.contains("chapter2.xhtml") == true
            }
            waitUntilValue("security fixture chapter rendering") {
                renderedText(scenario).contains("第二章")
            }
            val securityState = evaluateJavascript(
                scenario,
                """
                    JSON.stringify({
                      authorScript: document.documentElement.dataset.epubScriptExecuted || null,
                      authorHandler: document.documentElement.dataset.epubHandlerExecuted || null,
                      authorUrl: document.documentElement.dataset.epubUrlExecuted || null,
                      authorFrame: document.documentElement.dataset.epubFrameExecuted || null,
                      frames: document.querySelectorAll('iframe').length,
                      handlers: document.querySelectorAll('[onload],[onclick]').length,
                      dangerous: document.querySelectorAll('a[href^="javascript:"]').length,
                      remoteImages: document.querySelectorAll('img[src^="http"]').length
                    })
                """.trimIndent(),
            )
            val normalizedSecurityState = securityState.replace("\\\"", "\"")
            assertFalse(normalizedSecurityState, normalizedSecurityState.contains("true"))
        }
    }

    @Test
    fun continuousScrollSupportsTapZoneViewportTurnsAndForcesSinglePage() {
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitForReader(scenario)
            scenario.onActivity { activity ->
                val controller = checkNotNull(activity.controllerForTesting)
                controller.updatePreferences(
                    controller.preferences.value.copy(
                        epub = controller.preferences.value.epub.copy(
                            flow = ReaderReadingMode.ContinuousScroll,
                            spreadMode = ReaderSpreadMode.Double,
                        ),
                    ),
                )
            }
            waitUntil(scenario, "continuous scroll preferences") { activity ->
                val controller = activity.controllerForTesting ?: return@waitUntil false
                activity.navigatorOrNull()?.settings?.value?.scroll == true &&
                    controller.preferences.value.epub.spreadMode == ReaderSpreadMode.Single
            }
            evaluateJavascript(
                scenario,
                "document.body.style.minHeight = '400vh'; document.scrollingElement.scrollTop = 0; true",
            )

            scenario.onActivity { activity ->
                assertTrue(checkNotNull(activity.controllerForTesting).goNext())
            }
            waitUntilValue("continuous scroll forward viewport turn") {
                evaluateJavascript(scenario, "document.scrollingElement.scrollTop").trim('"').toDoubleOrNull()
                    ?.let { it > 1.0 } == true
            }
            val advanced = evaluateJavascript(scenario, "document.scrollingElement.scrollTop")
                .trim('"')
                .toDouble()

            scenario.onActivity { activity ->
                assertTrue(checkNotNull(activity.controllerForTesting).goPrevious())
            }
            waitUntilValue("continuous scroll backward viewport turn") {
                evaluateJavascript(scenario, "document.scrollingElement.scrollTop").trim('"').toDoubleOrNull()
                    ?.let { it < advanced - 1.0 } == true
            }
        }
    }

    @Test
    fun loadsContentsOnceAndSeeksUsingWholePublicationProgress() {
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitForReader(scenario)
            val activeController = controller(scenario)
            assertTrue(activeController.tableOfContents.isEmpty())

            val firstContents = runBlocking { activeController.loadTableOfContents() }
            val cachedContents = runBlocking { activeController.loadTableOfContents() }
            assertTrue(firstContents.isNotEmpty())
            assertSame(firstContents, cachedContents)

            waitUntil(scenario, "initial whole-publication progression") {
                currentLocationOrNull(it)?.totalProgression != null
            }
            val initial = currentLocation(scenario)
            val initialTotal = checkNotNull(initial.totalProgression)
            val seekAccepted = AtomicBoolean(false)
            scenario.onActivity { activity ->
                seekAccepted.set(checkNotNull(activity.controllerForTesting).goToTotalProgression(0.8))
            }
            assertTrue(seekAccepted.get())
            waitUntil(scenario, "whole-publication seek") {
                val location = currentLocationOrNull(it)
                location?.resourceKey?.contains("chapter2.xhtml") == true &&
                    (location.totalProgression ?: -1.0) > initialTotal
            }
            waitUntilValue("whole-publication seek rendering") { renderedText(scenario).contains("第二章") }
            val moved = currentLocation(scenario)
            assertNotNull(moved.totalProgression)
            assertTrue(checkNotNull(moved.totalProgression) > initialTotal)
            runBlocking { activeController.flush() }
            val persisted = runBlocking { progressStore.load(sourceId) }?.location as? ReflowReaderLocation
            assertTrue(checkNotNull(persisted?.totalProgression) > initialTotal)
        }
    }

    @Test
    fun savesClosesAndRestoresTheExactReaderLocation() {
        val saved = ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitForReader(scenario)
            val tableOfContents = runBlocking { controller(scenario).loadTableOfContents() }
            scenario.onActivity { activity ->
                val controller = checkNotNull(activity.controllerForTesting)
                assertTrue(controller.goTo(tableOfContents.last().location))
            }
            waitUntil(scenario, "saved chapter location") {
                currentLocationOrNull(it)?.let { location ->
                    location.resourceKey?.contains("chapter2.xhtml") == true &&
                        ReadiumLocatorEnvelope.from(location) != null
                } == true
            }
            waitUntilValue("saved chapter rendering") { renderedText(scenario).contains("第二章") }
            val locationBeforeLifecycleChanges = currentLocation(scenario)

            scenario.moveToState(Lifecycle.State.CREATED)
            waitUntilValue("background progress flush") {
                (runBlocking { progressStore.load(sourceId) }
                    ?.location as? ReflowReaderLocation)
                    ?.resourceKey
                    ?.contains("chapter2.xhtml") == true
            }
            scenario.moveToState(Lifecycle.State.RESUMED)
            waitForReader(scenario)
            assertEquals(locationBeforeLifecycleChanges.resourceKey, currentLocation(scenario).resourceKey)

            scenario.onActivity {
                it.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            }
            waitUntil(scenario, "landscape reader restoration") {
                it.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE &&
                    currentLocationOrNull(it)?.resourceKey?.contains("chapter2.xhtml") == true
            }
            scenario.onActivity {
                it.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            }
            waitUntil(scenario, "portrait reader restoration") {
                it.resources.configuration.orientation == Configuration.ORIENTATION_PORTRAIT &&
                    currentLocationOrNull(it)?.resourceKey?.contains("chapter2.xhtml") == true
            }

            val locationAfterLifecycleChanges = currentLocation(scenario)
            assertEquals(locationBeforeLifecycleChanges.resourceKey, locationAfterLifecycleChanges.resourceKey)
            assertTrue(
                abs(
                    (locationBeforeLifecycleChanges.totalProgression ?: 0.0) -
                        (locationAfterLifecycleChanges.totalProgression ?: 0.0),
                ) < MAX_LIFECYCLE_PROGRESSION_DRIFT,
            )
            runBlocking { controller(scenario).flush() }
            locationAfterLifecycleChanges
        }

        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { reopened ->
            reopened.keepReaderTestFixtureVisible()
            waitForReader(reopened)
            waitUntil(reopened, "restored chapter location") {
                currentLocationOrNull(it)?.resourceKey?.contains("chapter2.xhtml") == true
            }
            val restored = currentLocation(reopened)
            assertEquals(saved.resourceKey, restored.resourceKey)
            assertNotEquals(0.0, restored.totalProgression ?: 0.0, 0.0001)
            assertNotNull(restored.engineLocator)
        }
    }

    @Test
    fun rejectsSavedProgressWhenTheExactResourceNoLongerExists() = runBlocking {
        val removedResource = "legacy/removed-chapter.xhtml"
        progressStore.save(
            ReaderProgress(
                resourceId = sourceId,
                location = ReflowReaderLocation(
                    resourceKey = removedResource,
                    progression = 0.5,
                    textQuote = TextQuote(exact = "这是第二章，用于验证下一页或目录跳转后的阅读器状态。"),
                    engineLocator = EngineLocator(
                        engine = ReaderEngine.Readium,
                        platform = ReaderEnginePlatform.Android,
                        version = "readium-kotlin:3.3.0",
                        payload = EngineLocatorPayload.parse(
                            """{"href":"$removedResource","type":"application/xhtml+xml","locations":{"cssSelector":"body","progression":0.5},"text":{"highlight":"这是第二章，用于验证下一页或目录跳转后的阅读器状态。"}}""",
                        ),
                    ),
                ),
                updatedAtEpochMillis = 1L,
                deviceId = "legacy-test-device",
            ),
        )

        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            scenario.keepReaderTestFixtureVisible()
            waitForReader(scenario)
            waitUntil(scenario, "missing exact resource warning") {
                it.controllerForTesting?.restoreWarning?.value?.code == ReaderErrorCode.LocationRestoreFailed
            }
            assertFalse(currentLocation(scenario).resourceKey.orEmpty().contains("chapter2.xhtml"))
        }
    }

    private fun waitForReader(scenario: ActivityScenario<ReaderActivity>) {
        waitUntil(scenario, "Reader and navigator") { activity ->
            activity.controllerForTesting != null && activity.navigatorOrNull()?.view != null
        }
    }

    private fun waitUntil(
        scenario: ActivityScenario<ReaderActivity>,
        label: String,
        condition: (ReaderActivity) -> Boolean,
    ) {
        val deadline = SystemClock.uptimeMillis() + TEST_TIMEOUT_MILLIS
        val diagnostic = AtomicReference("activity unavailable")
        while (SystemClock.uptimeMillis() < deadline) {
            instrumentation.waitForIdleSync()
            val matched = AtomicReference(false)
            scenario.onActivity { activity ->
                matched.set(condition(activity))
                val location = currentLocationOrNull(activity)
                diagnostic.set(
                    "orientation=${activity.resources.configuration.orientation}, " +
                        "resource=${location?.resourceKey}, " +
                        "exact=${location?.let(ReadiumLocatorEnvelope::from) != null}, " +
                        "warning=${activity.controllerForTesting?.restoreWarning?.value?.code}",
                )
            }
            if (matched.get()) return
            SystemClock.sleep(POLL_MILLIS)
        }
        throw AssertionError("Timed out waiting for $label; ${diagnostic.get()}")
    }

    private fun waitUntilValue(label: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + TEST_TIMEOUT_MILLIS
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return
            SystemClock.sleep(POLL_MILLIS)
        }
        throw AssertionError("Timed out waiting for $label")
    }

    private fun currentLocation(scenario: ActivityScenario<ReaderActivity>): ReflowReaderLocation =
        AtomicReference<ReflowReaderLocation>().also { result ->
            scenario.onActivity { result.set(checkNotNull(currentLocationOrNull(it))) }
        }.get()

    private fun currentLocationOrNull(activity: ReaderActivity): ReflowReaderLocation? =
        activity.controllerForTesting?.currentLocation?.value as? ReflowReaderLocation

    private fun controller(scenario: ActivityScenario<ReaderActivity>) =
        AtomicReference<com.ermao.library.features.reader.application.ReaderScreenController>().also { result ->
            scenario.onActivity { result.set(checkNotNull(it.controllerForTesting)) }
        }.get()

    private fun renderedText(scenario: ActivityScenario<ReaderActivity>): String =
        evaluateJavascript(scenario, "document.body ? document.body.innerText : ''")

    private fun evaluateJavascript(scenario: ActivityScenario<ReaderActivity>, script: String): String {
        val navigator = AtomicReference<EpubNavigatorFragment>().also { result ->
            scenario.onActivity { result.set(checkNotNull(it.navigatorOrNull())) }
        }.get()
        return runBlocking {
            withContext(Dispatchers.Main) { navigator.evaluateJavascript(script).orEmpty() }
        }
    }

    private fun ReaderActivity.navigatorOrNull(): EpubNavigatorFragment? =
        supportFragmentManager.fragments.filterIsInstance<EpubNavigatorFragment>().singleOrNull()

    private companion object {
        const val TEST_TIMEOUT_MILLIS = 20_000L
        const val POLL_MILLIS = 100L
        const val MAX_LIFECYCLE_PROGRESSION_DRIFT = 0.02
    }
}
