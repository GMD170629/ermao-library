package com.ermao.library.features.downloads.infrastructure

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

class AndroidDownloadCatalog(
    private val rootDirectory: File,
) {
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = false; encodeDefaults = true }
    private val mutex = Mutex()
    private val revision = MutableStateFlow(0L)
    private val revisionCounter = AtomicLong()

    fun observe(namespace: AndroidDownloadNamespace): Flow<List<AndroidDownloadRecord>> = revision.map {
        records(namespace)
    }

    suspend fun records(namespace: AndroidDownloadNamespace): List<AndroidDownloadRecord> = mutex.withLock {
        readPayload(namespace).records.sortedByDescending(AndroidDownloadRecord::updatedAtEpochMillis)
    }

    suspend fun record(namespace: AndroidDownloadNamespace, taskId: String): AndroidDownloadRecord? =
        records(namespace).firstOrNull { it.taskId == taskId }

    suspend fun upsert(record: AndroidDownloadRecord): List<AndroidDownloadRecord> {
        var replaced = emptyList<AndroidDownloadRecord>()
        mutate(record.namespace) { records ->
            replaced = records.filter { it.taskId == record.taskId }
            records.filterNot { it.taskId == record.taskId } + record
        }
        return replaced
    }

    suspend fun remove(namespace: AndroidDownloadNamespace, taskId: String): AndroidDownloadRecord? {
        var removed: AndroidDownloadRecord? = null
        mutate(namespace) { records ->
            removed = records.firstOrNull { it.taskId == taskId }
            records.filterNot { it.taskId == taskId }
        }
        return removed
    }

    suspend fun clear(namespace: AndroidDownloadNamespace): List<AndroidDownloadRecord> = mutex.withLock {
        val current = readPayload(namespace).records
        val directory = namespaceDirectory(namespace)
        if (directory.exists() && !directory.deleteRecursively()) {
            throw AndroidDownloadStorageException("Unable to clear managed downloads")
        }
        publishRevision()
        current
    }

    private suspend fun mutate(
        namespace: AndroidDownloadNamespace,
        transform: (List<AndroidDownloadRecord>) -> List<AndroidDownloadRecord>,
    ) = mutex.withLock {
        val current = readPayload(namespace).records
        writePayload(namespace, CatalogPayload(records = transform(current)))
        publishRevision()
    }

    private suspend fun readPayload(namespace: AndroidDownloadNamespace): CatalogPayload = withContext(Dispatchers.IO) {
        val file = catalogFile(namespace)
        if (!file.isFile) return@withContext CatalogPayload()
        try {
            val decoded = json.decodeFromString<CatalogPayload>(file.readText())
            require(decoded.schemaVersion in setOf(LEGACY_SINGLE_ASSET_SCHEMA_VERSION, CATALOG_SCHEMA_VERSION))
            val payload = if (decoded.schemaVersion == LEGACY_SINGLE_ASSET_SCHEMA_VERSION) {
                decoded.copy(schemaVersion = CATALOG_SCHEMA_VERSION)
            } else {
                decoded
            }
            require(payload.records.all { it.namespace == namespace })
            require(payload.records.map(AndroidDownloadRecord::taskId).distinct().size == payload.records.size)
            if (decoded.schemaVersion != payload.schemaVersion) writePayloadFile(namespace, payload)
            payload
        } catch (error: SerializationException) {
            invalidCatalog(error)
        } catch (error: IllegalArgumentException) {
            invalidCatalog(error)
        }
    }

    private fun invalidCatalog(
        cause: Exception,
    ): CatalogPayload {
        throw AndroidDownloadStorageException("Managed download catalog is invalid; existing files were preserved", cause)
    }

    private suspend fun writePayload(namespace: AndroidDownloadNamespace, payload: CatalogPayload) = withContext(Dispatchers.IO) {
        writePayloadFile(namespace, payload)
    }

    private fun writePayloadFile(namespace: AndroidDownloadNamespace, payload: CatalogPayload) {
        val destination = catalogFile(namespace)
        destination.parentFile?.mkdirs()
        val temporary = File(destination.parentFile, "${destination.name}.tmp")
        try {
            FileOutputStream(temporary).use { output ->
                output.write(json.encodeToString(CatalogPayload.serializer(), payload).encodeToByteArray())
                output.fd.sync()
            }
            atomicReplace(temporary, destination)
        } catch (error: java.io.IOException) {
            throw AndroidDownloadStorageException("Unable to save managed download catalog", error)
        } finally {
            temporary.delete()
        }
    }

    private fun publishRevision() {
        revision.value = revisionCounter.incrementAndGet()
    }

    private fun catalogFile(namespace: AndroidDownloadNamespace): File = File(namespaceDirectory(namespace), "catalog.json")

    private fun namespaceDirectory(namespace: AndroidDownloadNamespace): File = File(
        rootDirectory,
        sha256("${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"),
    )

    private fun catalogKey(record: AndroidDownloadRecord): String =
        "${record.bookId}:${record.resourceId}:${record.assetId}"

    @Serializable
    private data class CatalogPayload(
        val schemaVersion: Int = CATALOG_SCHEMA_VERSION,
        val records: List<AndroidDownloadRecord> = emptyList(),
    )

    private companion object {
        /**
         * Catalog v4 adds completed Resource bundles. V3 already has stable
         * Book/Resource/Asset ownership, so its completed single-file records
         * migrate losslessly through the new record defaults.
         */
        const val LEGACY_SINGLE_ASSET_SCHEMA_VERSION = 3
        const val CATALOG_SCHEMA_VERSION = 4
    }
}

private fun File.deleteManagedArtifact() {
    if (exists() && !deleteRecursively()) {
        throw AndroidDownloadStorageException("Unable to delete legacy managed download")
    }
}

class AndroidDownloadStorageException(message: String, cause: Throwable? = null) : Exception(message, cause)

internal fun atomicReplace(source: File, destination: File) {
    try {
        java.nio.file.Files.move(
            source.toPath(),
            destination.toPath(),
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,
            java.nio.file.StandardCopyOption.REPLACE_EXISTING,
        )
    } catch (_: java.nio.file.AtomicMoveNotSupportedException) {
        java.nio.file.Files.move(
            source.toPath(),
            destination.toPath(),
            java.nio.file.StandardCopyOption.REPLACE_EXISTING,
        )
    }
}

internal fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
    .digest(value.encodeToByteArray())
    .joinToString("") { byte -> "%02x".format(byte) }
