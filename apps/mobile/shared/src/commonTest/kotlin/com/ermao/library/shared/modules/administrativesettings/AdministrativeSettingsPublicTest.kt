package com.ermao.library.shared.modules.administrativesettings

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class AdministrativeSettingsPublicTest {
    @Test
    fun contextNormalizesADeploymentBasePathWithoutExposingTransportTypes() {
        val context = createAdministrativeSettingsContext(
            profileId = "profile-1",
            displayName = "Books",
            baseUrl = "HTTPS://Books.Example/library/",
            serverIdentity = "server-1",
            acceptsInsecureTls = false,
        )

        assertEquals("https://books.example/library", context.baseUrl)
    }

    @Test
    fun contextRejectsNonHttpServers() {
        assertFailsWith<IllegalArgumentException> {
            createAdministrativeSettingsContext(
                profileId = "profile-1",
                displayName = "Books",
                baseUrl = "file:///private/library",
                serverIdentity = "server-1",
                acceptsInsecureTls = false,
            )
        }
    }
}
