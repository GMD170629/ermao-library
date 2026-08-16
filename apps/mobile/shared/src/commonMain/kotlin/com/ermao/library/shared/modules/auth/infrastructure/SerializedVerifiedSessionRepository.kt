package com.ermao.library.shared.modules.auth.infrastructure

import com.ermao.library.shared.core.storage.PlatformStorageException
import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.auth.application.VerifiedSessionRepository
import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

interface VerifiedSessionPayloadStore {
    @Throws(PlatformStorageException::class)
    fun loadVerifiedSessionsPayload(): PlatformStoragePayload

    @Throws(PlatformStorageException::class)
    fun saveVerifiedSessions(payload: String)
}

class SerializedVerifiedSessionRepository(
    private val store: VerifiedSessionPayloadStore,
) : VerifiedSessionRepository {
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = false }

    override suspend fun load(profileId: String): VerifiedSessionRecord? = decode().records[profileId]

    override suspend fun save(record: VerifiedSessionRecord) {
        val aggregate = decode()
        persist(aggregate.copy(records = aggregate.records + (record.profileId to record)))
    }

    override suspend fun removeSession(profileId: String) {
        val aggregate = decode()
        persist(aggregate.copy(records = aggregate.records - profileId))
    }

    private fun decode(): VerifiedSessionAggregateWire {
        val payload = store.loadVerifiedSessionsPayload().value ?: return VerifiedSessionAggregateWire()
        val aggregate = json.decodeFromString<VerifiedSessionAggregateWire>(payload)
        require(aggregate.schemaVersion == SCHEMA_VERSION) { "Unsupported verified-session schema" }
        require(aggregate.records.all { (profileId, record) -> profileId == record.profileId }) {
            "Verified-session profile key mismatch"
        }
        return aggregate
    }

    private fun persist(aggregate: VerifiedSessionAggregateWire) {
        store.saveVerifiedSessions(json.encodeToString(aggregate))
    }

    private companion object {
        const val SCHEMA_VERSION = 1
    }
}

@Serializable
private data class VerifiedSessionAggregateWire(
    val schemaVersion: Int = 1,
    val records: Map<String, VerifiedSessionRecord> = emptyMap(),
)
