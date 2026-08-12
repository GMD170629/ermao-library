package com.ermao.library.shared.modules.library.application

import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace

/**
 * Non-generic persistence seam for private Library Discovery snapshots.
 * KMP owns the payload schema; platform adapters only perform atomic opaque-string I/O.
 */
interface LibrarySnapshotPayloadStore {
    @Throws(PlatformStorageException::class)
    fun loadLibrarySnapshotPayload(namespaceKey: String, payloadKey: String): PlatformStoragePayload

    @Throws(PlatformStorageException::class)
    fun saveLibrarySnapshotPayload(namespaceKey: String, payloadKey: String, payload: String)

    @Throws(PlatformStorageException::class)
    fun removeLibrarySnapshotPayload(namespaceKey: String, payloadKey: String)

    @Throws(PlatformStorageException::class)
    fun clearLibrarySnapshotPayloads(namespaceKey: String)
}

class InMemoryLibrarySnapshotPayloadStore : LibrarySnapshotPayloadStore {
    private val payloads = mutableMapOf<String, String>()

    override fun loadLibrarySnapshotPayload(namespaceKey: String, payloadKey: String): PlatformStoragePayload =
        PlatformStoragePayload(payloads[storageKey(namespaceKey, payloadKey)])

    override fun saveLibrarySnapshotPayload(namespaceKey: String, payloadKey: String, payload: String) {
        payloads[storageKey(namespaceKey, payloadKey)] = payload
    }

    override fun removeLibrarySnapshotPayload(namespaceKey: String, payloadKey: String) {
        payloads.remove(storageKey(namespaceKey, payloadKey))
    }

    override fun clearLibrarySnapshotPayloads(namespaceKey: String) {
        val prefix = "$namespaceKey|"
        payloads.keys.filter { it.startsWith(prefix) }.forEach(payloads::remove)
    }

    private fun storageKey(namespaceKey: String, payloadKey: String): String = "$namespaceKey|$payloadKey"
}

fun PrivateDataNamespace.librarySnapshotNamespaceKey(): String =
    "$serverIdentity|$userId|$authorizationVersion"
