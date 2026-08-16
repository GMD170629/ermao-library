package com.ermao.library.features.workmanagement.infrastructure

import java.io.ByteArrayInputStream
import kotlin.test.assertContentEquals
import kotlin.test.assertNull
import org.junit.Test

class AndroidCoverSelectionReaderTest {
    @Test
    fun boundedReadReturnsBytesAtTheLimit() {
        val bytes = ByteArray(32) { it.toByte() }

        assertContentEquals(bytes, ByteArrayInputStream(bytes).readAtMost(32))
    }

    @Test
    fun boundedReadRejectsOneByteBeyondTheLimit() {
        val bytes = ByteArray(33) { it.toByte() }

        assertNull(ByteArrayInputStream(bytes).readAtMost(32))
    }
}
