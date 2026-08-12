package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
import com.ermao.library.shared.modules.reader.domain.EngineLocator
import com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import com.ermao.library.shared.modules.reader.domain.ContentFingerprint
import com.ermao.library.shared.modules.reader.domain.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderEngine
import com.ermao.library.shared.modules.reader.domain.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderServerContentFingerprint
import com.ermao.library.shared.modules.reader.domain.ReaderPublicAnchor
import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.domain.TextQuote
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

class ReaderServerWireException(message: String, cause: Throwable? = null) :
    IllegalArgumentException(message, cause)

/** Strict mapping boundary between Reader domain and Reader v4 HTTP JSON. */
class ReaderServerWireMapper(
    private val json: Json = readerServerWireJson,
) {
    fun encodeProgressUpload(upload: ReaderProgressUpload): String {
        return json.encodeToString(
            ReaderProgressPutWire(
                clientId = upload.snapshot.clientId,
                updatedAtEpochMillis = upload.snapshot.updatedAtEpochMillis,
                percent = upload.snapshot.percent,
                location = upload.localLocation.toServerLocation(),
                contentFingerprint = upload.target.serverContentFingerprint.value,
            ),
        )
    }

    internal fun decodeSnapshot(
        response: ReaderProgressResponseWire,
        expectedSourceId: String,
    ): ReaderProgressSnapshotV4 = response.progress.toDomainSnapshot(expectedSourceId)

    internal fun responseSerializer() = ReaderProgressResponseWire.serializer()

    internal fun JsonObject.toDomainSnapshot(sourceId: String): ReaderProgressSnapshotV4 =
        ReaderProgressSnapshotV4(
            sourceId = sourceId,
            percent = requiredDouble("percent"),
            updatedAtEpochMillis = requiredLong("updatedAtEpochMillis"),
            clientId = requiredString("clientId"),
            serverContentFingerprint = ReaderServerContentFingerprint(requiredString("contentFingerprint")),
            anchor = (this["location"] as? JsonObject)?.toPublicAnchorOrNull(),
        )

    internal fun JsonObject.toDomainSnapshotWithoutAnchor(sourceId: String): ReaderProgressSnapshotV4 =
        ReaderProgressSnapshotV4(
            sourceId = sourceId,
            percent = requiredDouble("percent"),
            updatedAtEpochMillis = requiredLong("updatedAtEpochMillis"),
            clientId = requiredString("clientId"),
            serverContentFingerprint = ReaderServerContentFingerprint(requiredString("contentFingerprint")),
            anchor = null,
        )

    private fun ReaderLocation.toServerLocation(): JsonObject = when (this) {
        is ReflowReaderLocation -> buildJsonObject {
            put("kind", "reflow")
            resourceKey?.let { put("resourceKey", it) }
            progression?.let { put("progression", it) }
            position?.let { put("position", it) }
            textQuote?.let { put("textQuote", it.toJson()) }
            engineLocator?.let { put("engineLocator", it.toJson()) }
            put("contentFingerprint", contentFingerprint.toJson())
        }
        is PdfReaderLocation -> buildJsonObject {
            put("kind", "pdf")
            put("pageNumber", pageIndex + 1)
            engineLocator?.let { put("engineLocator", it.toJson()) }
        }
        is ComicReaderLocation -> buildJsonObject {
            put("kind", "comic")
            put("pageIndex", pageIndex + 1)
            engineLocator?.let { put("engineLocator", it.toJson()) }
        }
        is AudioReaderLocation -> buildJsonObject {
            put("kind", "audio")
            put("fileId", fileId)
            chapterId?.let { put("chapterId", it) }
            put("positionMs", positionMillis)
            engineLocator?.let { put("engineLocator", it.toJson()) }
        }
    }

    private fun JsonObject.toPublicAnchorOrNull(): ReaderPublicAnchor? = try {
        val kind = optionalString("kind") ?: return null
        if (kind == "pdf" || kind == "comic") {
            val pageNumber = this[if (kind == "pdf") "pageNumber" else "pageIndex"].intOrNull() ?: return null
            return ReaderPublicAnchor(
                format = if (kind == "pdf") ReaderFormat.Pdf else ReaderFormat.Comic,
                engineLocator = (this["engineLocator"] as? JsonObject)?.toEngineLocator(),
                pageNumber = pageNumber,
            )
        }
        if (kind == "audio") {
            return ReaderPublicAnchor(
                format = ReaderFormat.Audio,
                engineLocator = (this["engineLocator"] as? JsonObject)?.toEngineLocator(),
                fileId = requiredString("fileId"),
                chapterId = optionalString("chapterId"),
                positionMillis = requiredLong("positionMs"),
            )
        }
        if (kind != "reflow") return null
        val resourceKey = optionalString("resourceKey")
        val progression = this["progression"].doubleOrNull()
        val quoteObject = this["textQuote"] as? JsonObject
        val exact = quoteObject?.optionalString("exact")
        val locator = (this["engineLocator"] as? JsonObject)?.toEngineLocator()
        val position = this["position"].intOrNull()
        if (locator == null && resourceKey == null && progression == null && exact == null && position == null) return null
        ReaderPublicAnchor(
            contentFingerprint = (this["contentFingerprint"] as? JsonObject)?.toContentFingerprint(),
            engineLocator = locator,
            resourceKey = resourceKey,
            progression = progression,
            textQuote = exact?.let { TextQuote(it, quoteObject.optionalString("prefix"), quoteObject.optionalString("suffix")) },
            position = position,
        )
    } catch (_: IllegalArgumentException) {
        null
    }

    private fun EngineLocator.toJson() = buildJsonObject {
        put("engine", engine.wireValue)
        put("platform", platform.wireValue)
        put("version", version)
        put("payload", json.parseToJsonElement(payload.canonicalJson))
    }

    private fun JsonObject.toEngineLocator() = EngineLocator(
        engine = requiredEnum("engine", ReaderEngine.entries, ReaderEngine::wireValue),
        platform = requiredEnum("platform", ReaderEnginePlatform.entries, ReaderEnginePlatform::wireValue),
        version = requiredString("version"),
        payload = EngineLocatorPayload.parse(
            (this["payload"] as? JsonObject)?.toString()
                ?: throw ReaderServerWireException("Reader server engine payload is not an object"),
        ),
    )

    private fun TextQuote.toJson() = buildJsonObject {
        put("exact", exact)
        prefix?.let { put("prefix", it) }
        suffix?.let { put("suffix", it) }
    }

    private fun ContentFingerprint.toJson() = buildJsonObject {
        put("originalFileHash", originalFileHash)
        put("parserVersion", parserVersion)
        put("normalizationVersion", normalizationVersion)
    }

    private fun JsonObject.toContentFingerprint() = ContentFingerprint(
        requiredString("originalFileHash"),
        requiredString("parserVersion"),
        requiredString("normalizationVersion"),
    )
}

