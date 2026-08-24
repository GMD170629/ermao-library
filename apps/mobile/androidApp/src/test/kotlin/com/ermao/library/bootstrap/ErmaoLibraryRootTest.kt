package com.ermao.library.bootstrap

import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class ErmaoLibraryRootTest {
    @Test
    fun actualProtocolIncompatibilityStillRequestsAnAlert() {
        assertTrue(
            shouldShowIncompatibleServerAlert(
                operationErrorCode = "UNSUPPORTED_PROTOCOL_VERSION",
            ),
        )
        assertFalse(
            shouldShowIncompatibleServerAlert(
                operationErrorCode = null,
            ),
        )
    }
}
