package com.ermao.library.platform.persistence

import android.content.Context
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

object AndroidCoverCache {
    private const val MEMORY_ENTRY_LIMIT = 18
    private const val DISK_BYTE_LIMIT = 64L * 1024L * 1024L
    private val mutex = Mutex()
    private val namespaceByMemoryKey = mutableMapOf<String, String>()
    private val memory = object : LinkedHashMap<String, ByteArray>(MEMORY_ENTRY_LIMIT, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, ByteArray>?): Boolean {
            val shouldRemove = size > MEMORY_ENTRY_LIMIT
            if (shouldRemove && eldest != null) namespaceByMemoryKey.remove(eldest.key)
            return shouldRemove
        }
    }

    suspend fun load(
        appContext: Context,
        requestContext: ContentRequestContext,
        apiPath: String,
        repository: ContentRepository,
    ): ByteArray? = withContext(Dispatchers.IO) {
        val key = cacheKey(requestContext, apiPath)
        mutex.withLock { memory[key] }?.let { return@withContext it }
        val directory = File(appContext.cacheDir, "authenticated-covers/${namespaceKey(requestContext)}")
        val destination = File(directory, key)
        runCatching { destination.takeIf(File::isFile)?.readBytes() }.getOrNull()?.let { bytes ->
            if (bytes.isNotEmpty()) {
                mutex.withLock {
                    memory[key] = bytes
                    namespaceByMemoryKey[key] = namespaceKey(requestContext)
                }
                destination.setLastModified(System.currentTimeMillis())
                return@withContext bytes
            }
        }
        when (val result = repository.loadCover(requestContext, apiPath)) {
            is ContentResult.Content -> result.value.bytes.takeIf(ByteArray::isNotEmpty)?.also { bytes ->
                directory.mkdirs()
                val temporary = File(directory, "$key.tmp")
                runCatching {
                    temporary.writeBytes(bytes)
                    if (!temporary.renameTo(destination)) {
                        temporary.copyTo(destination, overwrite = true)
                        temporary.delete()
                    }
                    trim(directory)
                }
                mutex.withLock {
                    memory[key] = bytes
                    namespaceByMemoryKey[key] = namespaceKey(requestContext)
                }
            }
            is ContentResult.Failure -> null
        }
    }

    suspend fun clearNamespace(appContext: Context, requestContext: ContentRequestContext) = withContext(Dispatchers.IO) {
        val namespace = namespaceKey(requestContext)
        mutex.withLock {
            val keys = namespaceByMemoryKey.filterValues { it == namespace }.keys.toList()
            keys.forEach {
                memory.remove(it)
                namespaceByMemoryKey.remove(it)
            }
        }
        val directory = File(appContext.cacheDir, "authenticated-covers/$namespace")
        if (directory.exists() && !directory.deleteRecursively()) {
            throw CoverCacheException("Failed to clear cover cache namespace")
        }
    }

    suspend fun invalidate(
        appContext: Context,
        requestContext: ContentRequestContext,
        apiPath: String,
    ) = withContext(Dispatchers.IO) {
        if (apiPath.isBlank()) return@withContext
        val key = cacheKey(requestContext, apiPath)
        mutex.withLock {
            memory.remove(key)
            namespaceByMemoryKey.remove(key)
        }
        val destination = File(
            File(appContext.cacheDir, "authenticated-covers/${namespaceKey(requestContext)}"),
            key,
        )
        if (destination.exists() && !destination.delete()) {
            throw CoverCacheException("Failed to invalidate cover cache entry")
        }
    }

    private fun trim(directory: File) {
        val files = directory.listFiles()?.filter(File::isFile)?.sortedByDescending(File::lastModified).orEmpty()
        var retainedBytes = 0L
        files.forEach { file ->
            retainedBytes += file.length()
            if (retainedBytes > DISK_BYTE_LIMIT) file.delete()
        }
    }

    private fun cacheKey(context: ContentRequestContext, apiPath: String): String =
        sha256("${namespaceKey(context)}|$apiPath")

    private fun namespaceKey(context: ContentRequestContext): String = sha256(
        listOf(
            context.namespace.serverIdentity,
            context.namespace.userId,
            context.namespace.authorizationVersion,
        ).joinToString("|"),
    )

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.encodeToByteArray())
        .joinToString("") { byte -> "%02x".format(byte) }
}

class CoverCacheException(message: String) : Exception(message)
