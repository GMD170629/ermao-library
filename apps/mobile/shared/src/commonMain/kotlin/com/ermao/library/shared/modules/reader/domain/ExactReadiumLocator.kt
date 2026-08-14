package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put

/**
 * Content identity required before a Readium locator may cross a device boundary.
 *
 * The parser identifies the component which produced the Publication DOM. It is
 * deliberately not the Navigator version, which is diagnostic metadata on
 * [ReadiumLocatorEnvelope].
 */
class PublicationFingerprint(
    originalFileHash: String,
    val parser: String,
    val normalization: String,
) {
    private val originalFileDigest: String = originalFileHash.removePrefix("sha256:").lowercase()
    val originalFileHash: String = "sha256:$originalFileDigest"

    init {
        require(originalFileDigest.length == 64 && originalFileDigest.all(Char::isHexDigit)) {
            "Publication fingerprint must contain a SHA-256 hash"
        }
        require(parser.isNotBlank() && parser.unicodeCodePointCount() <= MAXIMUM_COMPONENT_LENGTH) {
            "Publication parser is invalid"
        }
        require(normalization.isNotBlank() && normalization.unicodeCodePointCount() <= MAXIMUM_COMPONENT_LENGTH) {
            "Publication normalization is invalid"
        }
    }

    val stableKey: String
        get() = "$originalFileHash|$parser|$normalization"

    fun toContentFingerprint(): ContentFingerprint = ContentFingerprint(
        originalFileHash = originalFileHash,
        parserVersion = parser,
        normalizationVersion = normalization,
    )

    companion object {
        private const val MAXIMUM_COMPONENT_LENGTH = 256

        fun from(value: ContentFingerprint): PublicationFingerprint = PublicationFingerprint(
            originalFileHash = value.originalFileHash,
            parser = value.parserVersion,
            normalization = value.normalizationVersion,
        )
    }

    override fun equals(other: Any?): Boolean = other is PublicationFingerprint &&
        originalFileHash == other.originalFileHash && parser == other.parser && normalization == other.normalization

    override fun hashCode(): Int = 31 * (31 * originalFileHash.hashCode() + parser.hashCode()) + normalization.hashCode()

    override fun toString(): String = "PublicationFingerprint($originalFileHash, $parser, $normalization)"
}

/** A validated Readium Locator envelope used by Reader v4 and durable sync. */
data class ReadiumLocatorEnvelope(
    val platform: ReaderEnginePlatform,
    /** Navigator implementation/version, e.g. `readium-kotlin:3.3.0`. */
    val version: String,
    val publication: PublicationFingerprint,
    val payload: EngineLocatorPayload,
) {
    init {
        require(version.isNotBlank()) { "Readium Navigator version is blank" }
        require(version.unicodeCodePointCount() <= MAXIMUM_VERSION_LENGTH) { "Readium Navigator version is too long" }
        require(exactAnchorOrNull() != null) { "Readium Locator does not contain an exact block anchor" }
        require(canonicalJson().encodeToByteArray().size <= MAXIMUM_ENVELOPE_BYTES) {
            "Readium Locator envelope exceeds 64 KiB"
        }
    }

    val engine: ReaderEngine
        get() = ReaderEngine.Readium

    fun asEngineLocator(): EngineLocator = EngineLocator(
        engine = ReaderEngine.Readium,
        platform = platform,
        version = version,
        payload = payload,
    )

    fun canonicalJson(): String = buildJsonObject {
        put("engine", ReaderEngine.Readium.wireValue)
        put("platform", platform.wireValue)
        put("version", version)
        put("publication", buildJsonObject {
            put("originalFileHash", publication.originalFileHash)
            put("parser", publication.parser)
            put("normalization", publication.normalization)
        })
        put("payload", Json.parseToJsonElement(payload.canonicalJson))
    }.toString()

    fun exactAnchorOrNull(): ReadiumExactAnchor? = payload.toExactAnchorOrNull()

    companion object {
        const val MAXIMUM_ENVELOPE_BYTES = 65_536
        const val MAXIMUM_HIGHLIGHT_LENGTH = 512
        const val MAXIMUM_CONTEXT_LENGTH = 256
        private const val MAXIMUM_VERSION_LENGTH = 256

        fun from(location: ReflowReaderLocation): ReadiumLocatorEnvelope? {
            val locator = location.engineLocator ?: return null
            if (locator.engine != ReaderEngine.Readium) return null
            return runCatching {
                ReadiumLocatorEnvelope(
                    platform = locator.platform,
                    version = locator.version,
                    publication = PublicationFingerprint.from(location.contentFingerprint),
                    payload = locator.payload,
                )
            }.getOrNull()
        }

        fun parse(value: String): ReadiumLocatorEnvelope {
            require(value.encodeToByteArray().size <= MAXIMUM_ENVELOPE_BYTES) {
                "Readium Locator envelope exceeds 64 KiB"
            }
            val root = Json.parseToJsonElement(value) as? JsonObject
                ?: throw IllegalArgumentException("Readium Locator envelope must be a JSON object")
            require(root.requiredString("engine") == ReaderEngine.Readium.wireValue) {
                "Reader v4 only accepts Readium locators"
            }
            val publication = root["publication"] as? JsonObject
                ?: throw IllegalArgumentException("Readium publication fingerprint is missing")
            val payload = root["payload"] as? JsonObject
                ?: throw IllegalArgumentException("Readium Locator payload must be a JSON object")
            return ReadiumLocatorEnvelope(
                platform = root.requiredEnum("platform", ReaderEnginePlatform.entries, ReaderEnginePlatform::wireValue),
                version = root.requiredString("version"),
                publication = PublicationFingerprint(
                    originalFileHash = publication.requiredString("originalFileHash"),
                    parser = publication.requiredString("parser"),
                    normalization = publication.requiredString("normalization"),
                ),
                payload = EngineLocatorPayload.parse(payload.toString()),
            )
        }
    }
}

