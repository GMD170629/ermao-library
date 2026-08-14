package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ReaderProgressDurableState
import com.ermao.library.shared.modules.reader.domain.PublicationLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressMutation
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

class ReaderProgressSyncStateJson(
    private val json: Json = readerServerWireJson,
) {
    fun encode(state: ReaderProgressDurableState): String = buildJsonObject {
        put("schema", SCHEMA)
        put("version", VERSION)
        put("confirmedRevision", state.confirmedRevision)
        state.pending?.let { put("pending", it.toJson()) }
        state.terminalFailureCode?.let { put("terminalFailureCode", it) }
    }.toString()

    fun decode(payload: String): ReaderProgressDurableState {
        val root = runCatching { json.parseToJsonElement(payload) as? JsonObject }.getOrNull()
            ?: throw ReaderServerWireException("Reader sync state is malformed")
        if (root.requiredString("schema") != SCHEMA || root.requiredLong("version") != VERSION.toLong()) {
            throw ReaderServerWireException("Reader sync state schema is unsupported")
        }
        val pending = (root["pending"] as? JsonObject)?.toMutation()
        return ReaderProgressDurableState(
            confirmedRevision = root.requiredLong("confirmedRevision"),
            pending = pending,
            terminalFailureCode = root.optionalString("terminalFailureCode"),
        )
    }

    private fun ReaderProgressMutation.toJson(): JsonObject = buildJsonObject {
        put("sourceId", sourceId)
        put("clientId", clientId)
        put("mutationId", mutationId)
        put("baseRevision", baseRevision)
        put("capturedAtEpochMillis", capturedAtEpochMillis)
        put("locator", json.parseToJsonElement(locator.canonicalJson()))
    }

    private fun JsonObject.toMutation(): ReaderProgressMutation = ReaderProgressMutation(
        sourceId = requiredString("sourceId"),
        clientId = requiredString("clientId"),
        mutationId = requiredString("mutationId"),
        baseRevision = requiredLong("baseRevision"),
        capturedAtEpochMillis = requiredLong("capturedAtEpochMillis"),
        locator = PublicationLocation.parse(requiredObject("locator").toString()),
    )

    companion object {
        private const val SCHEMA = "ermao.reader-progress-sync"
        private const val VERSION = 6
    }
}

private fun JsonObject.optionalString(name: String): String? =
    (this[name] as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)

private fun JsonObject.requiredString(name: String): String = optionalString(name)
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")

private fun JsonObject.requiredLong(name: String): Long = (this[name] as? JsonPrimitive)?.longOrNull
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")

private fun JsonObject.requiredObject(name: String): JsonObject = this[name] as? JsonObject
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")
