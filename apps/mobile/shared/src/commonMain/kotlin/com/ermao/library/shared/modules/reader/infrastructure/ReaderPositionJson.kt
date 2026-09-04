package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ReaderPositionLocalState
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/** v5 local document. It intentionally has no decoder for v4/v3 documents. */
class ReaderPositionJson(
    private val mapper: ReaderV5ServerWireMapper = ReaderV5ServerWireMapper(),
) {
    fun encode(position: ReaderPositionLocalState): String = buildJsonObject {
        put("schema", SCHEMA)
        put("version", VERSION)
        put("resourceId", position.resourceId)
        put("clientId", position.clientId)
        put("capturedAtEpochMillis", position.capturedAtEpochMillis)
        put("position", mapper.encodePosition(position.position))
    }.toString()

    fun decode(payload: String): ReaderPositionLocalState {
        val root = runCatching { readerV5ServerWireJson.parseToJsonElement(payload) as? JsonObject }
            .getOrNull() ?: throw ReaderServerWireException("Reader v5 position is malformed")
        requireKeys(root, setOf("schema", "version", "resourceId", "clientId", "capturedAtEpochMillis", "position"))
        if (root.requiredString("schema") != SCHEMA || root.requiredLong("version") != VERSION.toLong()) {
            throw ReaderServerWireException("Reader v5 position schema is unsupported")
        }
        return ReaderPositionLocalState(
            resourceId = root.requiredString("resourceId"),
            clientId = root.requiredString("clientId"),
            capturedAtEpochMillis = root.requiredLong("capturedAtEpochMillis"),
            position = mapper.decodePosition(root.requiredObject("position")),
        )
    }

    private companion object {
        const val SCHEMA = "ermao.reader-position"
        const val VERSION = 5
    }
}

private fun JsonObject.requiredString(name: String): String = (this[name] as? JsonPrimitive)
    ?.takeIf(JsonPrimitive::isString)?.content
    ?.takeIf(String::isNotBlank)
    ?: throw ReaderServerWireException("Reader v5 position field $name is missing")

private fun JsonObject.requiredLong(name: String): Long = (this[name] as? JsonPrimitive)
    ?.takeIf { !it.isString }?.longOrNull
    ?: throw ReaderServerWireException("Reader v5 position field $name is missing")

private fun JsonObject.requiredObject(name: String): JsonObject = this[name] as? JsonObject
    ?: throw ReaderServerWireException("Reader v5 position field $name is missing")

private fun requireKeys(root: JsonObject, expected: Set<String>) {
    if (root.keys != expected) throw ReaderServerWireException("Reader v5 position fields are unsupported")
}
