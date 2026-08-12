package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.auth.application.OfflineEntitlementRepository
import com.ermao.library.shared.modules.auth.domain.OfflineEntitlementStatus
import com.ermao.library.shared.modules.auth.domain.ValidatedSessionRecord
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

interface OfflineEntitlementPayloadStore {
    @Throws(PlatformStorageException::class)
    fun loadEntitlementsPayload(): PlatformStoragePayload

    @Throws(PlatformStorageException::class)
    fun saveEntitlements(payload: String)
}

class SerializedOfflineEntitlementRepository(
    private val store: OfflineEntitlementPayloadStore,
) : OfflineEntitlementRepository {
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = false }

    override suspend fun load(profileId: String): ValidatedSessionRecord? = decode().records[profileId]

    override suspend fun save(record: ValidatedSessionRecord) {
        val aggregate = decode()
        persist(aggregate.copy(records = aggregate.records + (record.profileId to record)))
    }

    override suspend fun revoke(profileId: String) {
        val aggregate = decode()
        val record = aggregate.records[profileId] ?: return
        persist(
            aggregate.copy(
                records = aggregate.records + (
                    profileId to record.copy(status = OfflineEntitlementStatus.RevokedLocally)
                ),
            ),
        )
    }

    override suspend fun removeEntitlement(profileId: String) {
        val aggregate = decode()
        persist(aggregate.copy(records = aggregate.records - profileId))
    }

    private fun decode(): EntitlementAggregateWire {
        val payload = store.loadEntitlementsPayload().value ?: return EntitlementAggregateWire()
        val aggregate = json.decodeFromString<EntitlementAggregateWire>(payload)
        require(aggregate.schemaVersion == SCHEMA_VERSION) { "Unsupported entitlement schema" }
        require(aggregate.records.all { (profileId, record) -> profileId == record.profileId }) {
            "Entitlement profile key mismatch"
        }
        return aggregate
    }

    private fun persist(aggregate: EntitlementAggregateWire) {
        store.saveEntitlements(json.encodeToString(aggregate))
    }

    private companion object {
        const val SCHEMA_VERSION = 1
    }
}

@Serializable
private data class EntitlementAggregateWire(
    val schemaVersion: Int = 1,
    val records: Map<String, ValidatedSessionRecord> = emptyMap(),
)
