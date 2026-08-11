package com.ermao.library.shared.modules.auth.domain

import kotlinx.serialization.Serializable

private const val OFFLINE_GRACE_MILLIS = 30L * 24L * 60L * 60L * 1_000L

@Serializable
enum class OfflineEntitlementStatus {
    Valid,
    Expired,
    RevokedLocally,
}

@Serializable
data class ValidatedSessionRecord(
    val profileId: String,
    val serverIdentity: String,
    val userId: String,
    val email: String,
    val displayName: String,
    val authorizationVersion: Long,
    val lastValidatedAtEpochMillis: Long,
    val expiresAtEpochMillis: Long,
    val maxObservedWallClockEpochMillis: Long,
    val status: OfflineEntitlementStatus,
)

fun interface EpochMillisClock {
    fun now(): Long
}

object SystemEpochMillisClock : EpochMillisClock {
    override fun now(): Long = platformEpochMillis()
}

internal expect fun platformEpochMillis(): Long

class OfflineEntitlementPolicy(
    private val validityMillis: Long = OFFLINE_GRACE_MILLIS,
) {
    fun validated(
        profileId: String,
        identity: SessionIdentity,
        nowEpochMillis: Long,
        previousRecord: ValidatedSessionRecord? = null,
    ): ValidatedSessionRecord {
        val matchingPrevious = previousRecord?.takeIf {
            it.profileId == profileId &&
                it.serverIdentity == identity.namespace.serverIdentity &&
                it.userId == identity.userId
        }
        val rollbackDetected = matchingPrevious != null &&
            nowEpochMillis < matchingPrevious.maxObservedWallClockEpochMillis
        return ValidatedSessionRecord(
            profileId = profileId,
            serverIdentity = identity.namespace.serverIdentity,
            userId = identity.userId,
            email = identity.email,
            displayName = identity.displayName,
            authorizationVersion = identity.namespace.authorizationVersion,
            lastValidatedAtEpochMillis = nowEpochMillis,
            expiresAtEpochMillis = if (rollbackDetected) nowEpochMillis else nowEpochMillis + validityMillis,
            maxObservedWallClockEpochMillis = maxOf(
                nowEpochMillis,
                matchingPrevious?.maxObservedWallClockEpochMillis ?: nowEpochMillis,
            ),
            status = if (rollbackDetected) {
                OfflineEntitlementStatus.Expired
            } else {
                OfflineEntitlementStatus.Valid
            },
        )
    }

    fun evaluate(
        record: ValidatedSessionRecord,
        nowEpochMillis: Long,
    ): OfflineEntitlementEvaluation {
        if (record.status == OfflineEntitlementStatus.RevokedLocally) {
            return OfflineEntitlementEvaluation.Revoked
        }
        if (record.status == OfflineEntitlementStatus.Expired) {
            return OfflineEntitlementEvaluation.Expired
        }
        if (nowEpochMillis < record.maxObservedWallClockEpochMillis) {
            return OfflineEntitlementEvaluation.Expired
        }
        if (nowEpochMillis >= record.expiresAtEpochMillis) {
            return OfflineEntitlementEvaluation.Expired
        }
        return OfflineEntitlementEvaluation.Valid(
            record.copy(maxObservedWallClockEpochMillis = nowEpochMillis),
        )
    }
}

sealed interface OfflineEntitlementEvaluation {
    data class Valid(val updatedRecord: ValidatedSessionRecord) : OfflineEntitlementEvaluation
    data object Expired : OfflineEntitlementEvaluation
    data object Revoked : OfflineEntitlementEvaluation
}
