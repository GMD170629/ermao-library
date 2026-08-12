package com.ermao.library.features.reader.infrastructure

import android.content.Context
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressJson
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import java.io.File
import java.io.FileOutputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal class AndroidReaderProgressStore(
    context: Context,
    private val codec: ReaderProgressJson = ReaderProgressJson(),
) : ReaderProgressStore {
    private val progressRoot = File(context.filesDir, PROGRESS_DIRECTORY)

    override suspend fun load(sourceId: String): ReaderProgress? = withContext(Dispatchers.IO) {
        require(sourceId.isNotBlank()) { "Reader source id is blank" }
        val file = progressFile(sourceId)
        if (!file.exists()) return@withContext null
        require(file.isFile && !Files.isSymbolicLink(file.toPath())) { "Reader progress path is invalid" }
        codec.decode(file.readText(Charsets.UTF_8)).also { progress ->
            require(progress.sourceId == sourceId) { "Reader progress identity does not match its storage key" }
        }
    }

    override suspend fun save(progress: ReaderProgress): Unit = withContext(Dispatchers.IO) {
        progressRoot.mkdirs()
        require(progressRoot.isDirectory) { "Reader progress root is unavailable" }
        val target = progressFile(progress.sourceId)
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

    override suspend fun delete(sourceId: String): Unit = withContext(Dispatchers.IO) {
        require(sourceId.isNotBlank()) { "Reader source id is blank" }
        Files.deleteIfExists(progressFile(sourceId).toPath())
    }

    private fun progressFile(sourceId: String): File = File(progressRoot, sha256(sourceId) + JSON_SUFFIX)

    private companion object {
        const val PROGRESS_DIRECTORY = "reader-progress"
        const val JSON_SUFFIX = ".json"
    }
}
