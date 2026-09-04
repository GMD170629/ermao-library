package com.ermao.library.features.reader.infrastructure

import android.content.Context
import androidx.core.content.edit
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject

internal data class AndroidReaderBookmarkRecord(
    val id: String,
    val positionJson: String,
    val label: String,
    val createdAt: String,
)

internal data class AndroidReaderBookmarkState(
    val bookmarks: List<AndroidReaderBookmarkRecord> = emptyList(),
    val pending: List<AndroidReaderBookmarkRecord>? = null,
)

internal class AndroidReaderBookmarkStore(
    context: Context,
    namespace: ReaderSyncNamespace,
    resourceId: String,
) {
    private val preferences = context.getSharedPreferences(
        "reader_bookmarks_v5_${sha256(readerAccountStorageKey(namespace))}",
        Context.MODE_PRIVATE,
    )
    private val key = listOf(namespace.stableKey, resourceId)
        .joinToString("\u0000")
        .sha256()

    fun load(): AndroidReaderBookmarkState = preferences.getString(key, null)
        ?.let(::decode)
        ?: AndroidReaderBookmarkState()

    fun save(state: AndroidReaderBookmarkState) {
        val encodedState = encode(state)
        preferences.edit(commit = true) { putString(key, encodedState) }
        check(preferences.getString(key, null) == encodedState) {
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
                .put("position", JSONObject(value.positionJson))
                .put("label", value.label)
                .put("createdAt", value.createdAt))
        }
    }

    private fun parseRecords(array: JSONArray?): List<AndroidReaderBookmarkRecord> = buildList {
        if (array == null) return@buildList
        repeat(array.length()) { index ->
            val item = array.optJSONObject(index) ?: return@repeat
            val id = item.optString("id").takeIf(String::isNotBlank) ?: return@repeat
            val position = item.optJSONObject("position")?.toString() ?: return@repeat
            add(AndroidReaderBookmarkRecord(
                id = id,
                positionJson = position,
                label = item.optString("label"),
                createdAt = item.optString("createdAt"),
            ))
        }
    }

    companion object {
        internal fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) {
            context.deleteSharedPreferences("reader_bookmarks_v5_${sha256(readerAccountStorageKey(namespace))}")
        }
    }
}

private fun String.sha256(): String = MessageDigest.getInstance("SHA-256")
    .digest(toByteArray())
    .joinToString("") { "%02x".format(it) }
