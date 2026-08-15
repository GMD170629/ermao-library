package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/** Renderer-neutral exact publication location shared by Reader clients and Reader v4. */
sealed interface PublicationLocation {
    val engineLocator: EngineLocator?

    val platform: ReaderEnginePlatform?
        get() = engineLocator?.platform

    fun asEngineLocator(): EngineLocator = engineLocator
        ?: throw IllegalStateException("Publication location has no engine locator")

    fun canonicalJson(): String = toJson().toString()

    companion object {
        const val MAXIMUM_ENVELOPE_BYTES = 65_536

        fun parse(value: String): PublicationLocation {
            require(value.encodeToByteArray().size <= MAXIMUM_ENVELOPE_BYTES) {
                "Publication location exceeds 64 KiB"
            }
            val root = runCatching { Json.parseToJsonElement(value) as? JsonObject }.getOrNull()
                ?: throw IllegalArgumentException("Publication location must be a JSON object")
            val engineLocator = root.optionalObject("engineLocator")?.toEngineLocator()
            return when (root.requiredString("kind")) {
                "reflowable" -> root.requireOnly("kind", "engineLocator", "publication").let { ReflowablePublicationLocation(
                    engineLocator = engineLocator
                        ?: throw IllegalArgumentException("Reflowable publication location requires an engine locator"),
                ) }
                "pdf" -> root.requireOnly(
                    "kind", "pageIndex", "pageProgression", "engineLocator", "publication",
                ).let { PdfPublicationLocation(
                    pageIndex = root.requiredInt("pageIndex"),
                    pageProgression = root.requiredCanonicalPageProgression("pageProgression"),
                    engineLocator = engineLocator,
                ) }
                "comic" -> root.requireOnly(
                    "kind", "resourceHref", "pageIndex", "engineLocator", "publication",
                ).let { ComicPublicationLocation(
                    resourceHref = root.requiredString("resourceHref"),
                    pageIndex = root.requiredInt("pageIndex"),
                    engineLocator = engineLocator,
                ) }
                "audio" -> root.requireOnly(
                    "kind", "fileId", "chapterId", "positionMillis", "engineLocator", "publication",
                ).let { AudioPublicationLocation(
                    fileId = root.requiredString("fileId"),
                    chapterId = root.optionalString("chapterId"),
                    positionMillis = root.requiredLong("positionMillis"),
                    engineLocator = engineLocator,
                ) }
                else -> throw IllegalArgumentException("Publication location kind is unsupported")
            }.also {
                require(it.canonicalJson().encodeToByteArray().size <= MAXIMUM_ENVELOPE_BYTES) {
                    "Publication location exceeds 64 KiB"
                }
            }
        }
    }
}

data class ReflowablePublicationLocation(
    override val engineLocator: EngineLocator,
) : PublicationLocation {
    init {
        require(engineLocator.engine == ReaderEngine.Readium) { "Reflowable location requires Readium" }
        ReadiumLocatorEnvelope(
            platform = engineLocator.platform,
            version = engineLocator.version,
            payload = engineLocator.payload,
        )
    }

    val readiumEnvelope: ReadiumLocatorEnvelope
        get() = ReadiumLocatorEnvelope(
            platform = engineLocator.platform,
            version = engineLocator.version,
            payload = engineLocator.payload,
        )
}

class PdfPublicationLocation(
    val pageIndex: Int,
    pageProgression: Double,
    override val engineLocator: EngineLocator? = null,
) : PublicationLocation {
    val pageProgression: Double = canonicalPageProgression(pageProgression)

    init {
        require(pageIndex >= 0) { "PDF page index is negative" }
        require(pageProgression.isFinite() && pageProgression in 0.0..1.0) {
            "PDF page progression is outside 0..1"
        }
    }

    override fun equals(other: Any?): Boolean = other is PdfPublicationLocation &&
        pageIndex == other.pageIndex &&
        pageProgression == other.pageProgression && engineLocator == other.engineLocator

    override fun hashCode(): Int = 31 * (31 * pageIndex + pageProgression.hashCode()) +
        (engineLocator?.hashCode() ?: 0)

    override fun toString(): String =
        "PdfPublicationLocation(pageIndex=$pageIndex, " +
            "pageProgression=$pageProgression, engineLocator=$engineLocator)"
}

data class ComicPublicationLocation(
    val resourceHref: String,
    val pageIndex: Int,
    override val engineLocator: EngineLocator? = null,
) : PublicationLocation {
    init {
        requireSafeResourceHref(resourceHref)
        require(pageIndex >= 0) { "Comic page index is negative" }
    }
}

data class AudioPublicationLocation(
    val fileId: String,
    val chapterId: String? = null,
    val positionMillis: Long,
    override val engineLocator: EngineLocator? = null,
) : PublicationLocation {
    init {
        require(fileId.isNotBlank()) { "Audio file id is blank" }
        require(chapterId == null || chapterId.isNotBlank()) { "Audio chapter id is blank" }
        require(positionMillis >= 0) { "Audio position is negative" }
    }
}

enum class ExactLocationMatch { Exact, MorphologyMismatch, AnchorMismatch }

