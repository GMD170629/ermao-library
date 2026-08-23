package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_DOCUMENT_CACHE_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_NAMESPACE_CACHE_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MEMORY_CACHE_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Private persistent chunks. PDFium's synchronous callback uses [readCached] and never performs I/O over the network. */
internal class AndroidPdfRangeCache(private val rootDirectory: File) {
    private val lock = Any()
    private val hotChunks = LinkedHashMap<String, ByteArray>(16, 0.75f, true)
    private var hotBytes = 0

    fun isCached(identity: PdfRangeCacheIdentity, offset: Long, count: Int): Boolean = synchronized(lock) {
        cachedSlices(identity, offset, count) != null
    }

    fun readCached(identity: PdfRangeCacheIdentity, offset: Long, count: Int): ByteArray? = synchronized(lock) {
        val slices = cachedSlices(identity, offset, count) ?: return null
        val result = ByteArray(count)
        var destinationOffset = 0
        slices.forEach { slice ->
            val (chunk, offsetInChunk, readable) = slice
            val bytes = readHotChunk(chunk) ?: return null
            bytes.copyInto(result, destinationOffset, offsetInChunk, offsetInChunk + readable)
            chunk.setLastModified(System.currentTimeMillis())
            destinationOffset += readable
        }
        result
    }

    private fun cachedSlices(identity: PdfRangeCacheIdentity, offset: Long, count: Int): List<CachedSlice>? {
        if (offset < 0 || count <= 0 || offset > Long.MAX_VALUE - count) return null
        val slices = mutableListOf<CachedSlice>()
        var remaining = count
        var cursor = offset
        while (remaining > 0) {
            val chunkIndex = cursor / PDF_RANGE_CHUNK_BYTES
            val offsetInChunk = (cursor % PDF_RANGE_CHUNK_BYTES).toInt()
            val chunk = chunkFile(identity, chunkIndex)
            if (!isSafeChunk(chunk) || offsetInChunk >= chunk.length()) return null
            val readable = minOf(remaining, chunk.length().toInt() - offsetInChunk)
            slices += CachedSlice(chunk, offsetInChunk, readable)
            remaining -= readable
            cursor += readable
        }
        return slices
    }

    suspend fun writeAlignedRange(
        identity: PdfRangeCacheIdentity,
        begin: Long,
        bytes: ByteArray,
        protectedChunkIndices: Set<Long> = emptySet(),
    ): Unit = withContext(Dispatchers.IO) {
        require(begin >= 0 && begin % PDF_RANGE_CHUNK_BYTES == 0L)
        require(bytes.isNotEmpty())
        synchronized(lock) {
            var sourceOffset = 0
            var chunkIndex = begin / PDF_RANGE_CHUNK_BYTES
            while (sourceOffset < bytes.size) {
                val count = minOf(PDF_RANGE_CHUNK_BYTES, bytes.size - sourceOffset)
                writeChunk(identity, chunkIndex, bytes, sourceOffset, count)
                sourceOffset += count
                chunkIndex += 1
            }
            evict(identity, protectedChunkIndices + ((begin / PDF_RANGE_CHUNK_BYTES) until chunkIndex))
        }
    }

    suspend fun clearNamespace(identity: PdfRangeCacheIdentity): Unit = withContext(Dispatchers.IO) {
        clearNamespace(identity.namespace)
    }

    suspend fun clearNamespace(namespace: ReaderSyncNamespace): Unit = withContext(Dispatchers.IO) {
        synchronized(lock) {
            val directory = namespaceDirectory(namespace)
            if (directory.exists()) {
                removeHotChunks(directory)
                directory.deleteRecursively()
            }
        }
    }

    /** Authorization/user switches invalidate old generations for this account only. */
    suspend fun activateNamespace(namespace: ReaderSyncNamespace): Unit = withContext(Dispatchers.IO) {
        synchronized(lock) {
            val accountDirectory = File(root(), sha256(readerAccountStorageKey(namespace)))
            val activeName = sha256(namespace.stableKey)
            accountDirectory.mkdirs()
            accountDirectory.listFiles()?.forEach { candidate ->
                if (candidate.isDirectory && candidate.name != activeName) {
                    removeHotChunks(candidate)
                    candidate.deleteRecursively()
                }
            }
            namespaceDirectory(namespace).mkdirs()
        }
    }

    private fun writeChunk(
        identity: PdfRangeCacheIdentity,
        chunkIndex: Long,
        bytes: ByteArray,
        sourceOffset: Int,
        count: Int,
    ) {
        val destination = chunkFile(identity, chunkIndex)
        destination.parentFile?.mkdirs()
        require(destination.parentFile?.isDirectory == true)
        val temporary = File(destination.parentFile, ".${destination.name}.${System.nanoTime()}.tmp")
        try {
            FileOutputStream(temporary).use { output ->
                output.write(bytes, sourceOffset, count)
                output.fd.sync()
            }
            atomicReplace(temporary, destination)
            destination.setLastModified(System.currentTimeMillis())
            storeHotChunk(destination, bytes.copyOfRange(sourceOffset, sourceOffset + count))
        } finally {
            temporary.delete()
        }
    }

