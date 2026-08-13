package com.ermao.library.features.reader.infrastructure

import android.content.Context
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject

internal data class AndroidReaderBookmarkRecord(
    val id: String,
    val resourceKey: String,
    val progression: Double?,
    val totalProgression: Double?,
    val position: Int?,
    val exactEnvelope: String?,
    val label: String,
    val percent: Double,
    val createdAt: String,
)

internal data class AndroidReaderBookmarkState(
    val bookmarks: List<AndroidReaderBookmarkRecord> = emptyList(),
    val pending: List<AndroidReaderBookmarkRecord>? = null,
)

internal class AndroidReaderBookmarkStore(
    context: Context,
    serverIdentity: String,
    userId: String,
    volumeId: String,
    contentFingerprint: String,
) {
    private val preferences = context.getSharedPreferences("reader_bookmarks_v1", Context.MODE_PRIVATE)
    private val key = listOf(serverIdentity, userId, volumeId, contentFingerprint)
        .joinToString("\u0000")
        .sha256()

    fun load(): AndroidReaderBookmarkState = preferences.getString(key, null)
        ?.let(::decode)
        ?: AndroidReaderBookmarkState()

    fun save(state: AndroidReaderBookmarkState) {
        check(preferences.edit().putString(key, encode(state)).commit()) {
            "Unable to atomically save reader bookmarks"
        }
    }

    private fun encode(state: AndroidReaderBookmarkState): String = JSONObject()
        .put("bookmarks", records(state.bookmarks))
        .put("pending", state.pending?.let(::records) ?: JSONObject.NULL)
        .toString()

    private fun decode(raw: String): AndroidReaderBookmarkState = runCatching {
        val root = JSONObject(raw)
        AndroidReaderBookmarkState(
            bookmarks = parseRecords(root.optJSONArray("bookmarks")),
            pending = if (root.isNull("pending")) null else parseRecords(root.optJSONArray("pending")),
        )
    }.getOrDefault(AndroidReaderBookmarkState())

    private fun records(values: List<AndroidReaderBookmarkRecord>) = JSONArray().apply {
        values.forEach { value ->
            put(JSONObject()
                .put("id", value.id)
                .put("resourceKey", value.resourceKey)
                .put("progression", value.progression)
                .put("totalProgression", value.totalProgression)
                .put("position", value.position)
                .put("exactEnvelope", value.exactEnvelope)
                .put("label", value.label)
                .put("percent", value.percent)
                .put("createdAt", value.createdAt))
        }
    }

    private fun parseRecords(array: JSONArray?): List<AndroidReaderBookmarkRecord> = buildList {
        if (array == null) return@buildList
        repeat(array.length()) { index ->
            val item = array.optJSONObject(index) ?: return@repeat
            val id = item.optString("id").takeIf(String::isNotBlank) ?: return@repeat
            val resourceKey = item.optString("resourceKey").takeIf(String::isNotBlank) ?: return@repeat
            add(AndroidReaderBookmarkRecord(
                id = id,
                resourceKey = resourceKey,
                progression = item.optionalDouble("progression"),
                totalProgression = item.optionalDouble("totalProgression"),
                position = if (item.isNull("position")) null else item.optInt("position"),
                exactEnvelope = item.optString("exactEnvelope").takeIf(String::isNotBlank),
                label = item.optString("label"),
                percent = item.optDouble("percent").takeIf(Double::isFinite) ?: 0.0,
                createdAt = item.optString("createdAt"),
            ))
        }
    }
}

private fun JSONObject.optionalDouble(name: String): Double? =
    if (isNull(name)) null else optDouble(name).takeIf(Double::isFinite)

private fun String.sha256(): String = MessageDigest.getInstance("SHA-256")
    .digest(toByteArray())
    .joinToString("") { "%02x".format(it) }
