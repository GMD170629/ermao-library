package com.ermao.library.shared.modules.servers.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ServerBaseUrlTest {
    @Test
    fun exposesNormalizedHostnameForAutomaticProfileNaming() {
        val parsed = assertIs<ServerBaseUrlParseResult.Valid>(
            ServerBaseUrl.parse("https://Books.Example:8443/library"),
        )

        assertEquals("books.example", parsed.baseUrl.hostName)
    }

    @Test
    fun normalizesSchemeHostDefaultPortAndDotSegments() {
        val result = ServerBaseUrl.parse(" HTTPS://Books.Example:443/library/a/../ ")

        val valid = assertIs<ServerBaseUrlParseResult.Valid>(result)
        assertEquals("https://books.example/library", valid.baseUrl.value)
        assertEquals("https://books.example/library/api/health", valid.baseUrl.resolveApiPath("/api/health"))
    }

    @Test
    fun preservesPathCaseWithoutLowercasingTheAuthorityAsAWhole() {
        val valid = assertIs<ServerBaseUrlParseResult.Valid>(
            ServerBaseUrl.parse("https://BOOKS.example/LibraryRoot"),
        )
        assertEquals("https://books.example/LibraryRoot", valid.baseUrl.value)
    }

    @Test
    fun rejectsUnsafeOrAmbiguousAuthorities() {
        listOf(
            "https:///missing-host",
            "https://example.com:0",
            "https://example.com:65536",
            "https://example.com:not-a-port",
            "https://user@example.com",
            "https://例子.测试",
            "https://bad..example",
            "https://-bad.example",
            "https://example.com\\evil",
            "https://example.com\u0001/path",
        ).forEach { raw ->
            assertIs<ServerBaseUrlParseResult.Invalid>(ServerBaseUrl.parse(raw), raw)
        }
    }
}