    private fun evict(identity: PdfRangeCacheIdentity, protectedChunkIndices: Set<Long>) {
        val protected = protectedChunkIndices.mapTo(mutableSetOf()) { chunkFile(identity, it).absolutePath }
        val document = documentDirectory(identity)
        evictFiles(document.walkTopDown().filter(::isSafeChunk).toList(), PDF_RANGE_DOCUMENT_CACHE_BYTES, protected)
        val namespace = namespaceDirectory(identity)
        evictFiles(namespace.walkTopDown().filter(::isSafeChunk).toList(), PDF_RANGE_NAMESPACE_CACHE_BYTES, protected)
        namespace.walkBottomUp().filter { it.isDirectory && it != namespace }.forEach { directory ->
            if (directory.list().isNullOrEmpty()) directory.delete()
        }
    }

    private fun evictFiles(files: List<File>, limit: Long, protected: Set<String>) {
        var total = files.sumOf { it.length() }
        files.sortedWith(compareBy<File> { it.lastModified() }.thenBy { it.absolutePath }).forEach { file ->
            if (total <= limit) return
            if (file.absolutePath in protected) return@forEach
            val length = file.length()
            if (file.delete()) {
                removeHotChunk(file)
                total -= length
            }
        }
    }

    private fun readHotChunk(file: File): ByteArray? {
        hotChunks[file.absolutePath]?.let { return it }
        val length = file.length().toInt()
        if (length !in 1..PDF_RANGE_CHUNK_BYTES) return null
        val bytes = ByteArray(length)
        RandomAccessFile(file, "r").use { input ->
            if (input.read(bytes) != length) return null
        }
        storeHotChunk(file, bytes)
        return bytes
    }

    private fun storeHotChunk(file: File, bytes: ByteArray) {
        hotChunks.remove(file.absolutePath)?.let { hotBytes -= it.size }
        hotChunks[file.absolutePath] = bytes
        hotBytes += bytes.size
        val iterator = hotChunks.entries.iterator()
        while (hotBytes > PDF_RANGE_MEMORY_CACHE_BYTES && iterator.hasNext()) {
            val oldest = iterator.next()
            hotBytes -= oldest.value.size
            iterator.remove()
        }
    }

    private fun removeHotChunk(file: File) {
        hotChunks.remove(file.absolutePath)?.let { hotBytes -= it.size }
    }

    private fun removeHotChunks(directory: File) {
        val prefix = directory.absolutePath + File.separator
        val iterator = hotChunks.entries.iterator()
        while (iterator.hasNext()) {
            val entry = iterator.next()
            if (entry.key.startsWith(prefix)) {
                hotBytes -= entry.value.size
                iterator.remove()
            }
        }
    }

    private fun isSafeChunk(file: File): Boolean = file.isFile &&
        !Files.isSymbolicLink(file.toPath()) &&
        file.name.startsWith(CHUNK_PREFIX) &&
        file.name.endsWith(CHUNK_SUFFIX) &&
        file.length() in 1..PDF_RANGE_CHUNK_BYTES.toLong()

    private fun chunkFile(identity: PdfRangeCacheIdentity, chunkIndex: Long): File {
        require(chunkIndex >= 0)
        return File(documentDirectory(identity), "$CHUNK_PREFIX$chunkIndex$CHUNK_SUFFIX")
    }

    private fun documentDirectory(identity: PdfRangeCacheIdentity): File =
        File(namespaceDirectory(identity), sha256(identity.resourceId))

    private fun namespaceDirectory(identity: PdfRangeCacheIdentity): File =
        namespaceDirectory(identity.namespace)

    private fun namespaceDirectory(namespace: ReaderSyncNamespace): File =
        File(
            File(root(), sha256(readerAccountStorageKey(namespace))),
            sha256(namespace.stableKey),
        )

    private fun root(): File {
        rootDirectory.mkdirs()
        require(rootDirectory.isDirectory && !Files.isSymbolicLink(rootDirectory.toPath()))
        return rootDirectory
    }

    private fun atomicReplace(source: File, destination: File) {
        try {
            Files.move(
                source.toPath(),
                destination.toPath(),
                StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(source.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }

    private companion object {
        const val CHUNK_PREFIX = "chunk-"
        const val CHUNK_SUFFIX = ".bin"
    }

    private data class CachedSlice(val file: File, val offset: Int, val length: Int)
}