fun compareExactPublicationLocations(
    expected: PublicationLocation,
    actual: PublicationLocation,
): ExactLocationMatch {
    if (expected::class != actual::class) return ExactLocationMatch.MorphologyMismatch
    return when (expected) {
        is ReflowablePublicationLocation -> {
            val candidate = actual as ReflowablePublicationLocation
            when (compareExactReadiumBlocks(expected.readiumEnvelope, candidate.readiumEnvelope)) {
                ExactBlockMatch.Exact -> ExactLocationMatch.Exact
                else -> ExactLocationMatch.AnchorMismatch
            }
        }
        is PdfPublicationLocation -> (actual as PdfPublicationLocation).let {
            if (expected.pageIndex == it.pageIndex &&
                expected.pageProgression == it.pageProgression
            ) ExactLocationMatch.Exact else ExactLocationMatch.AnchorMismatch
        }
        is ComicPublicationLocation -> (actual as ComicPublicationLocation).let {
            if (expected.pageIndex == it.pageIndex && normalizeResourceHref(expected.resourceHref) == normalizeResourceHref(it.resourceHref)) {
                ExactLocationMatch.Exact
            } else ExactLocationMatch.AnchorMismatch
        }
        is AudioPublicationLocation -> (actual as AudioPublicationLocation).let {
            if (expected.fileId == it.fileId && expected.chapterId == it.chapterId && expected.positionMillis == it.positionMillis) {
                ExactLocationMatch.Exact
            } else ExactLocationMatch.AnchorMismatch
        }
    }
}

fun compareExactProgressLocations(
    expected: PublicationLocation,
    actual: PublicationLocation,
): ExactLocationMatch = compareExactPublicationLocations(expected, actual)

private fun PublicationLocation.toJson(): JsonObject = buildJsonObject {
    put("kind", when (this@toJson) {
        is ReflowablePublicationLocation -> "reflowable"
        is PdfPublicationLocation -> "pdf"
        is ComicPublicationLocation -> "comic"
        is AudioPublicationLocation -> "audio"
    })
    when (val location = this@toJson) {
        is ReflowablePublicationLocation -> put("engineLocator", location.engineLocator.toJson())
        is PdfPublicationLocation -> {
            put("pageIndex", location.pageIndex)
            put("pageProgression", location.pageProgression)
            location.engineLocator?.let { put("engineLocator", it.toJson()) }
        }
        is ComicPublicationLocation -> {
            put("resourceHref", location.resourceHref)
            put("pageIndex", location.pageIndex)
            location.engineLocator?.let { put("engineLocator", it.toJson()) }
        }
        is AudioPublicationLocation -> {
            put("fileId", location.fileId)
            location.chapterId?.let { put("chapterId", it) }
            put("positionMillis", location.positionMillis)
            location.engineLocator?.let { put("engineLocator", it.toJson()) }
        }
    }
}

private fun EngineLocator.toJson() = buildJsonObject {
    put("engine", engine.wireValue)
    put("platform", platform.wireValue)
    put("version", version)
    put("payload", Json.parseToJsonElement(payload.canonicalJson))
}

private fun JsonObject.toEngineLocator() = requireOnly("engine", "platform", "version", "payload").let {
    EngineLocator(
        engine = requiredEnum("engine", ReaderEngine.entries, ReaderEngine::wireValue),
        platform = requiredEnum("platform", ReaderEnginePlatform.entries, ReaderEnginePlatform::wireValue),
        version = requiredString("version"),
        payload = EngineLocatorPayload.parse(requiredObject("payload").toString()),
    )
}

private fun JsonObject.requireOnly(vararg allowed: String): JsonObject {
    require(keys.all(allowed.toSet()::contains)) { "Publication location contains unsupported fields" }
    return this
}

private fun requireSafeResourceHref(value: String) {
    require(value.isNotBlank() && value.length <= 8_192) { "Comic resource href is invalid" }
    require(!value.startsWith('/') && !value.contains('\\')) { "Comic resource href is not relative" }
    require(!Regex("^[A-Za-z][A-Za-z0-9+.-]*:").containsMatchIn(value)) { "Comic resource href has a scheme" }
    require(value.split('/').none { it == ".." }) { "Comic resource href escapes the publication" }
}

private fun normalizeResourceHref(value: String): String = value.split('/').filter { it.isNotEmpty() && it != "." }.joinToString("/")
private fun canonicalPageProgression(value: Double): Double = kotlin.math.round(value * 10_000.0) / 10_000.0
private fun JsonObject.optionalString(name: String): String? = (this[name] as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)
private fun JsonObject.requiredString(name: String): String = optionalString(name)
    ?: throw IllegalArgumentException("Publication location field $name is missing")
private fun JsonObject.requiredObject(name: String): JsonObject = this[name] as? JsonObject
    ?: throw IllegalArgumentException("Publication location field $name is missing")
private fun JsonObject.optionalObject(name: String): JsonObject? = this[name] as? JsonObject
private fun JsonObject.requiredInt(name: String): Int = (this[name] as? JsonPrimitive)?.intOrNull
    ?: throw IllegalArgumentException("Publication location field $name is missing")
private fun JsonObject.requiredLong(name: String): Long = (this[name] as? JsonPrimitive)?.longOrNull
    ?: throw IllegalArgumentException("Publication location field $name is missing")
private fun JsonObject.requiredDouble(name: String): Double = (this[name] as? JsonPrimitive)?.doubleOrNull
    ?: throw IllegalArgumentException("Publication location field $name is missing")
private fun JsonObject.requiredCanonicalPageProgression(name: String): Double = requiredDouble(name).also {
    require(it.isFinite() && it in 0.0..1.0 && it == canonicalPageProgression(it)) {
        "PDF page progression must be canonical to four decimals"
    }
}
private fun <T> JsonObject.requiredEnum(name: String, values: List<T>, wireValue: (T) -> String): T {
    val raw = requiredString(name)
    return values.firstOrNull { wireValue(it) == raw }
        ?: throw IllegalArgumentException("Publication location field $name is unsupported")
}
