package com.ermao.library.mobi.infrastructure

import kotlin.test.assertEquals
import org.junit.Test

class MobiCoreStatusTest {
    @Test
    fun stableStatusCodesRemainMapped() {
        assertEquals(MobiCoreStatus.DrmProtected, MobiCoreStatus.fromCode(5))
        assertEquals(MobiCoreStatus.LimitExceeded, MobiCoreStatus.fromCode(9))
        assertEquals(MobiCoreStatus.Internal, MobiCoreStatus.fromCode(Int.MAX_VALUE))
    }
}
