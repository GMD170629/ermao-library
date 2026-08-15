package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ReaderAppearancePreferences
import com.ermao.library.shared.modules.reader.domain.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderReadingMode
import com.ermao.library.shared.modules.reader.domain.ReaderTextAlignment
import com.ermao.library.shared.modules.reader.domain.ReaderTheme
import com.ermao.library.shared.modules.reader.domain.ReaderThemeMode
import kotlinx.serialization.SerializationException
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.roundToInt

class ReaderPreferencesJson(
    private val json: Json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        explicitNulls = false
    },
) {
    fun encode(preferences: ReaderPreferences): String = json.encodeToString(preferences)

    fun decode(payload: String): ReaderPreferences {
        val document = json.decodeFromString<JsonObject>(payload)
        if (document["schemaVersion"]?.jsonPrimitive?.contentOrNull == "3") {
            val migrated = JsonObject(
                document.toMutableMap().apply {
                    put("schemaVersion", JsonPrimitive(ReaderPreferences.SCHEMA_VERSION))
                },
            )
            return json.decodeFromJsonElement<ReaderPreferences>(migrated)
        }
        if ("schemaVersion" !in document && document.keys.any(LEGACY_KEYS::contains)) {
            return decodeLegacy(document)
        }
        try {
            return json.decodeFromString<ReaderPreferences>(payload)
        } catch (_: SerializationException) {
            return decodeLegacy(document)
        } catch (_: IllegalArgumentException) {
            return decodeLegacy(document)
        }
    }

    private fun decodeLegacy(document: JsonObject): ReaderPreferences {
        val legacyTheme = document["theme"]?.jsonPrimitive?.contentOrNull
        val appearance = when (legacyTheme) {
            "night" -> ReaderAppearancePreferences(ReaderTheme.Night)
            "system" -> ReaderAppearancePreferences(ReaderTheme.Warm, ReaderThemeMode.System)
            else -> ReaderAppearancePreferences(ReaderTheme.Warm)
        }
        val oldFontScale = document["fontSize"]?.jsonPrimitive?.doubleOrNull ?: 1.0
        val fontSize = (oldFontScale * 18).roundToInt().coerceIn(14, 30)
        val lineHeight = (document["lineHeight"]?.jsonPrimitive?.doubleOrNull ?: 1.9).coerceIn(1.4, 2.4)
        val flow = when (document["readingMode"]?.jsonPrimitive?.contentOrNull) {
            "continuous_scroll", "scrolled" -> ReaderReadingMode.ContinuousScroll
            else -> ReaderReadingMode.Paged
        }
        val publisherStyles = document["publisherStyles"]?.jsonPrimitive?.booleanOrNull ?: false
        val alignment = when (document["textAlignment"]?.jsonPrimitive?.contentOrNull) {
            "start", "left" -> ReaderTextAlignment.Start
            "justify" -> ReaderTextAlignment.Justify
            else -> ReaderTextAlignment.PublisherDefault
        }
        return ReaderPreferences(
            appearance = appearance,
            epub = ReaderEpubPreferences(
                fontSize = fontSize,
                lineHeight = lineHeight,
                flow = flow,
                typography = com.ermao.library.shared.modules.reader.domain.ReaderTypographyPreferences(
                    textAlign = alignment,
                    preservePublisherStyles = publisherStyles,
                ),
            ),
        )
    }

    private companion object {
        val LEGACY_KEYS = setOf(
            "theme",
            "fontSize",
            "fontFamily",
            "lineHeight",
            "letterSpacing",
            "pageMargins",
            "readingMode",
            "publisherStyles",
            "textAlignment",
        )
    }
}
