package com.ermao.library.features.reader.infrastructure

import android.content.Context
import androidx.core.content.edit
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderPreferencesJson
import java.security.MessageDigest

internal class AndroidReaderPreferencesStore(
    context: Context,
    serverIdentity: String,
    userId: String,
    private val codec: ReaderPreferencesJson = ReaderPreferencesJson(),
) {
    private val preferences = context.applicationContext.getSharedPreferences(STORE_NAME, Context.MODE_PRIVATE)
    private val key = "reader-${sha256("$serverIdentity\u0000$userId")}"

    fun load(): ReaderPreferences = preferences.getString(key, null)
        ?.let { runCatching { codec.decode(it) }.getOrNull() }
        ?: ReaderPreferences()

    fun save(value: ReaderPreferences) {
        val encodedPreferences = codec.encode(value)
        preferences.edit(commit = true) { putString(key, encodedPreferences) }
        check(preferences.getString(key, null) == encodedPreferences) {
            "Reader preferences could not be saved"
        }
    }

    fun reset(): ReaderPreferences = ReaderPreferences().also(::save)

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { byte -> "%02x".format(byte) }

    private companion object {
        const val STORE_NAME = "reader_preferences_v3"
    }
}
