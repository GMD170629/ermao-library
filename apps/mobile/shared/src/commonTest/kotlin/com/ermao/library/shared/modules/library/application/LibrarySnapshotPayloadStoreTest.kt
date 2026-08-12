package com.ermao.library.shared.modules.library.application

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class LibrarySnapshotPayloadStoreTest {
    @Test
    fun payloadsAreIsolatedByServerUserAndAuthorizationVersion() {
        val store = InMemoryLibrarySnapshotPayloadStore()
        val first = PrivateDataNamespace("server-a", "user-a", 1).librarySnapshotNamespaceKey()
        val reauthorized = PrivateDataNamespace("server-a", "user-a", 2).librarySnapshotNamespaceKey()
        val otherUser = PrivateDataNamespace("server-a", "user-b", 1).librarySnapshotNamespaceKey()

        store.saveLibrarySnapshotPayload(first, "works|query|1", "private-payload")

        assertEquals("private-payload", store.loadLibrarySnapshotPayload(first, "works|query|1").value)
        assertNull(store.loadLibrarySnapshotPayload(reauthorized, "works|query|1").value)
        assertNull(store.loadLibrarySnapshotPayload(otherUser, "works|query|1").value)
    }

    @Test
    fun clearingOneNamespaceDoesNotTouchAnotherAccount() {
        val store = InMemoryLibrarySnapshotPayloadStore()
        val first = PrivateDataNamespace("server", "user-a", 1).librarySnapshotNamespaceKey()
        val second = PrivateDataNamespace("server", "user-b", 1).librarySnapshotNamespaceKey()
        store.saveLibrarySnapshotPayload(first, "works|query|1", "first")
        store.saveLibrarySnapshotPayload(second, "works|query|1", "second")

        store.clearLibrarySnapshotPayloads(first)

        assertNull(store.loadLibrarySnapshotPayload(first, "works|query|1").value)
        assertEquals("second", store.loadLibrarySnapshotPayload(second, "works|query|1").value)
    }
}
