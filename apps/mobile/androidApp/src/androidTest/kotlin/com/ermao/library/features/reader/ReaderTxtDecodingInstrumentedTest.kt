package com.ermao.library.features.reader

import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.TxtDecoder
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import java.io.ByteArrayInputStream
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.navigator.epub.EpubNavigatorFragment

/** Runs the shared byte contract and the real Reader on Android's platform codecs. */
@RunWith(AndroidJUnit4::class)
class ReaderTxtDecodingInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext

    @Test
    fun platformDecoderMatchesAllSharedCases() {
        val cases = JSONObject(instrumentation.context.assets.open("txt-decoding-v2.json")
            .bufferedReader().use { it.readText() }).getJSONArray("cases")
        assertEquals(35, cases.length())
        for (index in 0 until cases.length()) {
            val fixture = cases.getJSONObject(index)
            val bytes = fixture.getString("sourceHex").chunked(2).map { it.toInt(16).toByte() }.toByteArray()
            assertEquals(fixture.getString("id"), fixture.getString("expectedText"), TxtDecoder.decode(bytes))
        }
    }

    @Test
    fun tolerantFilesRenderAndReopenWithoutChangingOriginalBytes() = runBlocking {
        val cases = JSONObject(instrumentation.context.assets.open("txt-decoding-v2.json")
            .bufferedReader().use { it.readText() }).getJSONArray("cases")
        val selected = setOf(
            "gb18030", "gb18030_invalid_byte_between_text", "gb18030_consecutive_invalid_bytes",
            "gb18030_truncated_character", "utf8_bom_invalid_between_text",
            "utf16le_bom_invalid_surrogate_then_text", "utf16be_bom_invalid_surrogate_then_text",
            "gb18030_interior_nul", "gb18030_trailing_160_nul", "gb18030_literal_replacement_character",
        )
        for (index in 0 until cases.length()) {
            val fixture = cases.getJSONObject(index)
            val id = fixture.getString("id")
            if (id !in selected) continue
            verifyRendering(
                id,
                fixture.getString("sourceHex").chunked(2).map { it.toInt(16).toByte() }.toByteArray(),
                fixture.getString("expectedText").split('\u0000', '\n').filter { it.isNotBlank() },
            )
        }
        // U+20000 requires a GB18030 four-byte sequence; GBK cannot encode it.
        verifyRendering("gb18030-four-byte", byteArrayOf(0x95.toByte(), 0x32, 0x82.toByte(), 0x36), listOf("𠀀"))
    }

    private suspend fun verifyRendering(id: String, bytes: ByteArray, expectedParts: List<String>) {
        val store = AndroidReaderPublicationStore(context)
        val resourceId = "txt-decoding-${UUID.randomUUID()}"
        val source = ByteArrayInputStream(bytes).use {
            store.publishLocalPublication(resourceId, id, it, ReaderSourceFormat.Txt)
        }
        try {
            repeat(2) { opening ->
                ActivityScenario.launch<ReaderActivity>(ReaderActivity.createIntent(context, source)).use { scenario ->
                    scenario.keepReaderTestFixtureVisible()
                    val deadline = SystemClock.uptimeMillis() + 20_000L
                    var rendered = ""
                    while (SystemClock.uptimeMillis() < deadline) {
                        instrumentation.waitForIdleSync()
                        var navigator: EpubNavigatorFragment? = null
                        scenario.onActivity { activity ->
                            navigator = activity.supportFragmentManager.fragments
                                .filterIsInstance<EpubNavigatorFragment>().singleOrNull()
                        }
                        rendered = withContext(Dispatchers.Main) {
                            navigator?.evaluateJavascript("document.body ? document.body.innerText : ''").orEmpty()
                        }
                        if (expectedParts.all { rendered.contains(it) }) break
                        SystemClock.sleep(100L)
                    }
                    assertTrue("$id opening=$opening rendered=$rendered", expectedParts.all { rendered.contains(it) })
                }
                assertArrayEquals("$id original bytes", bytes, store.resolve(source).readBytes())
            }
        } finally {
            deleteLocalReaderV5Position(context, source)
            store.delete(resourceId)
        }
    }
}
