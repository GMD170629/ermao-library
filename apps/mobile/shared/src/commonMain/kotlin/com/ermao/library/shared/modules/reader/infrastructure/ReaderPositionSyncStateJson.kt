package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ReaderPositionDurableState
import com.ermao.library.shared.modules.reader.domain.ReaderProgressMutationV5
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/** v5 outbox document. Older sync documents are rejected and never migrated. */
class ReaderPositionSyncStateJson(
    private val mapper: ReaderV5ServerWireMapper = ReaderV5ServerWireMapper(),
) {
    fun encode(state: ReaderPositionDurableState): String = buildJsonObject {
        put("schema", SCHEMA)
        put("version", VERSION)
        put("confirmedRevision", state.confirmedRevision)
        // JsonObjectBuilder.put returns the value previously stored under the
        // key.  Using it as the result of a nullable `let`/Elvis expression
        // would therefore overwrite a newly inserted pending mutation (whose
        // previous value is null) with JsonNull.
        val pending = state.pending
        if (pending != null) put("pending", pending.toJson())
        else put("pending", JsonNull)
        val terminalFailureCode = state.terminalFailureCode
        if (terminalFailureCode != null) put("terminalFailureCode", terminalFailureCode)
        else put("terminalFailureCode", JsonNull)
    }.toString()

    fun decode(payload: String): ReaderPositionDurableState {
        val root = runCatching { readerV5ServerWireJson.parseToJsonElement(payload) as? JsonObject }
            .getOrNull() ?: throw ReaderServerWireException("Reader v5 sync state is malformed")
        requireKeys(root, setOf("schema", "version", "confirmedRevision", "pending", "terminalFailureCode"))
        if (root.requiredString("schema") != SCHEMA || root.requiredLong("version") != VERSION.toLong()) {
            throw ReaderServerWireException("Reader v5 sync state schema is unsupported")
        }
        val pending = (root["pending"] as? JsonObject)?.toMutation()
        val terminal = when (val value = root["terminalFailureCode"]) {
            null, JsonNull -> null
            is JsonPrimitive -> value.takeIf { it.isString }?.content?.takeIf(String::isNotBlank)
                ?: throw ReaderServerWireException("Reader v5 terminal failure is invalid")
            else -> throw ReaderServerWireException("Reader v5 terminal failure is invalid")
        }
        return ReaderPositionDurableState(root.requiredLong("confirmedRevision"), pending, terminal)
    }

    private fun ReaderProgressMutationV5.toJson(): JsonObject = buildJsonObject {
        put("resourceId", resourceId)
        put("clientId", clientId)
        put("mutationId", mutationId)
        put("capturedAtEpochMillis", capturedAtEpochMillis)
        put("position", mapper.encodePosition(position))
    }

    private fun JsonObject.toMutation(): ReaderProgressMutationV5 {
        requireKeys(
            this,
            setOf("resourceId", "clientId", "mutationId", "capturedAtEpochMillis", "position"),
        )
        return ReaderProgressMutationV5(
            resourceId = requiredString("resourceId"),
            clientId = requiredString("clientId"),
            mutationId = requiredString("mutationId"),
            capturedAtEpochMillis = requiredLong("capturedAtEpochMillis"),
            position = mapper.decodePosition(requiredObject("position")),
        )
    }

    private companion object {
        const val SCHEMA = "ermao.reader-position-sync"
        const val VERSION = 5
    }
}

private fun JsonObject.requiredString(name: String): String = (this[name] as? JsonPrimitive)
    ?.takeIf { it.isString }?.content?.takeIf(String::isNotBlank)
    ?: throw ReaderServerWireException("Reader v5 sync state field $name is missing")

private fun JsonObject.requiredLong(name: String): Long = (this[name] as? JsonPrimitive)
    ?.takeIf { !it.isString }?.longOrNull
    ?: throw ReaderServerWireException("Reader v5 sync state field $name is missing")

private fun JsonObject.requiredObject(name: String): JsonObject = this[name] as? JsonObject
    ?: throw ReaderServerWireException("Reader v5 sync state field $name is missing")

private fun requireKeys(root: JsonObject, expected: Set<String>) {
    if (root.keys != expected) throw ReaderServerWireException("Reader v5 sync state fields are unsupported")
}
