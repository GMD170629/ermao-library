package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.auth.domain.OfflineEntitlementStatus
import com.ermao.library.shared.modules.auth.domain.ValidatedSessionRecord
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlinx.coroutines.runBlocking

class SerializedOfflineEntitlementRepositoryTest {
    @Test
    fun roundTripsRevokesAndRemovesPerProfileRecords() = runBlocking {
        val store = MemoryStore()
        val repository = SerializedOfflineEntitlementRepository(store)
        val record = record()

        repository.save(record)
        assertEquals(record, repository.load("profile-1"))
        repository.revoke("profile-1")
        assertEquals(OfflineEntitlementStatus.RevokedLocally, repository.load("profile-1")?.status)
        repository.removeEntitlement("profile-1")
        assertEquals(null, repository.load("profile-1"))
    }

    @Test
    fun unknownSchemaFailsClosedWithoutOverwritingPayload() = runBlocking {
        val payload = """{"schemaVersion":99,"records":{}}"""
        val store = MemoryStore(payload)
        val repository = SerializedOfflineEntitlementRepository(store)

        assertFailsWith<IllegalArgumentException> { repository.load("profile-1") }
        assertEquals(payload, store.payload)
    }

    @Test
    fun schemaOnePayloadWithoutNewIdentityFieldsRemainsReadable() = runBlocking {
        val payload =
            """{"schemaVersion":1,"records":{"profile-1":{"profileId":"profile-1","serverIdentity":"server-1","userId":"user-1","email":"reader@example.com","displayName":"Reader","authorizationVersion":7,"lastValidatedAtEpochMillis":1000,"expiresAtEpochMillis":2000,"maxObservedWallClockEpochMillis":1000,"status":"Valid"}}}"""
        val repository = SerializedOfflineEntitlementRepository(MemoryStore(payload))

        val record = requireNotNull(repository.load("profile-1"))

        assertEquals(null, record.avatarUrl)
        assertEquals(null, record.locale)
    }

    private fun record() = ValidatedSessionRecord(
        profileId = "profile-1",
        serverIdentity = "server-1",
        userId = "user-1",
        email = "reader@example.com",
        displayName = "Reader",
        avatarUrl = "/api/auth/avatar",
        locale = "en-US",
        authorizationVersion = 7,
        lastValidatedAtEpochMillis = 1_000,
        expiresAtEpochMillis = 2_000,
        maxObservedWallClockEpochMillis = 1_000,
        status = OfflineEntitlementStatus.Valid,
    )

    private class MemoryStore(var payload: String? = null) : OfflineEntitlementPayloadStore {
        override fun loadEntitlementsPayload() = PlatformStoragePayload(payload)
        override fun saveEntitlements(payload: String) {
            this.payload = payload
        }
    }
}
