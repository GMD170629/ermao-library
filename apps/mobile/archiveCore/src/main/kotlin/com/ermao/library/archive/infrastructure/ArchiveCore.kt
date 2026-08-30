package com.ermao.library.archive.infrastructure

import java.io.Closeable
import java.io.File

class ArchiveCoreException(
    val stableCode: String,
    detail: String,
) : Exception("Archive core failed: $stableCode ($detail)")

data class ArchiveCorePage(
    val index: Int,
    val path: String,
    val sizeBytes: Long,
)

class ArchiveCore private constructor(
    private var handle: Long,
) : Closeable {
    val pages: List<ArchiveCorePage> by lazy {
        val current = requireOpen()
        List(ArchiveCoreNative.pageCount(current)) { index ->
            ArchiveCorePage(
                index = index,
                path = ArchiveCoreNative.pagePath(current, index),
                sizeBytes = ArchiveCoreNative.pageSize(current, index),
            )
        }
    }

    @Synchronized
    fun readPage(index: Int): ByteArray {
        require(index in pages.indices) { "Archive page index is invalid" }
        return ArchiveCoreNative.readPage(requireOpen(), index)
    }

    @Synchronized
    override fun close() {
        val current = handle
        if (current == 0L) return
        handle = 0L
        ArchiveCoreNative.close(current)
    }

    private fun requireOpen(): Long = handle.takeIf { it != 0L }
        ?: throw IllegalStateException("Archive core handle is closed")

    companion object {
        val version: String get() = ArchiveCoreNative.version()

        fun open(
            file: File,
            maximumEntries: Int,
            maximumPageBytes: Long,
            maximumExpandedBytes: Long,
        ): ArchiveCore {
            val canonical = file.canonicalFile
            require(canonical.isFile) { "Archive file is missing" }
            require(maximumEntries > 0 && maximumPageBytes > 0 && maximumExpandedBytes > 0)
            return ArchiveCore(
                ArchiveCoreNative.open(
                    canonical.path.encodeToByteArray(),
                    maximumEntries,
                    maximumPageBytes,
                    maximumExpandedBytes,
                ),
            )
        }
    }
}

private object ArchiveCoreNative {
    init { System.loadLibrary("ermao_archive_jni") }

    external fun version(): String
    external fun open(
        pathUtf8: ByteArray,
        maximumEntries: Int,
        maximumPageBytes: Long,
        maximumExpandedBytes: Long,
    ): Long
    external fun close(handle: Long)
    external fun pageCount(handle: Long): Int
    external fun pagePath(handle: Long, index: Int): String
    external fun pageSize(handle: Long, index: Int): Long
    external fun readPage(handle: Long, index: Int): ByteArray
}
