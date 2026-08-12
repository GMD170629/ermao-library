package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
import com.ermao.library.shared.modules.reader.domain.ContentFingerprint
import com.ermao.library.shared.modules.reader.domain.EngineLocator
import com.ermao.library.shared.modules.reader.domain.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderEngine
import com.ermao.library.shared.modules.reader.domain.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.domain.TextQuote
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

class ReaderProgressDocumentException(message: String, cause: Throwable? = null) :
    IllegalArgumentException(message, cause)

/** Local exact Reader progress. Encoder writes v4; decoder migrates v1 documents. */
class ReaderProgressJson(
    private val json: Json = defaultReaderProgressJson,
) {
    fun encode(progress: ReaderProgress): String = try {
        json.encodeToString(progress.toWire())
    } catch (error: SerializationException) {
        throw ReaderProgressDocumentException("Reader progress could not be encoded", error)
    }

    fun decode(payload: String): ReaderProgress {
        val document = try {
            json.decodeFromString<ReaderProgressDocumentWire>(payload)
        } catch (error: SerializationException) {
            throw ReaderProgressDocumentException("Reader progress document is malformed", error)
        }
        if (document.schema != SCHEMA_NAME || document.version !in setOf(LEGACY_SCHEMA_VERSION, SCHEMA_VERSION)) {
            throw ReaderProgressDocumentException("Reader progress schema is unsupported")
        }
        return try {
            document.toDomain()
        } catch (error: IllegalArgumentException) {
            throw ReaderProgressDocumentException("Reader progress document is invalid", error)
        }
    }

    private fun ReaderProgress.toWire() = ReaderProgressDocumentWire(
        sourceId = sourceId,
        location = location.toWire(),
        updatedAtEpochMillis = updatedAtEpochMillis,
        deviceId = deviceId,
        percent = percent,
    )

    private fun ReaderLocation.toWire(): ReaderLocationWire = when (this) {
        is ReflowReaderLocation -> ReflowLocationWire(
            resourceKey,
            progression,
            totalProgression,
            position,
            textQuote?.let { TextQuoteWire(it.exact, it.prefix, it.suffix) },
            engineLocator?.toWire(),
            contentFingerprint.toWire(),
        )
        is PdfReaderLocation -> PdfLocationWire(
            pageIndex,
            pageProgression,
            contentFingerprint.toWire(),
            engineLocator?.toWire(),
        )
        is ComicReaderLocation -> ComicLocationWire(pageIndex, contentFingerprint.toWire(), engineLocator?.toWire())
        is AudioReaderLocation -> AudioLocationWire(
            fileId,
            chapterId,
            positionMillis,
            contentFingerprint.toWire(),
            engineLocator?.toWire(),
        )
    }

    private fun ReaderProgressDocumentWire.toDomain() = ReaderProgress(
        sourceId,
        location.toDomain(version),
        updatedAtEpochMillis,
        deviceId,
        percent,
    )

    private fun ReaderLocationWire.toDomain(version: Int): ReaderLocation = when (this) {
        is ReflowLocationWire -> {
            val fingerprint = contentFingerprint.toDomain()
            ReflowReaderLocation(
                resourceKey,
                progression,
                totalProgression,
                position,
                textQuote?.let { TextQuote(it.exact, it.prefix, it.suffix) },
                engineLocator?.toEngineLocator(version, fingerprint),
                fingerprint,
            )
        }
        is PdfLocationWire -> {
            val fingerprint = contentFingerprint.toDomain()
            PdfReaderLocation(pageIndex, pageProgression, fingerprint, engineLocator?.toEngineLocator(version, fingerprint))
        }
        is ComicLocationWire -> {
            val fingerprint = contentFingerprint.toDomain()
            ComicReaderLocation(pageIndex, fingerprint, engineLocator?.toEngineLocator(version, fingerprint))
        }
        is AudioLocationWire -> {
            val fingerprint = contentFingerprint.toDomain()
            AudioReaderLocation(
                fileId,
                chapterId,
                positionMillis,
                fingerprint,
                engineLocator?.toEngineLocator(version, fingerprint),
            )
        }
    }

    private fun EngineLocator.toWire(): JsonObject = JsonObject(
        mapOf(
            "engine" to JsonPrimitive(engine.wireValue),
            "platform" to JsonPrimitive(platform.wireValue),
            "version" to JsonPrimitive(version),
            "payload" to json.parseToJsonElement(payload.canonicalJson),
        ),
    )

    private fun JsonObject.toEngineLocator(version: Int, fingerprint: ContentFingerprint): EngineLocator {
        if (version == LEGACY_SCHEMA_VERSION) {
            val parser = fingerprint.parserVersion.lowercase()
            return EngineLocator(
                engine = if ("foliate" in parser) ReaderEngine.Foliate else ReaderEngine.Readium,
                platform = when {
                    "swift" in parser -> ReaderEnginePlatform.Ios
                    "foliate" in parser -> ReaderEnginePlatform.Web
                    else -> ReaderEnginePlatform.Android
                },
                version = fingerprint.parserVersion.substringAfter(':', "legacy"),
                payload = EngineLocatorPayload.parse(json.encodeToString(JsonObject.serializer(), this)),
            )
        }
        return EngineLocator(
            engine = requiredEnum("engine", ReaderEngine.entries, ReaderEngine::wireValue),
            platform = requiredEnum("platform", ReaderEnginePlatform.entries, ReaderEnginePlatform::wireValue),
            version = requiredString("version"),
            payload = payloadObject(),
        )
    }
}

