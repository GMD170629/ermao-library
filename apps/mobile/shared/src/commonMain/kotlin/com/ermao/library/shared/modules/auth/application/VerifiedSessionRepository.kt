package com.ermao.library.shared.modules.auth.application

import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord

interface VerifiedSessionRepository {
    suspend fun load(profileId: String): VerifiedSessionRecord?

    suspend fun save(record: VerifiedSessionRecord)

    suspend fun removeSession(profileId: String)
}

class InMemoryVerifiedSessionRepository : VerifiedSessionRepository {
    private val records = mutableMapOf<String, VerifiedSessionRecord>()

    override suspend fun load(profileId: String): VerifiedSessionRecord? = records[profileId]

    override suspend fun save(record: VerifiedSessionRecord) {
        records[record.profileId] = record
    }

    override suspend fun removeSession(profileId: String) {
        records.remove(profileId)
    }
}
