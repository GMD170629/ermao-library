package com.ermao.library.testing.reader

import com.ermao.library.shared.modules.reader.domain.ReaderSafetyAction
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyMarkupResult
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class AndroidSafetyAdapterProbeResult(
    val ruleId: String,
    val action: String,
    val errorCode: String?,
    val semanticProjection: String?,
)

fun interface AndroidSafetyAdapterProbe {
    fun evaluate(evaluator: String, source: String): AndroidSafetyAdapterProbeResult
}

/** Report adapter that executes generated facts plus native production probes where required. */
class ReaderSafetyConformanceRunner private constructor(
    private val fixtureText: (String) -> String,
    private val androidAdapterProbe: AndroidSafetyAdapterProbe? = null,
) {
    private val json = Json { prettyPrint = true }

    constructor(
        fixtureRoot: File,
        androidAdapterProbe: AndroidSafetyAdapterProbe? = null,
    ) : this(
        fixtureText = { name -> File(fixtureRoot, name).readText() },
        androidAdapterProbe = androidAdapterProbe,
    )

    fun generate(consumer: String, engine: String): JsonObject {
        require(consumer == "KMP" || consumer == "ANDROID")
        if (consumer == "ANDROID") {
            requireNotNull(androidAdapterProbe) {
                "ANDROID_PRODUCTION_ADAPTER_UNAVAILABLE"
            }
        }
        val suite = readObject("conformance-suite.json")
        val manifest = readObject("manifest.json")
        require(suite.string("policyId") == ReaderSafetyPolicy.policyId)
        require(suite.int("policyVersion") == ReaderSafetyPolicy.policyVersion)
        require(suite.string("policyDigest") == ReaderSafetyPolicy.policyDigest)
        require(manifest.string("policyId") == ReaderSafetyPolicy.policyId)
        require(manifest.int("policyVersion") == ReaderSafetyPolicy.policyVersion)
        require(manifest.string("policyDigest") == ReaderSafetyPolicy.policyDigest)

        val fixtureCases = manifest.array("cases").associate { element ->
            val fixtureCase = element.jsonObject
            fixtureCase.string("id") to fixtureCase
        }
        val results = mutableListOf<JsonObject>()
        suite.array("cases").map { it.jsonObject }
            .filter { suiteCase -> consumer in suiteCase.array("consumers").map { it.jsonPrimitive.content } }
            .forEach { suiteCase ->
                val caseId = suiteCase.string("id")
                val fixtureCase = requireNotNull(fixtureCases[caseId])
                val evaluator = suiteCase.string("evaluator")
                val source = fixtureCase.string("input")
                val probe = if (
                    consumer == "ANDROID" && evaluator in ANDROID_PLATFORM_PROBE_EVALUATORS
                ) {
                    requireNotNull(androidAdapterProbe).evaluate(evaluator, source)
                } else {
                    null
                }
                results += evaluateCase(suiteCase, fixtureCase, probe)
            }

        return buildJsonObject {
            put("schemaVersion", 1)
            put("policyId", ReaderSafetyPolicy.policyId)
            put("policyVersion", ReaderSafetyPolicy.policyVersion)
            put("policyDigest", ReaderSafetyPolicy.policyDigest)
            put("consumer", consumer)
            put("engine", engine)
            put("results", JsonArray(results))
            put("omissions", JsonArray(emptyList()))
        }
    }

    fun verifyAgainstManifest(report: JsonObject) {
        val manifest = readObject("manifest.json")
        val expectedById = manifest.array("cases").associate { element ->
            val fixtureCase = element.jsonObject
            fixtureCase.string("id") to fixtureCase.objectValue("expected")
        }
        report.array("results").forEach { element ->
            val actual = element.jsonObject
            val expected = requireNotNull(expectedById[actual.string("caseId")])
            require(actual.string("terminalRuleId") == expected.string("terminalRuleId"))
            require(actual.string("action") == expected.string("action"))
            require(actual.nullableString("errorCode") == expected.nullableString("errorCode"))
            require(actual.array("orderedRuleEvents") == expected.array("orderedRuleEvents"))
            require(
                actual.nullableString("semanticProjectionSha256") ==
                    expected.nullableString("semanticProjectionSha256"),
            )
        }
    }

    fun write(report: JsonObject, output: File) {
        output.parentFile?.mkdirs()
        output.writeText(json.encodeToString(JsonObject.serializer(), report) + "\n")
    }

    private data class ActualDecision(
        val ruleId: ReaderSafetyRuleId,
        val action: String,
        val errorCode: String?,
        val event: String,
        val semanticProjection: String?,
    )

    private fun evaluateCase(
        suiteCase: JsonObject,
        fixtureCase: JsonObject,
        androidProbe: AndroidSafetyAdapterProbeResult?,
    ): JsonObject {
        val caseId = suiteCase.string("id")
        val ruleId = ReaderSafetyRuleId.entries.single {
            it.wireValue == suiteCase.string("ruleId")
        }
        val source = fixtureCase.string("input")
        val inputSha256 = fixtureCase.string("inputSha256")
        require(sha256(source) == inputSha256) {
            "Reader safety fixture input hash differs for $caseId"
        }
        val evaluator = suiteCase.string("evaluator")
        val decision = when {
            androidProbe != null -> decisionFromAndroidProbe(ruleId, androidProbe)
            evaluator in MARKUP_EVALUATORS -> evaluateMarkupCase(evaluator, ruleId, source)
            else -> evaluateFactCase(evaluator, ruleId, source)
        }
        return buildJsonObject {
            put("caseId", caseId)
            put("inputSha256", inputSha256)
            put("terminalRuleId", decision.ruleId.wireValue)
            put("action", decision.action)
            put("errorCode", decision.errorCode?.let(::JsonPrimitive) ?: JsonNull)
            put("orderedRuleEvents", buildJsonArray { add(JsonPrimitive(decision.event)) })
            put(
                "semanticProjectionSha256",
                decision.semanticProjection?.let(::sha256)?.let(::JsonPrimitive) ?: JsonNull,
            )
        }
    }

    private fun decisionFromAndroidProbe(
        configuredRuleId: ReaderSafetyRuleId,
        probe: AndroidSafetyAdapterProbeResult,
    ): ActualDecision {
        val actualRuleId = ReaderSafetyRuleId.entries.singleOrNull {
            it.wireValue == probe.ruleId
        } ?: error("Android production adapter returned unknown ruleId: ${probe.ruleId}")
        require(actualRuleId == configuredRuleId) {
            "Android production adapter returned ${actualRuleId.wireValue} for ${configuredRuleId.wireValue}"
        }
        val actualAction = ReaderSafetyAction.entries.singleOrNull {
            it.name == probe.action
        } ?: error("Android production adapter returned unknown action: ${probe.action}")
        val generatedRule = ReaderSafetyPolicy.rule(actualRuleId)
        require(actualAction == generatedRule.action) {
            "Android production adapter action differs from generated policy for ${actualRuleId.wireValue}"
        }
        require(probe.errorCode == generatedRule.errorCode?.name) {
            "Android production adapter errorCode differs from generated policy for ${actualRuleId.wireValue}"
        }
        return ActualDecision(
            ruleId = actualRuleId,
            action = actualAction.name,
            errorCode = probe.errorCode,
            event = "${actualRuleId.wireValue}:${actualAction.name}",
            semanticProjection = probe.semanticProjection,
        )
    }

    private fun generatedDecision(
        ruleId: ReaderSafetyRuleId,
        semanticProjection: String? = null,
    ): ActualDecision {
        val rule = ReaderSafetyPolicy.rule(ruleId)
        return ActualDecision(
            ruleId = ruleId,
            action = rule.action.name,
            errorCode = rule.errorCode?.name,
            event = "${ruleId.wireValue}:${rule.action.name}",
            semanticProjection = semanticProjection,
        )
    }

    private fun allowedDecision(
        ruleId: ReaderSafetyRuleId,
        event: String,
        semanticProjection: String,
    ): ActualDecision = ActualDecision(
        ruleId = ruleId,
        action = ReaderSafetyAction.ALLOW.name,
        errorCode = null,
        event = "${ruleId.wireValue}:$event",
        semanticProjection = semanticProjection,
    )

    private fun evaluateMarkupCase(
        evaluator: String,
        configuredRuleId: ReaderSafetyRuleId,
        source: String,
    ): ActualDecision {
        val facadeSource = if (evaluator == "REFLOWABLE_CSS") "<style>$source</style>" else source
        return when (val result = ReaderSafetyFacade().sanitizeMarkup(facadeSource)) {
            is ReaderSafetyMarkupResult.Accepted -> {
                val projection = when (evaluator) {
                    "REFLOWABLE_MARKUP", "REFLOWABLE_NAMED_ENTITIES" -> {
                        if (evaluator == "REFLOWABLE_NAMED_ENTITIES") {
                            require("&#160;" in result.value.parserMarkup)
                            require("&#169;" in result.value.parserMarkup)
                            require("&nbsp;" !in result.value.parserMarkup)
                            require("&copy;" !in result.value.parserMarkup)
                        }
                        requireNotNull(ROOT_ELEMENT.find(result.value.markup))
                            .groups["localName"]?.value?.lowercase()
                    }
                    "REFLOWABLE_CSS" -> STYLE_TEXT.find(result.value.markup)
                        ?.groups?.get("body")?.value
                    "REFLOWABLE_MARKUP_SANITIZE", "REFLOWABLE_URI", "REFLOWABLE_SVG" -> {
                        require(result.value.changed)
                        result.value.markup
                    }
                    else -> error("Unsupported markup evaluator: $evaluator")
                }
                generatedDecision(configuredRuleId, requireNotNull(projection))
            }

            is ReaderSafetyMarkupResult.Rejected -> {
                val actualRuleId = ReaderSafetyRuleId.entries.single {
                    it.wireValue == result.failure.ruleId
                }
                require(actualRuleId == configuredRuleId)
                generatedDecision(actualRuleId)
            }
        }
    }

    private fun evaluateFactCase(
        evaluator: String,
        ruleId: ReaderSafetyRuleId,
        source: String,
    ): ActualDecision {
        val values = if ('=' in source) facts(source) else emptyMap()
        val detected: Boolean
        when (evaluator) {
            "ARCHIVE_STRUCTURE" -> detected = archiveIsUnsafe(
                source,
                ReaderSafetyPolicy.reflowableProfile.archiveFatalFindings,
            )
            "ORIGINAL_BYTES" -> {
                detected = integerFact(values, "sizeBytes") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES)
                if (!detected) return allowedDecision(ruleId, "BOUNDARY_ALLOW", source)
            }
            "FB2_STRUCTURE" -> detected =
                integerFact(values, "depth") > ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_DEPTH) ||
                    integerFact(values, "nodes") > ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_NODES) ||
                    integerFact(values, "textChars") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_TEXT_MAX_CHARACTERS)
            "PDF_ACTIVE_ACTIONS" -> {
                val actions = values.getValue("actions").split(',').filter(String::isNotBlank).toSet()
                val blocked = actions.intersect(ReaderSafetyPolicy.pdfProfile.blockedActions.toSet())
                detected = blocked.isNotEmpty()
                if (detected) {
                    return generatedDecision(ruleId, (actions - blocked).sorted().joinToString(","))
                }
            }
            "PDF_PAGE_GEOMETRY" -> {
                val width = values.getValue("width").toDouble()
                val height = values.getValue("height").toDouble()
                detected = integerFact(values, "pageCount") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_PAGE_MAX_COUNT) ||
                    (
                        ReaderSafetyPolicy.pdfProfile.requireFinitePageGeometry &&
                            (!width.isFinite() || width <= 0 || !height.isFinite() || height <= 0)
                        )
            }
            "PDF_RANGE_PROTOCOL" -> detected =
                (values["status"] != "206" && !ReaderSafetyPolicy.pdfProfile.allowWholeResponseFallback) ||
                    (
                        values["encoding"]?.lowercase() != "identity" &&
                            ReaderSafetyPolicy.pdfProfile.requireIdentityContentEncoding
                        ) ||
                    (
                        values["revision"]?.lowercase() == "weak" &&
                            ReaderSafetyPolicy.pdfProfile.requireStrongRevision
                        )
            "COMIC_PAGE_MIME" -> detected =
                values["manifest"] in ReaderSafetyPolicy.comicProfile.allowedPageMimeTypes &&
                    values["response"] != values["manifest"]
            "COMIC_PAGE_COUNT" -> detected = integerFact(values, "pageCount") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT)
            "COMIC_PAGE_DECODE" -> detected =
                values["decoder"] == "failed" &&
                    ReaderSafetyPolicy.comicProfile.singlePageDecodeFailureAction ==
                    ReaderSafetyAction.BLOCK_RESOURCE
            "COMIC_REVISION" -> detected =
                ReaderSafetyPolicy.comicProfile.manifestRevisionRequired &&
                    values["manifestRevision"] != values["requestRevision"]
            "AUDIO_CONTAINER_MIME" -> detected =
                ReaderSafetyPolicy.audioProfile.containerMimeTypes[values["extension"]?.lowercase()] != null &&
                    ReaderSafetyPolicy.audioProfile.containerMimeTypes[values["extension"]?.lowercase()] !=
                    values["mime"]?.lowercase()
            "AUDIO_CODEC" -> detected =
                ReaderSafetyPolicy.audioProfile.codecDecision == "ENGINE_CAPABILITY" &&
                    values["codec"] == "unsupported"
            "AUDIO_CHAPTER_BOUNDS" -> {
                val duration = values.getValue("durationMs").toDouble()
                val start = values.getValue("chapterStartMs").toDouble()
                val end = values.getValue("chapterEndMs").toDouble()
                detected = !(start >= 0 && start <= end && end <= duration) ||
                    (
                        ReaderSafetyPolicy.audioProfile.requireFiniteNonNegativeDuration &&
                            listOf(duration, start, end).any { !it.isFinite() || it < 0 }
                        )
            }
            "DRM_ALGORITHM" -> {
                detected = values["algorithm"] !in
                    ReaderSafetyPolicy.reflowableProfile.allowedFontObfuscationAlgorithms
                if (!detected) {
                    return allowedDecision(
                        ruleId,
                        "ALLOW_FONT_OBFUSCATION",
                        "font-obfuscation-allowed",
                    )
                }
            }
            "EXACT_FORMAT_MIME" -> {
                val formatPolicy = ReaderSafetyPolicy.formatPolicy(values.getValue("format"))
                val mime = values.getValue("mime").substringBefore(';').trim().lowercase()
                detected = formatPolicy == null || mime !in formatPolicy.acceptedMimeTypes
            }
            "BINARY_RESOURCE_BYTES" -> detected = integerFact(values, "resourceBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.BINARY_RESOURCE_MAX_BYTES)
            "OPTIONAL_RESOURCE" -> detected =
                values["required"] == "false" && values["available"] == "false"
            "REQUIRED_READING_ORDER_MARKUP" -> detected =
                integerFact(values, "readingOrderCount") > 0 &&
                    (
                        integerFact(values, "markupCount") < integerFact(values, "readingOrderCount") ||
                            values["mime"]?.lowercase() !in
                            ReaderSafetyPolicy.reflowableProfile.readingOrderMarkupMimeTypes
                        )
            "XML_CONTROL_DOCUMENT_BYTES" -> detected =
                integerFact(values, "controlDocumentBytes") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.XML_CONTROL_DOCUMENT_MAX_BYTES)
            "REFLOWABLE_MARKUP_BYTES" -> detected = integerFact(values, "markupBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES)
            "EPUB_ARCHIVE_ENTRY_COUNT" -> detected = integerFact(values, "entryCount") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_COUNT)
            "EPUB_ARCHIVE_EXPANDED_BYTES" -> detected = integerFact(values, "expandedBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ARCHIVE_EXPANDED_MAX_BYTES)
            "EPUB_ARCHIVE_ENTRY_BYTES" -> detected = integerFact(values, "entryBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_BYTES)
            "EPUB_ARCHIVE_COMPRESSION_RATIO" -> {
                val compressedBytes = integerFact(values, "compressedBytes")
                detected = compressedBytes <= 0 ||
                    integerFact(values, "expandedBytes") >
                    compressedBytes *
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ARCHIVE_COMPRESSION_RATIO_MAX)
            }
            "FB2_IMAGE_BUDGET" -> detected =
                values["mime"]?.lowercase() !in
                    ReaderSafetyPolicy.reflowableProfile.embeddedImageExtensionsByMimeType ||
                    integerFact(values, "encodedBytes") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_ENCODED_IMAGE_MAX_BYTES) ||
                    integerFact(values, "decodedBytes") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_DECODED_IMAGE_MAX_BYTES) ||
                    integerFact(values, "decodedTotalBytes") >
                    ReaderSafetyPolicy.budget(
                        ReaderSafetyBudgetName.FB2_DECODED_IMAGES_TOTAL_MAX_BYTES,
                    )
            "TXT_MEMORY_BYTES" -> detected = integerFact(values, "textBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.TXT_MEMORY_MAX_BYTES)
            "TXT_CHUNK_CHARACTERS" -> {
                detected = integerFact(values, "chunkCharacters") <=
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.TXT_CHUNK_MAX_CHARACTERS)
                if (detected) return generatedDecision(ruleId, source)
            }
            "PDF_RENDER_BUDGET" -> detected =
                integerFact(values, "width") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_CANVAS_MAX_DIMENSION) ||
                    integerFact(values, "height") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_CANVAS_MAX_DIMENSION) ||
                    integerFact(values, "pixels") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.PDF_RENDER_MAX_PIXELS)
            "COMIC_ARCHIVE_STRUCTURE" -> detected = archiveIsUnsafe(
                source,
                ReaderSafetyPolicy.comicProfile.archiveFatalFindings,
            )
            "COMIC_ARCHIVE_BUDGET" -> {
                val compressedBytes = integerFact(values, "compressedBytes")
                val expandedBytes = integerFact(values, "expandedBytes")
                detected = expandedBytes >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.COMIC_EXPANDED_MAX_BYTES) ||
                    compressedBytes <= 0 ||
                    expandedBytes > compressedBytes *
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.COMIC_COMPRESSION_RATIO_MAX)
            }
            "COMIC_PAGE_BYTES" -> detected = integerFact(values, "pageBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES)
            "COMIC_MANIFEST_BYTES" -> detected = integerFact(values, "manifestBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES)
            "AUDIO_ORIGINAL_BYTES" -> detected = integerFact(values, "sizeBytes") >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES)
            "AUDIO_METADATA_BUDGET" -> detected =
                integerFact(values, "metadataBytes") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.AUDIO_METADATA_MAX_BYTES) ||
                    integerFact(values, "artworkBytes") >
                    ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.AUDIO_ARTWORK_MAX_BYTES)
            "AUDIO_REDIRECT_POLICY" -> detected =
                values["scheme"]?.lowercase() in ReaderSafetyPolicy.audioProfile.blockedRedirectSchemes
            else -> error("Unsupported pure-policy evaluator: $evaluator")
        }
        require(detected) { "$evaluator fixture did not trigger its generated policy fact" }
        return generatedDecision(ruleId)
    }

    private fun facts(source: String): Map<String, String> = source.split(';').associate { component ->
        val separator = component.indexOf('=')
        require(separator > 0) { "Invalid conformance fact: $component" }
        component.substring(0, separator) to component.substring(separator + 1)
    }

    private fun integerFact(values: Map<String, String>, name: String): Long =
        requireNotNull(values[name]).toLong()

    private fun archiveIsUnsafe(source: String, fatalFindings: List<String>): Boolean {
        val findings = mutableSetOf<String>()
        val canonical = mutableSetOf<String>()
        source.split('|').forEach { entry ->
            if ('\\' in entry) findings += "BACKSLASH_PATH"
            if ('\u0000' in entry) findings += "NUL_PATH"
            if (entry.startsWith('/')) findings += "ABSOLUTE_PATH"
            val parts = mutableListOf<String>()
            var escaped = false
            entry.split('/').forEach { part ->
                when (part) {
                    "" -> Unit
                    "." -> findings += "DOT_SEGMENT"
                    ".." -> {
                        findings += "DOT_SEGMENT"
                        if (parts.isEmpty()) escaped = true else parts.removeLast()
                    }
                    else -> parts += part
                }
            }
            if (escaped) findings += "PATH_ESCAPE"
            val normalized = parts.joinToString("/").lowercase()
            if (!canonical.add(normalized)) findings += "DUPLICATE_CANONICAL_ENTRY"
        }
        return findings.any { it in fatalFindings }
    }

    private fun readObject(name: String): JsonObject =
        json.parseToJsonElement(fixtureText(name)).jsonObject

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.encodeToByteArray())
        .joinToString(separator = "") { byte -> "%02x".format(byte.toInt() and 0xff) }

    private fun JsonObject.array(name: String): JsonArray = requireNotNull(this[name]).jsonArray
    private fun JsonObject.objectValue(name: String): JsonObject = requireNotNull(this[name]).jsonObject
    private fun JsonObject.string(name: String): String = requireNotNull(this[name]).jsonPrimitive.content
    private fun JsonObject.nullableString(name: String): String? = this[name]?.jsonPrimitive?.contentOrNull
    private fun JsonObject.int(name: String): Int = requireNotNull(this[name]).jsonPrimitive.int

    companion object {
        val ANDROID_PLATFORM_PROBE_EVALUATORS = setOf(
            "REFLOWABLE_MARKUP",
            "REFLOWABLE_NAMED_ENTITIES",
            "REFLOWABLE_MARKUP_SANITIZE",
            "REFLOWABLE_URI",
            "REFLOWABLE_CSS",
            "REFLOWABLE_SVG",
            "EPUB_ARCHIVE_CRC",
            "PDF_ACTIVE_ACTIONS",
            "PDF_PAGE_GEOMETRY",
            "PDF_RENDER_BUDGET",
            "COMIC_PAGE_DECODE",
        )

        fun fromJson(
            suiteJson: String,
            manifestJson: String,
            androidAdapterProbe: AndroidSafetyAdapterProbe? = null,
        ): ReaderSafetyConformanceRunner = ReaderSafetyConformanceRunner(
            fixtureText = { name ->
                when (name) {
                    "conformance-suite.json" -> suiteJson
                    "manifest.json" -> manifestJson
                    else -> error("Unknown Reader safety fixture: $name")
                }
            },
            androidAdapterProbe = androidAdapterProbe,
        )

        val MARKUP_EVALUATORS = setOf(
            "REFLOWABLE_MARKUP",
            "REFLOWABLE_NAMED_ENTITIES",
            "REFLOWABLE_MARKUP_SANITIZE",
            "REFLOWABLE_URI",
            "REFLOWABLE_CSS",
            "REFLOWABLE_SVG",
        )
        val ROOT_ELEMENT = Regex("<(?:[A-Za-z_][\\w.-]*:)?(?<localName>[A-Za-z][\\w.-]*)\\b")
        val STYLE_TEXT = Regex("(?is)<style\\b[^>]*>(?<body>.*?)</style\\s*>")
    }
}
