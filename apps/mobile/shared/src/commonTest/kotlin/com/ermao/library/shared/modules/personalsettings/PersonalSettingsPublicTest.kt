package com.ermao.library.shared.modules.personalsettings

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class PersonalSettingsPublicTest {
    @Test
    fun contextFactoryUsesCanonicalBaseUrlAndTlsTypes() {
        val context =
            createPersonalSettingsContext(
                profileId = "profile-1",
                displayName = "Books",
                baseUrl = "https://Books.Example/library/",
                serverIdentity = "server-1",
                acceptsInsecureTls = true,
            )

        assertEquals("https://books.example/library", context.baseUrl)
        assertEquals(PersonalSettingsTlsMode.InsecureSkipAllValidation, context.tlsMode)
        assertEquals("profile-1", context.profileId)
    }

    @Test
    fun contextFactoryRejectsInvalidBaseUrl() {
        assertFailsWith<IllegalArgumentException> {
            createPersonalSettingsContext(
                profileId = "profile-1",
                displayName = "Books",
                baseUrl = "not-a-url",
                serverIdentity = "server-1",
                acceptsInsecureTls = false,
            )
        }
    }
}
