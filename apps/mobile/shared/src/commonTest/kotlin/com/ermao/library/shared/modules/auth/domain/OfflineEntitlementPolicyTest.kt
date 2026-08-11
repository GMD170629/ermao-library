package com.ermao.library.shared.modules.auth.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class OfflineEntitlementPolicyTest {
    private val policy = OfflineEntitlementPolicy()
    private val identity = SessionIdentity(
        userId = "user-1",
        email = "reader@example.com",
        displayName = "Reader",
        namespace = PrivateDataNamespace("server-1", "user-1", 7),
    )

    @Test
    fun successfulValidationCreatesAThirtyDayEntitlement() {
        val record = policy.validated("profile-1", identity, nowEpochMillis = 1_000)

        assertEquals(2_592_001_000L, record.expiresAtEpochMillis)
        assertEquals(OfflineEntitlementStatus.Valid, record.status)
    }

    @Test
    fun exactExpiryBoundaryIsExpired() {
        val record = policy.validated("profile-1", identity, nowEpochMillis = 1_000)

        assertIs<OfflineEntitlementEvaluation.Expired>(
            policy.evaluate(record, record.expiresAtEpochMillis),
        )
    }

    @Test
    fun wallClockRollbackExpiresTheEntitlement() {
        val record = policy.validated("profile-1", identity, nowEpochMillis = 10_000)
        val advanced = assertIs<OfflineEntitlementEvaluation.Valid>(
            policy.evaluate(record, 20_000),
        ).updatedRecord

        assertIs<OfflineEntitlementEvaluation.Expired>(policy.evaluate(advanced, 19_999))
    }

    @Test
    fun successfulOnlineValidationDoesNotEraseAPersistedRollbackSentinel() {
        val futureRecord = policy.validated("profile-1", identity, nowEpochMillis = 20_000)

        val refreshedDuringRollback = policy.validated(
            "profile-1",
            identity,
            nowEpochMillis = 10_000,
            previousRecord = futureRecord,
        )

        assertEquals(OfflineEntitlementStatus.Expired, refreshedDuringRollback.status)
        assertEquals(20_000, refreshedDuringRollback.maxObservedWallClockEpochMillis)
        assertIs<OfflineEntitlementEvaluation.Expired>(policy.evaluate(refreshedDuringRollback, 10_001))
    }

    @Test
    fun locallyRevokedEntitlementCannotBeReentered() {
        val record = policy.validated("profile-1", identity, nowEpochMillis = 1_000).copy(
            status = OfflineEntitlementStatus.RevokedLocally,
        )

        assertIs<OfflineEntitlementEvaluation.Revoked>(policy.evaluate(record, 2_000))
    }
}
