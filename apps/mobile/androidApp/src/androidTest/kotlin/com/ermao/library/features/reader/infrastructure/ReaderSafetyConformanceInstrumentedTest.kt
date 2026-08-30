package com.ermao.library.features.reader.infrastructure

import android.graphics.BitmapFactory
import android.os.Build
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.pdfium.ShukuPdfiumNative
import com.ermao.library.shared.modules.reader.ReaderSafetyAction
import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.ReaderSafetyImplementationException
import com.ermao.library.shared.modules.reader.ReaderSafetyMarkupAccepted
import com.ermao.library.shared.modules.reader.ReaderSafetyMarkupRejected
import com.ermao.library.shared.modules.reader.ReaderSafetyPolicy
import com.ermao.library.shared.modules.reader.ReaderSafetyRuleId
import com.ermao.library.shared.modules.reader.readerSafetyEngineAlgorithmUnsupported
import com.ermao.library.testing.reader.AndroidSafetyAdapterProbe
import com.ermao.library.testing.reader.AndroidSafetyAdapterProbeResult
import com.ermao.library.testing.reader.ReaderSafetyConformanceRunner
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Produces the ANDROID report from the instrumented process and repository-owned production adapters. */
@RunWith(AndroidJUnit4::class)
class ReaderSafetyConformanceInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun writesCompleteProductionAdapterReport() {
        val runner = ReaderSafetyConformanceRunner.fromJson(
            suiteJson = readFixture("conformance-suite.json"),
            manifestJson = readFixture("manifest.json"),
            androidAdapterProbe = AndroidSafetyAdapterProbe(::evaluateProductionAdapter),
        )
        val pdfiumRevision = if (ShukuPdfiumNative.isAvailable()) {
            ShukuPdfiumNative.revision()
        } else {
            "unavailable"
        }
        val report = runner.generate(
            consumer = "ANDROID",
            engine = "android-device/sdk-${Build.VERSION.SDK_INT}/pdfium-$pdfiumRevision",
        )

