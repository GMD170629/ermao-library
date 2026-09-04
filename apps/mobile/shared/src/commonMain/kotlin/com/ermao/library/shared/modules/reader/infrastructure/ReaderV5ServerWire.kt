package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ReaderPositionUpload
import com.ermao.library.shared.modules.reader.application.ReaderPositionWriteResponse
import com.ermao.library.shared.modules.reader.domain.ReaderChapterPresentation
import com.ermao.library.shared.modules.reader.domain.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.domain.ReaderPagePresentation
import com.ermao.library.shared.modules.reader.domain.ReaderPlaybackPresentation
import com.ermao.library.shared.modules.reader.domain.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.domain.ReaderPositionReport
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.domain.requireReaderClientId
import com.ermao.library.shared.modules.reader.domain.requireReaderMutationId
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

class ReaderServerWireException(message: String, cause: Throwable? = null) :
    IllegalArgumentException(message, cause)

class ReaderV5ServerWireMapper(
    private val json: Json = readerV5ServerWireJson,
) {
    fun encodeProgressUpload(upload: ReaderPositionUpload): String = buildJsonObject {
        put("schemaVersion", READER_V5_SCHEMA_VERSION)
        put("clientId", upload.mutation.clientId)
        put("mutationId", upload.mutation.mutationId)
        put("capturedAtEpochMillis", upload.mutation.capturedAtEpochMillis)
        put("position", encodePosition(upload.mutation.position))
    }.toString()

    internal fun responseSerializer() = JsonObject.serializer()

    fun decodeWriteResponse(payload: String, expectedResourceId: String): ReaderPositionWriteResponse {
        val root = parseObject(payload, "Reader v5 progress response")
        requireTrue(root.requiredBoolean("ok"), "Reader v5 progress response is unsuccessful")
        val data = root.requiredObject("data")
        requireKeys(data, setOf("acceptedMutationId", "acceptedRevision", "currentSnapshot"))
        val acceptedMutationId = requireReaderMutationId(data.requiredString("acceptedMutationId"))
        val acceptedRevision = data.requiredLong("acceptedRevision")
        val snapshot = decodeSnapshot(data.requiredObject("currentSnapshot"), expectedResourceId)
        return ReaderPositionWriteResponse(acceptedMutationId, acceptedRevision, snapshot)
    }

    fun decodeProgressState(payload: String, expectedResourceId: String): ReaderProgressSnapshotV5? {
        val root = parseObject(payload, "Reader v5 progress response")
        requireTrue(root.requiredBoolean("ok"), "Reader v5 progress response is unsuccessful")
        val data = root.requiredObject("data")
        requireKeys(data, setOf("schemaVersion", "progressSnapshot"))
        requireSchema(data.requiredLong("schemaVersion"))
        val value = data["progressSnapshot"]
        if (value == null || value == JsonNull) return null
        return if (value is JsonObject) {
            decodeSnapshot(value, expectedResourceId)
        } else {
            throw ReaderServerWireException("Reader v5 progress snapshot is malformed")
        }
    }

    internal fun decodeSnapshot(root: JsonObject, expectedResourceId: String): ReaderProgressSnapshotV5 {
        requireKeys(
            root,
            setOf(
                "schemaVersion",
                "revision",
                "clientId",
                "mutationId",
                "capturedAtEpochMillis",
                "receivedAtEpochMillis",
                "position",
            ),
        )
        requireSchema(root.requiredLong("schemaVersion"))
        return ReaderProgressSnapshotV5(
            resourceId = expectedResourceId,
            clientId = requireReaderClientId(root.requiredString("clientId")),
            revision = root.requiredLong("revision"),
            mutationId = requireReaderMutationId(root.requiredString("mutationId")),
            capturedAtEpochMillis = root.requiredLong("capturedAtEpochMillis"),
            receivedAtEpochMillis = root.requiredLong("receivedAtEpochMillis"),
            position = decodePosition(root.requiredObject("position")),
        )
    }

    internal fun encodePosition(position: ReaderPositionReport): JsonObject = buildJsonObject {
        put("locator", json.parseToJsonElement(position.locator.canonicalJson))
        put("presentation", encodePresentation(position.presentation))
    }

    private fun encodePresentation(presentation: ReaderPositionPresentation): JsonObject = buildJsonObject {
        put("displayPercent", presentation.displayPercent)
        put("totalProgression", presentation.totalProgression)
        if (presentation.currentHref != null) put("currentHref", presentation.currentHref)
        else put("currentHref", JsonNull)
        if (presentation.chapter != null) put("chapter", encodeChapter(presentation.chapter))
        else put("chapter", JsonNull)
        if (presentation.page != null) put("page", encodePage(presentation.page))
        else put("page", JsonNull)
        if (presentation.playback != null) put("playback", encodePlayback(presentation.playback))
        else put("playback", JsonNull)
    }

    private fun encodeChapter(chapter: ReaderChapterPresentation): JsonObject = buildJsonObject {
        if (chapter.href != null) put("href", chapter.href) else put("href", JsonNull)
        if (chapter.title != null) put("title", chapter.title) else put("title", JsonNull)
        if (chapter.index != null) put("index", chapter.index) else put("index", JsonNull)
    }

    private fun encodePage(page: ReaderPagePresentation): JsonObject = buildJsonObject {
        put("number", page.number)
        if (page.total != null) put("total", page.total) else put("total", JsonNull)
    }

    private fun encodePlayback(playback: ReaderPlaybackPresentation): JsonObject = buildJsonObject {
        put("positionMillis", playback.positionMillis)
        if (playback.durationMillis != null) put("durationMillis", playback.durationMillis)
        else put("durationMillis", JsonNull)
    }

    internal fun decodePosition(root: JsonObject): ReaderPositionReport {
        requireKeys(root, setOf("locator", "presentation"))
        val locator = root["locator"] as? JsonObject
            ?: throw ReaderServerWireException("Reader v5 Locator is missing")
        return ReaderPositionReport(
            locator = ReaderOpaqueLocator.parse(locator.toString()),
            presentation = decodePresentation(root.requiredObject("presentation")),
        )
    }

    private fun decodePresentation(root: JsonObject): ReaderPositionPresentation {
        requireKeys(
            root,
            setOf("displayPercent", "totalProgression", "currentHref", "chapter", "page", "playback"),
        )
        return ReaderPositionPresentation(
            displayPercent = root.requiredDouble("displayPercent"),
            totalProgression = root.requiredDouble("totalProgression"),
            currentHref = root.requiredNullableString("currentHref"),
            chapter = root.requiredNullableObject("chapter")?.let(::decodeChapter),
            page = root.requiredNullableObject("page")?.let(::decodePage),
            playback = root.requiredNullableObject("playback")?.let(::decodePlayback),
        )
    }

    private fun decodeChapter(root: JsonObject): ReaderChapterPresentation {
        requireKeys(root, setOf("href", "title", "index"))
        return ReaderChapterPresentation(
            href = root.requiredNullableString("href"),
            title = root.requiredNullableString("title"),
            index = root.requiredNullableInt("index"),
        )
    }

    private fun decodePage(root: JsonObject): ReaderPagePresentation {
        requireKeys(root, setOf("number", "total"))
        return ReaderPagePresentation(
            number = root.requiredInt("number"),
            total = root.requiredNullableInt("total"),
        )
    }

    private fun decodePlayback(root: JsonObject): ReaderPlaybackPresentation {
        requireKeys(root, setOf("positionMillis", "durationMillis"))
        return ReaderPlaybackPresentation(
            positionMillis = root.requiredLong("positionMillis"),
            durationMillis = root.requiredNullableLong("durationMillis"),
        )
    }

    private fun parseObject(payload: String, label: String): JsonObject = runCatching {
        json.parseToJsonElement(payload).jsonObject
    }.getOrElse { throw ReaderServerWireException("$label is malformed", it) }

    private fun requireSchema(value: Long) {
        if (value != READER_V5_SCHEMA_VERSION.toLong()) {
            throw ReaderServerWireException("Reader v5 progress schema is unsupported")
        }
    }

    private fun requireTrue(value: Boolean, message: String) {
        if (!value) throw ReaderServerWireException(message)
    }

    companion object {
        const val READER_V5_SCHEMA_VERSION = 5
    }
}

