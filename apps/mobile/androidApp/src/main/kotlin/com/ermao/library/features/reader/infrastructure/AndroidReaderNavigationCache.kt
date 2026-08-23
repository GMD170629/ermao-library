package com.ermao.library.features.reader.infrastructure

import android.content.Context
import androidx.core.content.edit
import com.ermao.library.shared.modules.reader.ReaderBootstrap
import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.ReaderNavigationUnit
import com.ermao.library.shared.modules.reader.ReaderPdfPage
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

data class AndroidReaderNavigationSnapshot(
    val units: List<ReaderNavigationUnit>,
    val comicPages: List<ReaderComicPage>,
    val pdfPages: List<ReaderPdfPage>,
    val pageCount: Int?,
)

/** Best-effort navigation hints. Publication parsers remain authoritative. */
class AndroidReaderNavigationCache(context: Context) {
    private val appContext = context.applicationContext

    fun save(namespace: ReaderSyncNamespace, resourceId: String, bootstrap: ReaderBootstrap) {
        val payload = JSONObject().apply {
            put("schema", SCHEMA_VERSION)
            put("units", JSONArray().apply {
                bootstrap.units.take(MAX_ENTRIES).forEach { unit ->
                    put(JSONObject().apply {
                        put("id", unit.id)
                        put("index", unit.index)
                        put("title", unit.title)
                        unit.href?.let { put("href", it) }
                    })
                }
            })
            put("comicPages", JSONArray().apply {
                bootstrap.comicPages.take(MAX_ENTRIES).forEach { page ->
                    put(JSONObject().apply {
                        put("index", page.pageIndex)
                        put("href", page.resourceHref)
                        put("mediaType", page.mediaType)
                        page.width?.let { put("width", it) }
                        page.height?.let { put("height", it) }
                        page.title?.let { put("title", it) }
                    })
                }
            })
            put("pdfPages", JSONArray().apply {
                bootstrap.pdfPages.take(MAX_ENTRIES).forEach { page ->
                    put(JSONObject().apply {
                        put("index", page.pageIndex)
                        put("title", page.title)
                    })
                }
            })
            bootstrap.pageCount?.let { put("pageCount", it) }
        }
        preferences(namespace).edit {
            putString(key(namespace, resourceId), payload.toString())
        }
    }

    fun load(namespace: ReaderSyncNamespace, resourceId: String): AndroidReaderNavigationSnapshot? =
        runCatching {
            val payload = preferences(namespace).getString(key(namespace, resourceId), null)
                ?: return@runCatching null
            val root = JSONObject(payload)
            if (root.optInt("schema") != SCHEMA_VERSION) return@runCatching null
            val units = root.getJSONArray("units").objects().mapNotNull { value ->
                runCatching {
                    ReaderNavigationUnit(
                        id = value.getString("id"),
                        index = value.getInt("index"),
                        title = value.getString("title"),
                        href = value.optString("href").takeIf(String::isNotBlank),
                    )
                }.getOrNull()
            }.sortedBy(ReaderNavigationUnit::index).distinctBy(ReaderNavigationUnit::id)
            val comicPages = root.getJSONArray("comicPages").objects().mapIndexedNotNull { index, value ->
                runCatching {
                    ReaderComicPage(
                        pageIndex = index,
                        resourceHref = value.getString("href"),
                        mediaType = value.getString("mediaType"),
                        width = value.optInt("width").takeIf { it > 0 },
                        height = value.optInt("height").takeIf { it > 0 },
                        title = value.optString("title").takeIf(String::isNotBlank),
                    )
                }.getOrNull()
            }
            val pdfPages = root.getJSONArray("pdfPages").objects().mapIndexedNotNull { index, value ->
                runCatching { ReaderPdfPage(index, value.getString("title")) }.getOrNull()
            }
            AndroidReaderNavigationSnapshot(
                units = units,
                comicPages = comicPages,
                pdfPages = pdfPages,
                pageCount = root.optInt("pageCount").takeIf { it > 0 },
            )
        }.getOrNull()

    private fun preferences(namespace: ReaderSyncNamespace) = appContext.getSharedPreferences(
        "reader-navigation-v3-${sha256(readerAccountStorageKey(namespace))}",
        Context.MODE_PRIVATE,
    )

    private fun key(namespace: ReaderSyncNamespace, resourceId: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("${namespace.stableKey}\u0000$resourceId".toByteArray(Charsets.UTF_8))
        return digest.joinToString(separator = "") { byte -> "%02x".format(byte) }
    }

    private fun JSONArray.objects(): List<JSONObject> =
        (0 until minOf(length(), MAX_ENTRIES)).mapNotNull { index -> optJSONObject(index) }

    companion object {
        const val SCHEMA_VERSION = 2
        const val MAX_ENTRIES = 20_000

        internal fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) {
            context.deleteSharedPreferences("reader-navigation-v3-${sha256(readerAccountStorageKey(namespace))}")
        }
    }
}