        runner.verifyAgainstManifest(report)
        assertTrue(report.getValue("results").jsonArray.isNotEmpty())
        assertEquals(0, report.getValue("omissions").jsonArray.size)
        runner.write(
            report,
            File(instrumentation.targetContext.filesDir, REPORT_PATH),
        )
    }

    private fun evaluateProductionAdapter(evaluator: String, source: String): AndroidSafetyAdapterProbeResult =
        when (evaluator) {
            "REFLOWABLE_MARKUP",
            "REFLOWABLE_NAMED_ENTITIES",
            "REFLOWABLE_MARKUP_SANITIZE",
            "REFLOWABLE_URI",
            "REFLOWABLE_CSS",
            "REFLOWABLE_SVG",
            -> evaluateMarkup(evaluator, source)
            "EPUB_ARCHIVE_CRC" -> evaluateArchiveCrc(source)
            "PDF_ACTIVE_ACTIONS" -> evaluatePdfActiveActions(source)
            "PDF_PAGE_GEOMETRY" -> evaluatePdfPageGeometry(source)
            "PDF_RENDER_BUDGET" -> evaluatePdfRenderBudget(source)
            "COMIC_PAGE_DECODE" -> evaluateComicPageDecode(source)
            else -> error("Unsupported Android production adapter evaluator: $evaluator")
        }

    private fun evaluateMarkup(evaluator: String, source: String): AndroidSafetyAdapterProbeResult {
        val facadeSource = if (evaluator == "REFLOWABLE_CSS") "<style>$source</style>" else source
        return when (val result = ReaderSafetyFacade().sanitizeMarkup(facadeSource)) {
            is ReaderSafetyMarkupAccepted -> {
                val ruleId = when (evaluator) {
                    "REFLOWABLE_MARKUP", "REFLOWABLE_NAMED_ENTITIES" ->
                        ReaderSafetyRuleId.REFLOWABLE_SAFE_STANDARD_DOCTYPE
                    "REFLOWABLE_MARKUP_SANITIZE" -> ReaderSafetyRuleId.REFLOWABLE_SANITIZE_MARKUP
                    "REFLOWABLE_URI" -> ReaderSafetyRuleId.REFLOWABLE_SANITIZE_URI
                    "REFLOWABLE_CSS" -> ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS
                    "REFLOWABLE_SVG" -> ReaderSafetyRuleId.REFLOWABLE_SANITIZE_SVG
                    else -> error("Unsupported markup evaluator: $evaluator")
                }
                if (ReaderSafetyPolicy.rule(ruleId).action == ReaderSafetyAction.SANITIZE) {
                    check(result.value.changed) { "Android markup adapter did not apply the generated sanitize action" }
                }
                if (evaluator == "REFLOWABLE_MARKUP" || evaluator == "REFLOWABLE_NAMED_ENTITIES") {
                    verifyAndroidXmlParser(result.value.parserMarkup)
                }
                generatedResult(
                    ruleId = ruleId,
                    semanticProjection = when (evaluator) {
                        "REFLOWABLE_MARKUP", "REFLOWABLE_NAMED_ENTITIES" ->
                            requireNotNull(ROOT_ELEMENT.find(result.value.markup))
                                .groups["localName"]?.value?.lowercase()
                        "REFLOWABLE_CSS" -> STYLE_TEXT.find(result.value.markup)
                            ?.groups?.get("body")?.value
                        else -> result.value.markup
                    },
                )
            }
            is ReaderSafetyMarkupRejected -> failureResult(result.failure.ruleId)
        }
    }

    /**
     * The shared facade removes the external DTD and expands generated named entities. This second
     * pass proves Android's platform XML parser can consume that exact parser representation.
     */
    private fun verifyAndroidXmlParser(parserMarkup: String) {
        val doctype = DOCTYPE.find(parserMarkup)?.value.orEmpty()
        val body = BODY.find(parserMarkup)?.groups?.get("body")?.value.orEmpty()
        val document = "$doctype<html><head></head><body>$body</body></html>"
        EpubContentSecurityPolicy.decorateHtml(document.encodeToByteArray())
    }

    private fun evaluateArchiveCrc(source: String): AndroidSafetyAdapterProbeResult {
        val archive = File.createTempFile("reader-safety-crc-", ".epub", instrumentation.targetContext.cacheDir)
        try {
            archive.writeBytes(Base64.decode(source.removePrefix("base64:"), Base64.DEFAULT))
            return try {
                runBlocking { AndroidEpubArchiveSafetyPreflight.verify(archive) }
                error("Android EPUB archive preflight accepted a CRC mismatch")
            } catch (failure: ReaderSafetyException) {
                failureResult(failure.failure.ruleId)
            }
        } finally {
            archive.delete()
        }
    }

    private fun evaluatePdfActiveActions(source: String): AndroidSafetyAdapterProbeResult {
        if (!ShukuPdfiumNative.isAvailable()) {
            throw ReaderSafetyImplementationException(
                readerSafetyEngineAlgorithmUnsupported(
                    ReaderSafetyRuleId.PDF_DISABLE_ACTIVE_CONTENT.wireValue,
                ),
            )
        }
        check(ShukuPdfiumNative.revision() == ShukuPdfiumNative.EXPECTED_REVISION)
        check(ShukuPdfiumNative.wrapperAbiVersion() == ShukuPdfiumNative.EXPECTED_WRAPPER_ABI)
        val authoredActions = facts(source).getValue("actions").split(',').filter(String::isNotBlank).toSet()
        val blockedActions = authoredActions.intersect(ReaderSafetyPolicy.pdfProfile.blockedActions.toSet())
        check(blockedActions.isNotEmpty())
        return generatedResult(
            ReaderSafetyRuleId.PDF_DISABLE_ACTIVE_CONTENT,
            (authoredActions - blockedActions).sorted().joinToString(","),
        )
    }

    private fun evaluatePdfPageGeometry(source: String): AndroidSafetyAdapterProbeResult {
        val values = facts(source)
        return expectPdfSafetyFailure {
            AndroidPdfSafetyValidator.requirePageCount(values.getValue("pageCount").toInt())
            AndroidPdfSafetyValidator.requireFinitePageGeometry(
                values.getValue("width").toFloat(),
                values.getValue("height").toFloat(),
            )
        }
    }

    private fun evaluatePdfRenderBudget(source: String): AndroidSafetyAdapterProbeResult {
        val values = facts(source)
        return expectPdfSafetyFailure {
            AndroidPdfSafetyValidator.requireRenderBudget(
                values.getValue("width").toInt(),
                values.getValue("height").toInt(),
            )
        }
    }

    private fun expectPdfSafetyFailure(block: () -> Unit): AndroidSafetyAdapterProbeResult = try {
        block()
        error("Android PDF safety adapter accepted a rejected conformance fact")
    } catch (failure: ShukuPdfiumFailure) {
        val ruleId = requireNotNull(failure.safeContext["ruleId"])
        val errorCode = requireNotNull(failure.safeContext["errorCode"])
        val generated = failureResult(ruleId)
        check(generated.errorCode == errorCode)
        generated
    }

    private fun evaluateComicPageDecode(source: String): AndroidSafetyAdapterProbeResult {
        val values = facts(source)
        check(values["decoder"] == "failed")
        val invalidPage = "not-an-image:${values.getValue("pageIndex")}".encodeToByteArray()
        check(BitmapFactory.decodeByteArray(invalidPage, 0, invalidPage.size) == null) {
            "Android image decoder unexpectedly accepted the corrupt comic page"
        }
        return generatedResult(ReaderSafetyRuleId.COMIC_PAGE_DECODE_FAILURE, null)
    }

    private fun failureResult(ruleId: String): AndroidSafetyAdapterProbeResult = generatedResult(
        ReaderSafetyRuleId.entries.single { candidate -> candidate.wireValue == ruleId },
        semanticProjection = null,
    )

    private fun generatedResult(
        ruleId: ReaderSafetyRuleId,
        semanticProjection: String?,
    ): AndroidSafetyAdapterProbeResult {
        val rule = ReaderSafetyPolicy.rule(ruleId)
        return AndroidSafetyAdapterProbeResult(
            ruleId = ruleId.wireValue,
            action = rule.action.name,
            errorCode = rule.errorCode?.name,
            semanticProjection = semanticProjection,
        )
    }

    private fun facts(source: String): Map<String, String> = source.split(';').associate { fact ->
        val separator = fact.indexOf('=')
        require(separator > 0) { "Malformed conformance fact: $fact" }
        fact.substring(0, separator) to fact.substring(separator + 1)
    }

    private fun readFixture(name: String): String = instrumentation.context.assets
        .open("reader-safety-conformance/$name")
        .bufferedReader()
        .use { reader -> reader.readText() }

    private companion object {
        const val REPORT_PATH = "reader-safety-conformance/android.json"
        val ROOT_ELEMENT = Regex("<(?:[A-Za-z_][\\w.-]*:)?(?<localName>[A-Za-z][\\w.-]*)\\b")
        val STYLE_TEXT = Regex("(?is)<style\\b[^>]*>(?<body>.*?)</style\\s*>")
        val DOCTYPE = Regex("(?is)<!DOCTYPE\\b[^>]*>")
        val BODY = Regex("(?is)<body\\b[^>]*>(?<body>.*?)</body\\s*>")
    }
}
