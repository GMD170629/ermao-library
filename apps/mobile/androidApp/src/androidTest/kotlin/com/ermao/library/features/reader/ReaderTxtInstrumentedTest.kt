package com.ermao.library.features.reader

import android.content.Context
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.ReaderOpenFailure
import com.ermao.library.features.reader.infrastructure.RemoteReflowableReadiumPublicationFactory
import com.ermao.library.features.reader.infrastructure.TxtReadiumPublicationFactory
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.OnlinePublicationFailure
import com.ermao.library.shared.modules.reader.OnlinePublicationReadContent
import com.ermao.library.shared.modules.reader.OnlinePublicationReadResult
import com.ermao.library.shared.modules.reader.OnlinePublicationSession
import com.ermao.library.shared.modules.reader.OnlinePublicationStage
import com.ermao.library.shared.modules.reader.PublicationResourcePort
import com.ermao.library.shared.modules.reader.ReaderAdmission
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.RemoteReflowableReaderSource
import java.io.ByteArrayInputStream
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.shared.publication.services.positions

@RunWith(AndroidJUnit4::class)
class ReaderTxtInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val sourceId = "txt-reader-${UUID.randomUUID()}"
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val progressStore = AndroidReaderProgressStore(context)
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
        progressStore.delete(sourceId)
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
    fun onlineMetadataRejectedByReadiumPreservesTheCauseAndStage() = runBlocking {
        for (stage in listOf(OnlinePublicationStage.Manifest, OnlinePublicationStage.Positions)) {
            val mediaType = if (stage == OnlinePublicationStage.Positions) "not-a-media-type" else "application/xhtml+xml"
            val link = """{"href":"text/chapter-0001.xhtml","type":"$mediaType"}"""
            val title = if (stage == OnlinePublicationStage.Manifest) "" else """"metadata":{"title":"Reading"},"""
            val responses = mapOf(
                "manifest.json" to """{$title"readingOrder":[$link]}""",
                "positions.json" to """{"positions":[$link]}""",
            )
            val requests = mutableListOf<String>()
            val port = object : PublicationResourcePort {
                override suspend fun read(apiPath: String, maximumBytes: Int, mediaTypes: Set<String>): OnlinePublicationReadResult {
                    val name = apiPath.substringAfterLast('/')
                    requests += name
                    return OnlinePublicationReadContent(responses.getValue(name).encodeToByteArray())
                }
                override fun close() = Unit
            }
            val online = OnlinePublicationSession(RemoteReflowableReaderSource(
                "resource", "Reading", "book", "asset", ReaderSourceFormat.Txt,
                ReaderSyncNamespace("server", "user", 1),
                "/api/reader/v4/resources/resource/publication/manifest.json",
                "/api/reader/v4/resources/resource/publication/positions.json",
            ), port)
            try {
                // The shared transport contract accepts these inputs; the SDK owns
                // the missing metadata / invalid Locator media-type rejection.
                online.open()
                try {
                    RemoteReflowableReadiumPublicationFactory(online) {
                        throw AssertionError("Metadata opening must not request chapter content")
                    }.open().close()
                    throw AssertionError("Readium must reject $stage metadata")
                } catch (failure: ReaderOpenFailure) {
                    val translated = failure.cause as? OnlinePublicationFailure
                        ?: throw AssertionError("The shared metadata failure must be retained", failure)
                    assertEquals(stage, translated.stage)
                    assertTrue(translated.cause is IllegalArgumentException)
                    assertEquals(ReaderErrorCode.InvalidResponse, failure.readerError.code)
                    assertEquals(OnlinePublicationFailure.invalidMetadata(stage).readerError, failure.readerError)
                    assertFalse(ReaderAdmission.permitsDownload(failure.readerError.code))
                }
                assertEquals(listOf("manifest.json", "positions.json"), requests)
            } finally {
                online.close()
            }
        }
    }

    @Test
    fun opensRendersNavigatesAndCapturesExactLocationWithEpubNavigator() {
        ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
            waitUntil(scenario, "TXT reader") {
                it.controllerForTesting != null && it.navigatorOrNull()?.view != null
            }
            scenario.onActivity { activity ->
                val controller = checkNotNull(activity.controllerForTesting)
                assertEquals(2, controller.tableOfContents.size)
                assertTrue(controller.goTo(controller.tableOfContents.last().location))
            }
            waitUntil(scenario, "second TXT chapter") {
                (it.controllerForTesting?.currentLocation?.value as? ReflowReaderLocation)
                    ?.resourceKey == "text/chapter-0002.xhtml"
            }
            assertTrue(renderedText(scenario).contains("Second chapter"))
            scenario.onActivity { activity ->
                val location = activity.controllerForTesting?.currentLocation?.value as? ReflowReaderLocation
                assertNotNull(location?.engineLocator)
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
