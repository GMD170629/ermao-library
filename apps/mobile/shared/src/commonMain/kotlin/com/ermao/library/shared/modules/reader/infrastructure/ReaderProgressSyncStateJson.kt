package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ReaderProgressDurableState
import com.ermao.library.shared.modules.reader.domain.PublicationLocation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressConflict
import com.ermao.library.shared.modules.reader.domain.ReaderProgressMutation
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
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
        state.conflict?.let { put("conflict", it.server.toJson()) }
        state.terminalFailureCode?.let { put("terminalFailureCode", it) }
    }.toString()

    fun decode(payload: String): ReaderProgressDurableState {
        val root = runCatching { json.parseToJsonElement(payload) as? JsonObject }.getOrNull()
            ?: throw ReaderServerWireException("Reader sync state is malformed")
        if (root.requiredString("schema") != SCHEMA || root.requiredLong("version") != VERSION.toLong()) {
            throw ReaderServerWireException("Reader sync state schema is unsupported")
        }
        val pending = (root["pending"] as? JsonObject)?.toMutation()
        val conflict = (root["conflict"] as? JsonObject)?.let { server ->
            ReaderProgressConflict(
                pending ?: throw ReaderServerWireException("Reader conflict is missing its pending mutation"),
                server.toSnapshot(pending.sourceId),
            )
        }
        return ReaderProgressDurableState(
            confirmedRevision = root.requiredLong("confirmedRevision"),
            pending = pending,
            conflict = conflict,
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

    private fun ReaderProgressSnapshotV4.toJson(): JsonObject = buildJsonObject {
        put("revision", revision)
        put("locator", json.parseToJsonElement(locator.canonicalJson()))
        put("displayPercent", displayPercent)
        put("receivedAtEpochMillis", receivedAtEpochMillis)
        capturedAtEpochMillis?.let { put("capturedAtEpochMillis", it) }
    }

    private fun JsonObject.toMutation(): ReaderProgressMutation = ReaderProgressMutation(
        sourceId = requiredString("sourceId"),
        clientId = requiredString("clientId"),
        mutationId = requiredString("mutationId"),
        baseRevision = requiredLong("baseRevision"),
        capturedAtEpochMillis = requiredLong("capturedAtEpochMillis"),
        locator = PublicationLocation.parse(requiredObject("locator").toString()),
    )

    private fun JsonObject.toSnapshot(sourceId: String): ReaderProgressSnapshotV4 = ReaderProgressSnapshotV4(
        sourceId = sourceId,
        revision = requiredLong("revision"),
        locator = PublicationLocation.parse(requiredObject("locator").toString()),
        displayPercent = requiredDouble("displayPercent"),
        receivedAtEpochMillis = requiredLong("receivedAtEpochMillis"),
        capturedAtEpochMillis = optionalLong("capturedAtEpochMillis"),
    )

    companion object {
        private const val SCHEMA = "ermao.reader-progress-sync"
        private const val VERSION = 5
    }
}

private fun JsonObject.optionalString(name: String): String? =
    (this[name] as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)

private fun JsonObject.requiredString(name: String): String = optionalString(name)
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")

private fun JsonObject.requiredLong(name: String): Long = (this[name] as? JsonPrimitive)?.longOrNull
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")

private fun JsonObject.optionalLong(name: String): Long? = (this[name] as? JsonPrimitive)?.longOrNull

private fun JsonObject.requiredDouble(name: String): Double = (this[name] as? JsonPrimitive)?.doubleOrNull
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")

private fun JsonObject.requiredObject(name: String): JsonObject = this[name] as? JsonObject
    ?: throw ReaderServerWireException("Reader sync state field $name is missing")
