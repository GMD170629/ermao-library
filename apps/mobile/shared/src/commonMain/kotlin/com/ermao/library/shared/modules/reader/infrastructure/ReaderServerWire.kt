package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
import com.ermao.library.shared.modules.reader.domain.PublicationLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

class ReaderServerWireException(message: String, cause: Throwable? = null) :
    IllegalArgumentException(message, cause)

/** Strict Kotlin boundary for the language-neutral packages/reader-contracts schema. */
class ReaderServerWireMapper(
    private val json: Json = readerServerWireJson,
) {
    fun encodeProgressUpload(upload: ReaderProgressUpload): String = json.encodeToString(
        ReaderProgressPutWire(
            clientId = upload.mutation.clientId,
            mutationId = upload.mutation.mutationId,
            baseRevision = upload.mutation.baseRevision,
            capturedAtEpochMillis = upload.mutation.capturedAtEpochMillis,
            locator = json.parseToJsonElement(upload.mutation.locator.canonicalJson()) as JsonObject,
        ),
    )

    internal fun decodeSnapshot(root: JsonObject, expectedSourceId: String): ReaderProgressSnapshotV4 {
        val schemaVersion = root.requiredLong("schemaVersion")
        if (schemaVersion != READER_SERVER_SCHEMA_VERSION.toLong()) {
            throw ReaderServerWireException("Reader progress schema is unsupported")
        }
        val locator = root["locator"] as? JsonObject
            ?: throw ReaderServerWireException("Reader progress locator is missing")
        return ReaderProgressSnapshotV4(
            sourceId = expectedSourceId,
            revision = root.requiredLong("revision"),
            locator = PublicationLocation.parse(locator.toString()),
            displayPercent = root.requiredDouble("displayPercent"),
            receivedAtEpochMillis = root.requiredLong("receivedAtEpochMillis"),
            capturedAtEpochMillis = root.optionalLong("capturedAtEpochMillis"),
        )
    }

    internal fun responseSerializer() = JsonObject.serializer()
}

@Serializable
internal data class ReaderProgressPutWire(
    val schemaVersion: Int = READER_SERVER_SCHEMA_VERSION,
    val clientId: String,
    val mutationId: String,
    val baseRevision: Long,
    val capturedAtEpochMillis: Long,
    val locator: JsonObject,
)

internal const val READER_SERVER_SCHEMA_VERSION = 4

internal val readerServerWireJson = Json {
    encodeDefaults = true
    explicitNulls = false
    ignoreUnknownKeys = false
}

private fun JsonObject.requiredLong(name: String): Long = (this[name] as? JsonPrimitive)?.longOrNull
    ?: throw ReaderServerWireException("Reader progress field $name is missing")

private fun JsonObject.requiredDouble(name: String): Double = (this[name] as? JsonPrimitive)?.doubleOrNull
    ?: throw ReaderServerWireException("Reader progress field $name is missing")

private fun JsonObject.optionalLong(name: String): Long? = (this[name] as? JsonPrimitive)?.longOrNull