@Serializable
internal data class ReaderProgressPutWire(
    val schemaVersion: Int = READER_SERVER_SCHEMA_VERSION,
    val clientId: String,
    val updatedAtEpochMillis: Long,
    val percent: Double,
    val location: JsonObject?,
    /** Server-issued publication token, never a local structured fingerprint. */
    val contentFingerprint: String,
)

@Serializable
internal data class ReaderProgressResponseWire(val progress: JsonObject)

internal const val READER_SERVER_SCHEMA_VERSION = 4

internal val readerServerWireJson = Json {
    encodeDefaults = true
    explicitNulls = false
    ignoreUnknownKeys = false
}

private fun JsonElement?.longOrNull(): Long? = (this as? JsonPrimitive)?.longOrNull
private fun JsonElement?.intOrNull(): Int? = (this as? JsonPrimitive)?.intOrNull
private fun JsonElement?.doubleOrNull(): Double? = (this as? JsonPrimitive)?.doubleOrNull

private fun JsonObject.optionalString(name: String): String? =
    (this[name] as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)

private fun JsonObject.requiredString(name: String): String = optionalString(name)
    ?: throw ReaderServerWireException("Reader server field $name is missing")

private fun JsonObject.requiredLong(name: String): Long = this[name].longOrNull()
    ?: throw ReaderServerWireException("Reader server field $name is missing")

private fun JsonObject.requiredDouble(name: String): Double = this[name].doubleOrNull()
    ?: throw ReaderServerWireException("Reader server field $name is missing")

private fun <T> JsonObject.requiredEnum(name: String, values: List<T>, wireValue: (T) -> String): T {
    val raw = requiredString(name)
    return values.firstOrNull { wireValue(it) == raw }
        ?: throw ReaderServerWireException("Reader server field $name is unsupported")
}
