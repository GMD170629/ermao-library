package com.ermao.library.reader.mobipoc

import android.os.Bundle
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import com.ermao.library.mobi.infrastructure.MobiReadiumPublication
import com.ermao.library.mobi.infrastructure.MobiReadiumPublicationFactory
import com.ermao.library.shared.modules.reader.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.ExactBlockMatch
import com.ermao.library.shared.modules.reader.PublicationFingerprint
import com.ermao.library.shared.modules.reader.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.ReadiumLocatorEnvelope
import com.ermao.library.shared.modules.reader.compareExactReadiumLocators
import java.io.File
import java.util.concurrent.CountDownLatch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.readium.r2.navigator.epub.EpubNavigatorFactory
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.epub.EpubPreferences
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.mediatype.MediaType

/** Runnable Android Readium Kotlin + pinned mobiCore conformance harness. */
class MobiReadiumConformanceActivity : AppCompatActivity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var opened: MobiReadiumPublication? = null

    val completion = CountDownLatch(1)
    @Volatile var report: MobiConformanceReport? = null
        private set
    @Volatile var failure: Throwable? = null
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = FrameLayout(this).apply { id = CONTAINER_ID }
        setContentView(container)
        scope.launch {
            try {
                report = runConformance()
            } catch (error: Throwable) {
                failure = error
            } finally {
                completion.countDown()
            }
        }
    }

    override fun onDestroy() {
        scope.cancel()
        opened?.close()
        opened = null
        super.onDestroy()
    }

    @OptIn(ExperimentalReadiumApi::class)
    private suspend fun runConformance(): MobiConformanceReport {
        val fixture = withContext(Dispatchers.IO) { copyFixture() }
        val extracted = withContext(Dispatchers.IO) { MobiReadiumPublicationFactory().open(fixture) }
        opened = extracted
        check(extracted.originalFileHash == EXPECTED_FILE_SHA256)
        check(extracted.parser == EXPECTED_PARSER)
        check(extracted.normalization == EXPECTED_NORMALIZATION)
        check(extracted.readingOrderHrefs == listOf(EXPECTED_HREF))
        val xhtml = checkNotNull(extracted.resources.singleOrNull { it.href == EXPECTED_HREF })
        check(xhtml.sha256 == EXPECTED_XHTML_SHA256)
        val xhtmlText = checkNotNull(extracted.decodedText(EXPECTED_HREF))
        check(listOf("ZH_TEXT_MARKER", "𠮷", "𪚥").all(xhtmlText::contains))

        val fragmentFactory = EpubNavigatorFactory(extracted.publication).createFragmentFactory(
            initialLocator = null,
            initialPreferences = EpubPreferences(
                scroll = true,
                publisherStyles = false,
                fontSize = 3.0,
                typeScale = 3.0,
            ),
        )
        supportFragmentManager.fragmentFactory = fragmentFactory
        val navigator = fragmentFactory.instantiate(
            classLoader,
            EpubNavigatorFragment::class.java.name,
        ) as EpubNavigatorFragment
        supportFragmentManager.beginTransaction().replace(CONTAINER_ID, navigator).commitNow()

        val markerTarget = Locator(
            href = requireNotNull(Url(EXPECTED_HREF)),
            mediaType = MediaType.XHTML,
            locations = Locator.Locations(
                fragments = listOf("zh-proof"),
                otherLocations = mapOf("cssSelector" to "#zh-proof"),
            ),
            text = Locator.Text(highlight = "ZH_TEXT_MARKER"),
        )
        check(navigator.go(markerTarget, animated = false))
        val expected = captureExact(navigator, extracted, requiredText = "ZH_TEXT_MARKER")

        val chapterTarget = Locator(
            href = requireNotNull(Url(EXPECTED_HREF)),
            mediaType = MediaType.XHTML,
            locations = Locator.Locations(
                fragments = listOf("chapter-title"),
                otherLocations = mapOf("cssSelector" to "#chapter-title"),
            ),
            text = Locator.Text(highlight = "中文"),
        )
        check(navigator.go(chapterTarget, animated = false))
        captureExact(navigator, extracted, requiredText = "中文", forbiddenText = "ZH_TEXT_MARKER")

        val expectedReadiumLocator = requireNotNull(Locator.fromJSON(org.json.JSONObject(expected.payload.canonicalJson)))
        check(navigator.go(expectedReadiumLocator, animated = false))
        val recaptured = captureExact(navigator, extracted, requiredText = "ZH_TEXT_MARKER")
        val exactBlockMatch = compareExactReadiumLocators(expected, recaptured)
        check(exactBlockMatch == ExactBlockMatch.Exact) {
            "Readium go() succeeded but post-navigation exact-block verification failed: $exactBlockMatch"
        }

        return MobiConformanceReport(
            originalFileHash = extracted.originalFileHash,
            parser = extracted.parser,
            normalization = extracted.normalization,
            readingOrderHrefs = extracted.readingOrderHrefs,
            xhtmlSha256 = xhtml.sha256,
            expectedLocator = expected.canonicalJson(),
            recapturedLocator = recaptured.canonicalJson(),
            exactBlockMatch = exactBlockMatch,
        )
    }

    @OptIn(ExperimentalReadiumApi::class)
    private suspend fun captureExact(
        navigator: EpubNavigatorFragment,
        publication: MobiReadiumPublication,
        requiredText: String,
        forbiddenText: String? = null,
    ): ReadiumLocatorEnvelope = withTimeout(READIUM_TIMEOUT_MILLIS) {
        while (true) {
            val locator = navigator.firstVisibleElementLocator()
            val envelope = locator?.let { runCatching { it.toEnvelope(publication) }.getOrNull() }
            val text = locator?.text?.highlight.orEmpty()
            if (envelope != null && requiredText in text && (forbiddenText == null || forbiddenText !in text)) {
                return@withTimeout envelope
            }
            delay(READIUM_POLL_MILLIS)
        }
        error("Unreachable")
    }

    private fun Locator.toEnvelope(publication: MobiReadiumPublication): ReadiumLocatorEnvelope =
        ReadiumLocatorEnvelope(
            platform = ReaderEnginePlatform.Android,
            version = "readium-kotlin:3.3.0",
            publication = PublicationFingerprint(
                originalFileHash = publication.originalFileHash,
                parser = publication.parser,
                normalization = publication.normalization,
            ),
            payload = EngineLocatorPayload.parse(toJSON().toString()),
        )

    private fun copyFixture(): File {
        val target = File(cacheDir, FIXTURE_NAME)
        assets.open(FIXTURE_NAME).use { input -> target.outputStream().use(input::copyTo) }
        return target
    }

    companion object {
        const val FIXTURE_NAME = "08-zh-hans.azw3"
        const val EXPECTED_FILE_SHA256 = "f2b9fdd883430568c161995e80e52fc337ceb417222884c3c782af8202f4c581"
        const val EXPECTED_PARSER = "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add"
        const val EXPECTED_NORMALIZATION = "ermao-mobi-core-v1"
        const val EXPECTED_HREF = "part00000.html"
        const val EXPECTED_XHTML_SHA256 = "a2c8ab0d3592ab8b5fc7c73a817fc1e2b5f3b175de86ccb0623cfdf1929065e5"
        private const val CONTAINER_ID = 0x5151
        private const val READIUM_TIMEOUT_MILLIS = 20_000L
        private const val READIUM_POLL_MILLIS = 100L
    }
}

data class MobiConformanceReport(
    val originalFileHash: String,
    val parser: String,
    val normalization: String,
    val readingOrderHrefs: List<String>,
    val xhtmlSha256: String,
    val expectedLocator: String,
    val recapturedLocator: String,
    val exactBlockMatch: ExactBlockMatch,
)
