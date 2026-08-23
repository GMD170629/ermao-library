@file:Suppress("PARAMETER_NAME_CHANGED_ON_OVERRIDE")

package com.ermao.library.features.reader.infrastructure

import android.content.Context
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressJson
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.io.File
import java.io.FileOutputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal class AndroidReaderProgressStore(
    context: Context,
    private val namespace: ReaderSyncNamespace? = null,
    private val codec: ReaderProgressJson = ReaderProgressJson(),
) : ReaderProgressStore {
    private val progressRoot = namespace?.let { value ->
        File(
            File(File(context.filesDir, PROGRESS_DIRECTORY), sha256(readerAccountStorageKey(value))),
            sha256(value.stableKey),
        )
    } ?: File(File(context.filesDir, PROGRESS_DIRECTORY), "unscoped")

    override suspend fun load(resourceId: String): ReaderProgress? = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank()) { "Reader resource id is blank" }
        val file = progressFile(resourceId)
        if (!file.exists()) return@withContext null
        require(file.isFile && !Files.isSymbolicLink(file.toPath())) { "Reader progress path is invalid" }
        val progress = try {
            codec.decode(file.readText(Charsets.UTF_8))
        } catch (_: IllegalArgumentException) {
            Files.deleteIfExists(file.toPath())
            return@withContext null
        }
        progress.also {
            require(progress.resourceId == resourceId) { "Reader progress identity does not match its storage key" }
        }
    }

    override suspend fun save(progress: ReaderProgress): Unit = withContext(Dispatchers.IO) {
        progressRoot.mkdirs()
        require(progressRoot.isDirectory) { "Reader progress root is unavailable" }
        val target = progressFile(progress.resourceId)
        val temporary = File(progressRoot, ".${target.name}.${System.nanoTime()}.tmp")
        try {
            FileOutputStream(temporary).use { output ->
                output.write(codec.encode(progress).toByteArray(Charsets.UTF_8))
                output.fd.sync()
            }
            try {
                Files.move(
                    temporary.toPath(),
                    target.toPath(),
                    StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING,
                )
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        } finally {
            temporary.delete()
        }
    }

    override suspend fun delete(resourceId: String): Unit = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank()) { "Reader resource id is blank" }
        Files.deleteIfExists(progressFile(resourceId).toPath())
    }

    private fun progressFile(resourceId: String): File = File(progressRoot, sha256(resourceId) + JSON_SUFFIX)

    companion object {
        const val PROGRESS_DIRECTORY = "reader-progress-v3"
        const val JSON_SUFFIX = ".json"

        internal suspend fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) =
            withContext(Dispatchers.IO) {
                val directory = File(
                    File(context.filesDir, PROGRESS_DIRECTORY),
                    sha256(readerAccountStorageKey(namespace)),
                )
                if (directory.exists()) {
                    check(directory.deleteRecursively()) { "Unable to clear Reader progress namespace" }
                }
            }
    }
}
