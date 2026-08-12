package com.ermao.library.shared.modules.library.infrastructure

import android.content.Context
import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.library.application.LibrarySnapshotPayloadStore
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest

class AndroidLibrarySnapshotPayloadStore(context: Context) : LibrarySnapshotPayloadStore {
    private val rootDirectory = File(context.applicationContext.filesDir, "library-snapshots-v1")

    override fun loadLibrarySnapshotPayload(namespaceKey: String, payloadKey: String): PlatformStoragePayload =
        storageOperation("load") {
            val source = payloadFile(namespaceKey, payloadKey)
            PlatformStoragePayload(source.takeIf(File::isFile)?.readText())
        }

    override fun saveLibrarySnapshotPayload(namespaceKey: String, payloadKey: String, payload: String) {
        storageOperation("save") {
            val destination = payloadFile(namespaceKey, payloadKey)
            destination.parentFile?.mkdirs()
            val temporary = File(destination.parentFile, "${destination.name}.tmp")
            try {
                FileOutputStream(temporary).use { output ->
                    output.write(payload.encodeToByteArray())
                    output.fd.sync()
                }
                if (!temporary.renameTo(destination)) {
                    temporary.copyTo(destination, overwrite = true)
                    temporary.delete()
                }
            } finally {
                temporary.delete()
            }
        }
    }

    override fun removeLibrarySnapshotPayload(namespaceKey: String, payloadKey: String) {
        storageOperation("remove") { payloadFile(namespaceKey, payloadKey).delete() }
    }

    override fun clearLibrarySnapshotPayloads(namespaceKey: String) {
        storageOperation("clear") { namespaceDirectory(namespaceKey).deleteRecursively() }
    }

    private fun payloadFile(namespaceKey: String, payloadKey: String): File =
        File(namespaceDirectory(namespaceKey), "${sha256(payloadKey)}.json")

    private fun namespaceDirectory(namespaceKey: String): File = File(rootDirectory, sha256(namespaceKey))

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.encodeToByteArray())
        .joinToString("") { "%02x".format(it) }

    private fun <T> storageOperation(action: String, block: () -> T): T = try {
        block()
    } catch (error: Throwable) {
        throw PlatformStorageException("Unable to $action Library Discovery snapshot", error)
    }
}
