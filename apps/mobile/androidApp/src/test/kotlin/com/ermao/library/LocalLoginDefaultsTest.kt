package com.ermao.library

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class LocalLoginDefaultsTest {
    @Test
    fun debugDefaultsUseTheWebOriginAndFillTheTestCredentials() {
        val defaults = localLoginDefaults()

        assertEquals("http://192.168.50.179:3000", defaults.serverAddress)
        assertFalse(defaults.serverAddress.contains("10.0.2.2"))
        assertFalse(defaults.serverAddress.endsWith(":8000"))
        assertEquals("1821483963@qq.com", defaults.email)
        assertEquals("1234567890", defaults.password)
    }
}
