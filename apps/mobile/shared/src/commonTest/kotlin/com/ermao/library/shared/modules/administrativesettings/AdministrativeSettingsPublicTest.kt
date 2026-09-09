package com.ermao.library.shared.modules.administrativesettings

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

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
    fun opdsDraftUsesTheConnectedServerOnlyWhenNoPublicAddressWasConfigured() {
        val context = createAdministrativeSettingsContext("p", "Books", "https://books.example/library/", "s", false)
        val unconfigured = OpdsSettings(false, false, null, null)
        assertEquals("https://books.example/library", initialOpdsPublicBaseUrl(unconfigured, context))
        assertEquals("https://books.example/library", initialOpdsPublicBaseUrl(unconfigured.copy(publicBaseUrl = " "), context))
        val configured = unconfigured.copy(publicBaseUrl = "https://public.example/reader")
        assertEquals("https://public.example/reader", initialOpdsPublicBaseUrl(configured, context))
        assertEquals(null, unconfigured.catalogUrl)
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

    @Test
    fun publicValidationMatchesAdministrativeWriteContracts() {
        assertTrue(isValidAdministrativeDisplayName("Reader"))
        assertFalse(isValidAdministrativeDisplayName(""))
        assertTrue(isValidAdministrativeEmail("reader@example.com"))
        assertFalse(isValidAdministrativeEmail("reader@example"))
        assertTrue(isValidOptionalAdministrativeEmail(""))
        assertTrue(isValidAdministrativePassword("0123456789"))
        assertFalse(isValidAdministrativePassword("short"))
        assertTrue(isValidAdministrativeSmtpHost("smtp.example.com"))
        assertTrue(isValidAdministrativeSmtpPort(65_535))
        assertFalse(isValidAdministrativeSmtpPort(65_536))
        assertTrue(isValidAdministrativeAttachmentMegabytes(1_000.0))
        assertFalse(isValidAdministrativeAttachmentMegabytes(Double.NaN))
        assertTrue(isValidAdministrativeLogMegabytes(100))
        assertFalse(isValidAdministrativeLogMegabytes(101))
        assertEquals(10, administrativeMinimumPasswordLength())
        assertEquals(128, administrativeMaximumPasswordLength())
        assertEquals(1, administrativeMinimumLogMegabytes())
        assertEquals(100, administrativeMaximumLogMegabytes())
    }
}