internal val readerV5ServerWireJson: Json = Json {
    encodeDefaults = true
    explicitNulls = true
    ignoreUnknownKeys = false
}

private fun requireKeys(root: JsonObject, expected: Set<String>) {
    if (root.keys != expected) throw ReaderServerWireException("Reader v5 progress fields are unsupported")
}

private fun JsonObject.requiredPrimitive(name: String): JsonPrimitive = this[name] as? JsonPrimitive
    ?: throw ReaderServerWireException("Reader v5 progress field $name is missing")

private fun JsonObject.requiredObject(name: String): JsonObject = this[name] as? JsonObject
    ?: throw ReaderServerWireException("Reader v5 progress field $name is missing")

private fun JsonObject.requiredBoolean(name: String): Boolean = requiredPrimitive(name)
    .takeIf { !it.isString }?.booleanOrNull
    ?: throw ReaderServerWireException("Reader v5 progress field $name is invalid")

private fun JsonObject.requiredDouble(name: String): Double = requiredPrimitive(name)
    .takeIf { !it.isString }?.doubleOrNull
    ?: throw ReaderServerWireException("Reader v5 progress field $name is missing")

private fun JsonObject.requiredLong(name: String): Long = requiredPrimitive(name)
    .takeIf { !it.isString }?.longOrNull
    ?: throw ReaderServerWireException("Reader v5 progress field $name is missing")

