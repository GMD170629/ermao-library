package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

object ReaderPreferencesJson {
    fun encode(preferences: ReaderPreferences): String = readerPreferencesJson.encodeToString(preferences)

    fun canonicalizeOrNull(payload: String): String? = runCatching { encode(decode(payload)) }.getOrNull()

    @Throws(IllegalArgumentException::class)
    fun decode(payload: String): ReaderPreferences {
        val document = readerPreferencesJson.decodeFromString<JsonObject>(payload)
        val version = document["schemaVersion"]?.jsonPrimitive
        require(version != null && !version.isString && version.intOrNull == ReaderPreferences.SCHEMA_VERSION) {
            "Unsupported reader preferences schema"
        }
        return readerPreferencesJson.decodeFromJsonElement(document)
    }
}

private val readerPreferencesJson = Json {
    encodeDefaults = true
    explicitNulls = false
}
