package com.ermao.library.shared.modules.auth.infrastructure

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

    private fun record() = ValidatedSessionRecord(
        profileId = "profile-1",
        serverIdentity = "server-1",
        userId = "user-1",
        email = "reader@example.com",
        displayName = "Reader",
        authorizationVersion = 7,
        lastValidatedAtEpochMillis = 1_000,
        expiresAtEpochMillis = 2_000,
        maxObservedWallClockEpochMillis = 1_000,
        status = OfflineEntitlementStatus.Valid,
    )

    private class MemoryStore(var payload: String? = null) : OfflineEntitlementPayloadStore {
        override fun loadEntitlements(): String? = payload
        override fun saveEntitlements(payload: String) {
            this.payload = payload
        }
    }
}
