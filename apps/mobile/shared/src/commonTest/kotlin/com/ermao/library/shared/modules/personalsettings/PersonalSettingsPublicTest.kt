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

    @Test
    fun validationRulesAreAvailableToEveryPlatform() {
        assertEquals(true, isValidPersonalSettingsDisplayName(" Reader "))
        assertEquals(false, isValidPersonalSettingsDisplayName("x".repeat(41)))
        assertEquals(true, isValidPersonalSettingsEmail(" reader@example.com "))
        assertEquals(false, isValidPersonalSettingsEmail("not-an-email"))
        assertEquals(true, isValidPersonalSettingsCurrentPassword("current"))
        assertEquals(false, isValidPersonalSettingsCurrentPassword("x".repeat(129)))
        assertEquals(true, isValidPersonalSettingsNewPassword("0123456789"))
        assertEquals(false, isValidPersonalSettingsNewPassword("short"))
        assertEquals(false, isValidPersonalSettingsNewPassword("x".repeat(129)))
    }
}
