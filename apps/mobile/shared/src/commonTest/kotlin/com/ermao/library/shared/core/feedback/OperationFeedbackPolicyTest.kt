package com.ermao.library.shared.core.feedback

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class OperationFeedbackPolicyTest {
    @Test fun onlyPlainSuccessUsesOneSecond() {
        assertEquals(1_000L, OperationFeedbackPolicy.timeoutMillis(OperationFeedbackKind.Success, Long.MAX_VALUE))
        for (kind in listOf(OperationFeedbackKind.PartialSuccess, OperationFeedbackKind.Failure, OperationFeedbackKind.Action)) {
            assertEquals(5_000L, OperationFeedbackPolicy.timeoutMillis(kind, 5_000L))
            assertEquals(Long.MAX_VALUE, OperationFeedbackPolicy.timeoutMillis(kind, Long.MAX_VALUE))
        }
    }

    @Test fun successCannotOverwriteAnOutcomeNeedingAttention() {
        assertTrue(OperationFeedbackPolicy.canReplace(OperationFeedbackKind.Success, OperationFeedbackKind.Success))
        for (kind in listOf(OperationFeedbackKind.PartialSuccess, OperationFeedbackKind.Failure, OperationFeedbackKind.Action)) {
            assertFalse(OperationFeedbackPolicy.canReplace(kind, OperationFeedbackKind.Success))
            assertTrue(OperationFeedbackPolicy.canReplace(OperationFeedbackKind.Success, kind))
        }
    }
}
