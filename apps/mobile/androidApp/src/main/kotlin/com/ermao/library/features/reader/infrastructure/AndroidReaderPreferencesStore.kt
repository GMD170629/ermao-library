package com.ermao.library.features.reader.infrastructure

import android.content.Context
import androidx.core.content.edit
import com.ermao.library.features.reader.application.enforceAndroidSinglePagePreferences
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderPreferencesJson
import java.security.MessageDigest

internal class AndroidReaderPreferencesStore(
    context: Context,
    serverIdentity: String,
    userId: String,
) {
    private val preferences = context.applicationContext.getSharedPreferences("reader_preferences", Context.MODE_PRIVATE)
    private val key = "reader-${sha256("$serverIdentity\u0000$userId")}"

    fun load(): ReaderPreferences {
        val stored = preferences.getString(key, null)
            ?: return enforceAndroidSinglePagePreferences(ReaderPreferences())
        val decoded = runCatching { ReaderPreferencesJson.decode(stored) }.getOrElse { return ReaderPreferences() }
        val supported = enforceAndroidSinglePagePreferences(decoded)
        val canonical = ReaderPreferencesJson.encode(supported)
        if (canonical != stored) save(supported)
        return supported
    }

    fun save(value: ReaderPreferences) {
        val encodedPreferences = ReaderPreferencesJson.encode(enforceAndroidSinglePagePreferences(value))
        try {
            preferences.edit(commit = true) { putString(key, encodedPreferences) }
        } catch (error: RuntimeException) {
            throw com.ermao.library.features.reader.application.ReaderPreferenceSaveFailure(error)
        }
        if (preferences.getString(key, null) != encodedPreferences) throw com.ermao.library.features.reader.application.ReaderPreferenceSaveFailure()
    }

    fun reset(): ReaderPreferences = enforceAndroidSinglePagePreferences(ReaderPreferences()).also(::save)

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { byte -> "%02x".format(byte) }
}
