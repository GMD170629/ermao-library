package com.ermao.library.shared.core.network

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ApiRedirectPolicyTest {
    @Test
    fun allowsSameOriginAndSameHostHttpToHttpsUpgrade() {
        assertTrue(RedirectPolicy.shouldFollow("https://books.example/api/a", "https://books.example/api/b"))
        assertTrue(RedirectPolicy.shouldFollow("http://books.example/api/a", "https://books.example/api/a"))
    }

    @Test
    fun rejectsCrossHostHttpsDowngradeAndSchemeChanges() {
        assertFalse(RedirectPolicy.shouldFollow("https://books.example/api/a", "https://other.example/api/a"))
        assertFalse(RedirectPolicy.shouldFollow("https://books.example/api/a", "http://books.example/api/a"))
        assertFalse(RedirectPolicy.shouldFollow("https://books.example/api/a", "ftp://books.example/api/a"))
    }

    @Test
    fun resolvesAbsoluteRootRelativeAndPathRelativeLocations() {
        assertEquals(
            "https://books.example/api/b",
            RedirectPolicy.resolve("https://books.example/api/a", "/api/b"),
        )
        assertEquals(
            "https://books.example/api/b",
            RedirectPolicy.resolve("https://books.example/api/a", "b"),
        )
    }
}