/** Renderer-neutral projection used to verify navigation after `go(locator)`. */
data class ReadiumExactAnchor(
    val href: String,
    val cssSelector: String?,
    val fragments: Set<String>,
    val highlight: String?,
    val before: String?,
    val after: String?,
) {
    init {
        require(href.isNotBlank()) { "Readium Locator href is blank" }
        require(cssSelector != null || fragments.isNotEmpty() || highlight != null) {
            "Readium Locator requires a selector, fragment, CFI, or text anchor"
        }
    }
}

enum class ExactBlockMatch {
    Exact,
    FingerprintMismatch,
    ResourceMismatch,
    AnchorMismatch,
}

/**
 * Compares the expected remote Locator with the Locator recaptured after
 * navigation. A successful Navigator `go` call alone is never exact evidence.
 */
fun compareExactReadiumBlocks(
    expected: ReadiumLocatorEnvelope,
    recaptured: ReadiumLocatorEnvelope,
): ExactBlockMatch {
    if (expected.publication != recaptured.publication) return ExactBlockMatch.FingerprintMismatch
    val expectedAnchor = expected.exactAnchorOrNull() ?: return ExactBlockMatch.AnchorMismatch
    val actualAnchor = recaptured.exactAnchorOrNull() ?: return ExactBlockMatch.AnchorMismatch
    if (normalizeHref(expectedAnchor.href) != normalizeHref(actualAnchor.href)) {
        return ExactBlockMatch.ResourceMismatch
    }
    if (expectedAnchor.cssSelector != null && expectedAnchor.cssSelector == actualAnchor.cssSelector) {
        return ExactBlockMatch.Exact
    }
    if (expectedAnchor.fragments.intersect(actualAnchor.fragments).isNotEmpty()) {
        return ExactBlockMatch.Exact
    }
    if (expectedAnchor.highlight != null && actualAnchor.highlight != null) {
        val highlightMatches = normalizeText(expectedAnchor.highlight) == normalizeText(actualAnchor.highlight)
        val beforeMatches = matchingOptionalContext(expectedAnchor.before, actualAnchor.before)
        val afterMatches = matchingOptionalContext(expectedAnchor.after, actualAnchor.after)
        if (highlightMatches && beforeMatches && afterMatches) return ExactBlockMatch.Exact
    }
    return ExactBlockMatch.AnchorMismatch
}