private const val SCHEMA_NAME = "ermao.reader-progress"
private const val LEGACY_SCHEMA_VERSION = 1
private const val SCHEMA_VERSION = 4

private val defaultReaderProgressJson = Json {
    classDiscriminator = "kind"
    encodeDefaults = true
    explicitNulls = false
    ignoreUnknownKeys = true
}

@Serializable
private data class ReaderProgressDocumentWire(
    val schema: String = SCHEMA_NAME,
    val version: Int = SCHEMA_VERSION,
    val sourceId: String,
    val location: ReaderLocationWire,
    val updatedAtEpochMillis: Long,
    val deviceId: String,
    val percent: Double? = null,
)

@Serializable
private sealed interface ReaderLocationWire

@Serializable
@SerialName("reflow")
private data class ReflowLocationWire(
    val resourceKey: String? = null,
    val progression: Double? = null,
    val totalProgression: Double? = null,
    val position: Int? = null,
    val textQuote: TextQuoteWire? = null,
    val engineLocator: JsonObject? = null,
    val contentFingerprint: ContentFingerprintWire,
) : ReaderLocationWire

@Serializable
@SerialName("pdf")
private data class PdfLocationWire(
    val pageIndex: Int,
    val pageProgression: Double? = null,
    val contentFingerprint: ContentFingerprintWire,
    val engineLocator: JsonObject? = null,
) : ReaderLocationWire

@Serializable
@SerialName("comic")
private data class ComicLocationWire(
    val pageIndex: Int,
    val contentFingerprint: ContentFingerprintWire,
    val engineLocator: JsonObject? = null,
) : ReaderLocationWire

@Serializable
@SerialName("audio")
private data class AudioLocationWire(
    val fileId: String,
    val chapterId: String? = null,
    val positionMillis: Long,
    val contentFingerprint: ContentFingerprintWire,
    val engineLocator: JsonObject? = null,
) : ReaderLocationWire

@Serializable
private data class TextQuoteWire(val exact: String, val prefix: String? = null, val suffix: String? = null)

@Serializable
private data class ContentFingerprintWire(
    val originalFileHash: String,
    val parserVersion: String,
    val normalizationVersion: String,
)

private fun ContentFingerprint.toWire() = ContentFingerprintWire(
    originalFileHash,
    parserVersion,
    normalizationVersion,
)

private fun ContentFingerprintWire.toDomain() = ContentFingerprint(
    originalFileHash,
    parserVersion,
    normalizationVersion,
)

private fun JsonObject.requiredString(name: String): String =
    (this[name] as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)
        ?: throw ReaderProgressDocumentException("Reader progress field $name is missing")

private fun JsonObject.payloadObject(): EngineLocatorPayload {
    val element = this["payload"] ?: throw ReaderProgressDocumentException("Reader progress field payload is missing")
    // A short-lived pre-release v4 encoder wrote the object as a JSON string.
    val raw = if (element is JsonPrimitive && element.isString) element.content else element.toString()
    return EngineLocatorPayload.parse(raw)
}

private fun <T> JsonObject.requiredEnum(
    name: String,
    values: List<T>,
    wireValue: (T) -> String,
): T {
    val raw = requiredString(name)
    return values.firstOrNull { wireValue(it) == raw }
        ?: throw ReaderProgressDocumentException("Reader progress field $name is unsupported")
}
