package com.ermao.library.shared.modules.servers

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.servers.domain.toSnapshot
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class ServerProfilePublicTest {
    @Test
    fun defaultGeneratorCreatesUuidV4ProfileIdsIndependentlyFromServerIdentity() {
        val generator = RandomProfileIdGenerator()

        val first = generator.generate()
        val second = generator.generate()

        assertTrue(UUID_V4.matches(first))
        assertTrue(UUID_V4.matches(second))
        assertNotEquals(first, second)
        assertNotEquals("server-identity", first)
    }

    @Test
    fun snapshotKeepsProfileIdAndServerIdentityAsSeparateFields() {
        val baseUrl = (ServerBaseUrl.parse("https://library.example/base") as ServerBaseUrlParseResult.Valid).baseUrl
        val snapshot = ServerProfile(
            id = "profile-id",
            displayName = "Home",
            baseUrl = baseUrl,
            serverIdentity = "server-identity",
            isActive = true,
            tlsMode = TlsMode.SystemTrust,
        ).toSnapshot()

        assertEquals("profile-id", snapshot.id)
        assertEquals("server-identity", snapshot.serverIdentity)
        assertEquals("https://library.example/base", snapshot.baseUrl)
        assertTrue(snapshot.isActive)
    }

    private companion object {
        val UUID_V4 = Regex(
            "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
    }
}