/** Progress anchors remain valid when the publication bytes or parser version change. */
fun compareExactProgressReadiumBlocks(
    expected: ReadiumLocatorEnvelope,
    recaptured: ReadiumLocatorEnvelope,
): ExactBlockMatch = compareExactReadiumBlocks(
    expected,
    recaptured.copy(publication = expected.publication),
)

fun EngineLocatorPayload.hasExactReadiumBlockAnchor(): Boolean = toExactAnchorOrNull() != null

private fun EngineLocatorPayload.toExactAnchorOrNull(): ReadiumExactAnchor? {
    val root = runCatching { Json.parseToJsonElement(canonicalJson) as? JsonObject }.getOrNull() ?: return null
    val href = root.optionalString("href") ?: return null
    val mediaType = root.optionalString("type") ?: return null
    if (href.unicodeCodePointCount() > 8_192 || mediaType.unicodeCodePointCount() > 256) return null
    val locations = root["locations"] as? JsonObject ?: return null
    val progression = (locations["progression"] as? JsonPrimitive)?.doubleOrNull
    val totalProgression = (locations["totalProgression"] as? JsonPrimitive)?.doubleOrNull
    val position = (locations["position"] as? JsonPrimitive)?.intOrNull
    if (progression != null && (progression < 0.0 || progression > 1.0)) return null
    if (totalProgression != null && (totalProgression < 0.0 || totalProgression > 1.0)) return null
    if (position != null && position < 1) return null
    val cssSelector = locations.optionalString("cssSelector")
    val fragments = buildSet {
        (locations["fragments"] as? JsonArray)?.forEach { item ->
            (item as? JsonPrimitive)?.contentOrNull
                ?.takeIf { it.isNotBlank() && it.unicodeCodePointCount() <= 4_096 }
                ?.let(::add)
        }
        locations.optionalString("fragment")?.let(::add)
        locations.optionalString("cfi")?.let(::add)
    }
    if (fragments.size > 16 || cssSelector?.unicodeCodePointCount()?.let { it > 4_096 } == true) return null
    val text = root["text"] as? JsonObject
    val highlight = text?.optionalString("highlight")
    val before = text?.optionalString("before")
    val after = text?.optionalString("after")
    if (highlight != null && highlight.unicodeCodePointCount() > ReadiumLocatorEnvelope.MAXIMUM_HIGHLIGHT_LENGTH) return null
    if (before != null && before.unicodeCodePointCount() > ReadiumLocatorEnvelope.MAXIMUM_CONTEXT_LENGTH) return null
    if (after != null && after.unicodeCodePointCount() > ReadiumLocatorEnvelope.MAXIMUM_CONTEXT_LENGTH) return null
    if (cssSelector == null && fragments.isEmpty() && highlight == null) return null
    return runCatching {
        ReadiumExactAnchor(href, cssSelector, fragments, highlight, before, after)
    }.getOrNull()
}

private fun Char.isHexDigit(): Boolean = this in '0'..'9' || this in 'a'..'f' || this in 'A'..'F'

private fun normalizeHref(value: String): String = value.trim()

private fun normalizeText(value: String): String = value
    .normalizeUnicodeNfc()
    .trim()
    .replace(Regex("\\s+"), " ")

private fun matchingOptionalContext(expected: String?, actual: String?): Boolean =
    expected == null || (actual != null && normalizeText(expected) == normalizeText(actual))

private fun String.unicodeCodePointCount(): Int {
    var count = 0
    var index = 0
    while (index < length) {
        val current = this[index]
        index += if (
            current in '\uD800'..'\uDBFF' &&
            index + 1 < length &&
            this[index + 1] in '\uDC00'..'\uDFFF'
        ) {
            2
        } else {
            1
        }
        count += 1
    }
    return count
}

private fun JsonObject.optionalString(name: String): String? =
    (this[name] as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)

private fun JsonObject.requiredString(name: String): String = optionalString(name)
    ?: throw IllegalArgumentException("Readium Locator field $name is missing")

private fun <T> JsonObject.requiredEnum(name: String, values: List<T>, wireValue: (T) -> String): T {
    val raw = requiredString(name)
    return values.firstOrNull { wireValue(it) == raw }
        ?: throw IllegalArgumentException("Readium Locator field $name is unsupported")
}
