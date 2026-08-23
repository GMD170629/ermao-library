package com.ermao.library.bootstrap

import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class ErmaoLibraryRootTest {
    @Test
    fun savedServerIdentityChangeDoesNotRequestAnIncompatibleAlert() {
        assertFalse(
            shouldShowIncompatibleServerAlert(
                operationErrorCode = "SERVER_IDENTITY_CHANGED",
                reasonCode = "SERVER_IDENTITY_CHANGED",
            ),
        )
    }

    @Test
    fun actualProtocolIncompatibilityStillRequestsAnAlert() {
        assertTrue(
            shouldShowIncompatibleServerAlert(
                operationErrorCode = "UNSUPPORTED_PROTOCOL_VERSION",
                reasonCode = "UNSUPPORTED_PROTOCOL_VERSION",
            ),
        )
        assertFalse(
            shouldShowIncompatibleServerAlert(
                operationErrorCode = null,
                reasonCode = "UNSUPPORTED_PROTOCOL_VERSION",
            ),
        )
    }
}
