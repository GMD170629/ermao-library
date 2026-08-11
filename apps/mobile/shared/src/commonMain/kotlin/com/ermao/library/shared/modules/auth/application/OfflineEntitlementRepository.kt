package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.modules.auth.domain.ValidatedSessionRecord

interface OfflineEntitlementRepository {
    suspend fun load(profileId: String): ValidatedSessionRecord?

    suspend fun save(record: ValidatedSessionRecord)

    suspend fun revoke(profileId: String)

    suspend fun removeEntitlement(profileId: String)
}

class InMemoryOfflineEntitlementRepository : OfflineEntitlementRepository {
    private val records = mutableMapOf<String, ValidatedSessionRecord>()

    override suspend fun load(profileId: String): ValidatedSessionRecord? = records[profileId]

    override suspend fun save(record: ValidatedSessionRecord) {
        records[record.profileId] = record
    }

    override suspend fun revoke(profileId: String) {
        records[profileId]?.let { records[profileId] = it.copy(status = com.ermao.library.shared.modules.auth.domain.OfflineEntitlementStatus.RevokedLocally) }
    }

    override suspend fun removeEntitlement(profileId: String) {
        records.remove(profileId)
    }
}
