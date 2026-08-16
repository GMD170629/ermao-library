package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlinx.coroutines.runBlocking

class SerializedVerifiedSessionRepositoryTest {
    @Test
    fun roundTripsAndRemovesVerifiedSessionWithoutAnExpiry() = runBlocking {
        val store = MemoryStore()
        val repository = SerializedVerifiedSessionRepository(store)
        val record = record()

        repository.save(record)

        assertEquals(record, repository.load("profile-1"))
        repository.removeSession("profile-1")
        assertNull(repository.load("profile-1"))
    }

    private fun record() = VerifiedSessionRecord(
        profileId = "profile-1",
        serverIdentity = "server-1",
        userId = "user-1",
        email = "reader@example.com",
        displayName = "Reader",
        authorizationVersion = 7,
        isAdmin = false,
        canManageSystem = false,
        allLibraryScopes = true,
        canViewManualImports = false,
        monitorFolderIds = emptyList(),
        lastValidatedAtEpochMillis = 1_000,
        avatarUrl = null,
        locale = "zh-CN",
    )

    private class MemoryStore(var payload: String? = null) : VerifiedSessionPayloadStore {
        override fun loadVerifiedSessionsPayload() = PlatformStoragePayload(payload)

        override fun saveVerifiedSessions(payload: String) {
            this.payload = payload
        }
    }
}