private fun JsonObject.requiredInt(name: String): Int = requiredPrimitive(name)
    .takeIf { !it.isString }?.intOrNull
    ?: throw ReaderServerWireException("Reader v5 progress field $name is missing")

private fun JsonObject.requiredString(name: String): String {
    val primitive = requiredPrimitive(name)
    return primitive.content.takeIf { primitive.isString && it.isNotBlank() }
        ?: throw ReaderServerWireException("Reader v5 progress field $name is missing")
}

private fun JsonObject.requiredNullableString(name: String): String? = when (val value = this[name]) {
    JsonNull -> null
    is JsonPrimitive -> value.takeIf { it.isString }?.content
        ?: throw ReaderServerWireException("Reader v5 progress field $name is invalid")
    else -> throw ReaderServerWireException("Reader v5 progress field $name is invalid")
}

private fun JsonObject.requiredNullableInt(name: String): Int? = when (val value = this[name]) {
    JsonNull -> null
    is JsonPrimitive -> value.takeIf { !it.isString }?.intOrNull
        ?: throw ReaderServerWireException("Reader v5 progress field $name is invalid")
    else -> throw ReaderServerWireException("Reader v5 progress field $name is invalid")
}

private fun JsonObject.requiredNullableLong(name: String): Long? = when (val value = this[name]) {
    JsonNull -> null
    is JsonPrimitive -> value.takeIf { !it.isString }?.longOrNull
        ?: throw ReaderServerWireException("Reader v5 progress field $name is invalid")
    else -> throw ReaderServerWireException("Reader v5 progress field $name is invalid")
}

private fun JsonObject.requiredNullableObject(name: String): JsonObject? = when (val value = this[name]) {
    JsonNull -> null
    is JsonObject -> value
    else -> throw ReaderServerWireException("Reader v5 progress field $name is invalid")
}

private val JsonPrimitive.booleanOrNull: Boolean?
    get() = content.toBooleanStrictOrNull()
