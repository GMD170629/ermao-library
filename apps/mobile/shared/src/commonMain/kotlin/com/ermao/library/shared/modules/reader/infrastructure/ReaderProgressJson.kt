package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
import com.ermao.library.shared.modules.reader.domain.EngineLocator
import com.ermao.library.shared.modules.reader.domain.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderEngine
import com.ermao.library.shared.modules.reader.domain.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.domain.TextQuote
import com.ermao.library.shared.modules.reader.domain.exactPublicationLocation
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

/** Local exact Reader progress. Reader v4 is pre-release, so no legacy document is accepted. */
class ReaderProgressJson(
    private val json: Json = defaultReaderProgressJson,
) {
    @Throws(ReaderProgressDocumentException::class)
    fun encode(progress: ReaderProgress): String = try {
        progress.exactPublicationLocation()
        json.encodeToString(progress.toWire())
    } catch (error: SerializationException) {
        throw ReaderProgressDocumentException("Reader progress could not be encoded", error)
    }

    @Throws(ReaderProgressDocumentException::class)
    fun decode(payload: String): ReaderProgress {
        val document = try {
            json.decodeFromString<ReaderProgressDocumentWire>(payload)
        } catch (error: SerializationException) {
            throw ReaderProgressDocumentException("Reader progress document is malformed", error)
        }
        if (document.schema != SCHEMA_NAME || document.version !in SUPPORTED_VERSIONS) {
            throw ReaderProgressDocumentException("Reader progress schema is unsupported")
        }
        return try {
            document.toDomain().also { it.exactPublicationLocation() }
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
        )
        is PdfReaderLocation -> PdfLocationWire(
            pageIndex = pageIndex,
            pageProgression = pageProgression,
            engineLocator = engineLocator?.toWire(),
        )
        is ComicReaderLocation -> ComicLocationWire(
            resourceHref = resourceHref,
            pageIndex = pageIndex,
            engineLocator = engineLocator?.toWire(),
        )
        is AudioReaderLocation -> AudioLocationWire(
            fileId = fileId,
            chapterId = chapterId,
            positionMillis = positionMillis,
            engineLocator = engineLocator?.toWire(),
        )
    }

    private fun ReaderProgressDocumentWire.toDomain() = ReaderProgress(
        sourceId,
        location.toDomain(),
        updatedAtEpochMillis,
        deviceId,
        percent,
    )

    private fun ReaderLocationWire.toDomain(): ReaderLocation = when (this) {
        is ReflowLocationWire -> {
            ReflowReaderLocation(
                resourceKey,
                progression,
                totalProgression,
                position,
                textQuote?.let { TextQuote(it.exact, it.prefix, it.suffix) },
                engineLocator?.toEngineLocator(),
            )
        }
        is PdfLocationWire -> {
            PdfReaderLocation(pageIndex, pageProgression, engineLocator?.toEngineLocator())
        }
        is ComicLocationWire -> {
            ComicReaderLocation(resourceHref, pageIndex, engineLocator?.toEngineLocator())
        }
        is AudioLocationWire -> {
            AudioReaderLocation(
                fileId,
                chapterId,
                positionMillis,
                engineLocator?.toEngineLocator(),
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

    private fun JsonObject.toEngineLocator(): EngineLocator = EngineLocator(
            engine = requiredEnum("engine", ReaderEngine.entries, ReaderEngine::wireValue),
            platform = requiredEnum("platform", ReaderEnginePlatform.entries, ReaderEnginePlatform::wireValue),
            version = requiredString("version"),
            payload = payloadObject(),
        )
}

private const val SCHEMA_NAME = "ermao.reader-progress"
private const val SCHEMA_VERSION = 6
private val SUPPORTED_VERSIONS = setOf(SCHEMA_VERSION)

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
) : ReaderLocationWire

@Serializable
@SerialName("pdf")
private data class PdfLocationWire(
    val pageIndex: Int,
    val pageProgression: Double,
    val engineLocator: JsonObject? = null,
) : ReaderLocationWire

@Serializable
@SerialName("comic")
private data class ComicLocationWire(
    val resourceHref: String,
    val pageIndex: Int,
    val engineLocator: JsonObject? = null,
) : ReaderLocationWire

@Serializable
@SerialName("audio")
private data class AudioLocationWire(
    val fileId: String,
    val chapterId: String? = null,
    val positionMillis: Long,
    val engineLocator: JsonObject? = null,
) : ReaderLocationWire

@Serializable
private data class TextQuoteWire(val exact: String, val prefix: String? = null, val suffix: String? = null)

private fun JsonObject.requiredString(name: String): String =
    (this[name] as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)
        ?: throw ReaderProgressDocumentException("Reader progress field $name is missing")

private fun JsonObject.payloadObject(): EngineLocatorPayload {
    val element = this["payload"] as? JsonObject
        ?: throw ReaderProgressDocumentException("Reader progress field payload must be an object")
    return EngineLocatorPayload.parse(element.toString())
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
