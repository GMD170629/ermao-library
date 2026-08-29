package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ReaderAppearancePreferences
import com.ermao.library.shared.modules.reader.domain.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderReadingMode
import com.ermao.library.shared.modules.reader.domain.ReaderTextAlignment
import com.ermao.library.shared.modules.reader.domain.ReaderTheme
import com.ermao.library.shared.modules.reader.domain.ReaderThemeMode
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

class ReaderPreferencesJson(private val json: Json) {
    constructor() : this(Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        explicitNulls = false
    })

    fun encode(preferences: ReaderPreferences): String = json.encodeToString(preferences)

    fun canonicalizeOrNull(payload: String): String? = runCatching { encode(decode(payload)) }.getOrNull()

    @Throws(IllegalArgumentException::class)
    fun decode(payload: String): ReaderPreferences {
        val document = json.decodeFromString<JsonObject>(payload)
        val version = document["schemaVersion"]?.jsonPrimitive?.contentOrNull
        if (version == null && document.keys.any(LEGACY_KEYS::contains)) return decodeLegacy(document)
        require(version in setOf("3", "4", "5")) { "Unsupported reader preferences schema" }
        val migrated = if (version != "5") {
            val epub = document["epub"] as? JsonObject
            val typography = epub?.get("typography") as? JsonObject
            JsonObject(document.toMutableMap().apply {
                put("schemaVersion", JsonPrimitive(ReaderPreferences.SCHEMA_VERSION))
                remove("iosDraft")
                if (epub != null && typography != null) put("epub", JsonObject(epub.toMutableMap().apply {
                    put("typography", JsonObject(typography.filterKeys {
                        it != "allowPublisherColors" && it != "allowPublisherFonts"
                    }))
                }))
            })
        } else document
        return json.decodeFromJsonElement<ReaderPreferences>(normalizeLegacyFontAlias(migrated))
    }

    private fun normalizeLegacyFontAlias(document: JsonObject): JsonObject {
        val epub = document["epub"] as? JsonObject ?: return document
        val fontFamily = epub["fontFamily"]?.jsonPrimitive?.contentOrNull
        if (fontFamily !in LEGACY_SANS_FONT_ALIASES) return document
        return JsonObject(document.toMutableMap().apply {
            put("epub", JsonObject(epub.toMutableMap().apply {
                put("fontFamily", JsonPrimitive("pingfang"))
            }))
        })
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
        val LEGACY_SANS_FONT_ALIASES = setOf("heiti", "yahei")
    }
}
