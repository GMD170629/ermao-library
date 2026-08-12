package com.ermao.library.platform.persistence

import android.content.Context
import com.ermao.library.features.content.model.GroupingCard
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.shared.modules.library.ContentRequestContext
import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

object AndroidContentSnapshotCache {
    private const val MAX_QUERY_IDENTITIES = 20
    private const val MAX_PAGES_PER_QUERY = 3
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = false }

    @Serializable
    data class CachedHome(val savedAtEpochMillis: Long, val content: HomeContent)

    @Serializable
    data class CachedWorkPage(
        val savedAtEpochMillis: Long,
        val items: List<WorkCard>,
        val page: Int,
        val total: Int,
        val totalPages: Int,
        val facetName: String? = null,
    )

    @Serializable
    data class CachedGroupingPage(
        val savedAtEpochMillis: Long,
        val items: List<GroupingCard>,
        val page: Int,
        val total: Int,
        val totalPages: Int,
    )

    @Serializable
    data class CachedDetail(val savedAtEpochMillis: Long, val content: WorkDetailContent)

    suspend fun loadHome(context: Context, request: ContentRequestContext): CachedHome? =
        read(context, request, "home", "root", 1, CachedHome.serializer())

    suspend fun saveHome(context: Context, request: ContentRequestContext, content: HomeContent) =
        write(context, request, "home", "root", 1, CachedHome(System.currentTimeMillis(), content), CachedHome.serializer())

    suspend fun loadWorks(context: Context, request: ContentRequestContext, identity: String, page: Int): CachedWorkPage? =
        read(context, request, "works", identity, page, CachedWorkPage.serializer())

    suspend fun saveWorks(context: Context, request: ContentRequestContext, identity: String, value: CachedWorkPage) =
        write(context, request, "works", identity, value.page, value, CachedWorkPage.serializer())

    suspend fun loadGroups(context: Context, request: ContentRequestContext, identity: String, page: Int): CachedGroupingPage? =
        read(context, request, "groups", identity, page, CachedGroupingPage.serializer())

    suspend fun saveGroups(context: Context, request: ContentRequestContext, identity: String, value: CachedGroupingPage) =
        write(context, request, "groups", identity, value.page, value, CachedGroupingPage.serializer())

    suspend fun loadFacet(context: Context, request: ContentRequestContext, identity: String, page: Int): CachedWorkPage? =
        read(context, request, "facets", identity, page, CachedWorkPage.serializer())

    suspend fun saveFacet(context: Context, request: ContentRequestContext, identity: String, value: CachedWorkPage) =
        write(context, request, "facets", identity, value.page, value, CachedWorkPage.serializer())

    suspend fun loadDetail(context: Context, request: ContentRequestContext, workId: String): CachedDetail? =
        read(context, request, "details", workId, 1, CachedDetail.serializer())

    suspend fun saveDetail(context: Context, request: ContentRequestContext, workId: String, content: WorkDetailContent) =
        write(context, request, "details", workId, 1, CachedDetail(System.currentTimeMillis(), content), CachedDetail.serializer())

    suspend fun clearNamespace(context: Context, request: ContentRequestContext) = withContext(Dispatchers.IO) {
        val namespaceDirectory = File(context.filesDir, "content-snapshots/${namespaceKey(request)}")
        if (namespaceDirectory.exists() && !namespaceDirectory.deleteRecursively()) {
            throw ContentSnapshotCacheException("Failed to clear content cache namespace", null)
        }
    }

    private suspend fun <T> read(
        appContext: Context,
        request: ContentRequestContext,
        kind: String,
        identity: String,
        page: Int,
        serializer: KSerializer<T>,
    ): T? = withContext(Dispatchers.IO) {
        val file = pageFile(appContext, request, kind, identity, page)
        if (!file.isFile) return@withContext null
        try {
            json.decodeFromString(serializer, file.readText()).also {
                file.parentFile?.setLastModified(System.currentTimeMillis())
            }
        } catch (error: java.io.IOException) {
            throw ContentSnapshotCacheException("Failed to read content cache", error)
        } catch (error: kotlinx.serialization.SerializationException) {
            file.delete()
            null
        }
    }

    private suspend fun <T> write(
        appContext: Context,
        request: ContentRequestContext,
        kind: String,
        identity: String,
        page: Int,
        value: T,
        serializer: KSerializer<T>,
    ) = withContext(Dispatchers.IO) {
        val destination = pageFile(appContext, request, kind, identity, page)
        destination.parentFile?.mkdirs()
        val temporary = File(destination.parentFile, "${destination.name}.tmp")
        try {
            temporary.writeText(json.encodeToString(serializer, value))
            if (!temporary.renameTo(destination)) {
                temporary.copyTo(destination, overwrite = true)
                temporary.delete()
            }
        } catch (error: java.io.IOException) {
            temporary.delete()
            throw ContentSnapshotCacheException("Failed to write content cache", error)
        }
        destination.parentFile?.setLastModified(System.currentTimeMillis())
        destination.parentFile?.listFiles()?.filter(File::isFile)?.sortedByDescending(File::lastModified)
            ?.drop(MAX_PAGES_PER_QUERY)?.forEach(File::delete)
        val kindDirectory = destination.parentFile?.parentFile
        kindDirectory?.listFiles()?.filter(File::isDirectory)?.sortedByDescending(File::lastModified)
            ?.drop(MAX_QUERY_IDENTITIES)?.forEach(File::deleteRecursively)
    }

    private fun pageFile(
        context: Context,
        request: ContentRequestContext,
        kind: String,
        identity: String,
        page: Int,
    ): File = File(
        context.filesDir,
        "content-snapshots/${namespaceKey(request)}/$kind/${sha256(identity)}/page-$page.json",
    )

    private fun namespaceKey(context: ContentRequestContext): String = sha256(
        "${context.namespace.serverIdentity}|${context.namespace.userId}|${context.namespace.authorizationVersion}",
    )

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.encodeToByteArray()).joinToString("") { "%02x".format(it) }
}

class ContentSnapshotCacheException(message: String, cause: Throwable?) : Exception(message, cause)
