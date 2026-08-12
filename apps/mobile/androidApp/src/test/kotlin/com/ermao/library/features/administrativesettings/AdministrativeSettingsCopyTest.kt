package com.ermao.library.features.administrativesettings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AdministrativeSettingsCopyTest {
    @Test
    fun everyCopyKeyHasNonBlankChineseAndEnglishText() {
        AdministrativeCopy.entries.forEach { key ->
            assertTrue("Missing zh-CN for $key", key.hasText(AdministrativeLocale.ZhCn))
            assertTrue("Missing en-US for $key", key.hasText(AdministrativeLocale.EnUs))
        }
    }

    @Test
    fun localeCatalogsHaveExactKeyParity() {
        val chineseKeys = AdministrativeCopy.entries.filter { it.hasText(AdministrativeLocale.ZhCn) }.toSet()
        val englishKeys = AdministrativeCopy.entries.filter { it.hasText(AdministrativeLocale.EnUs) }.toSet()

        assertEquals(chineseKeys, englishKeys)
        assertEquals(AdministrativeCopy.entries.toSet(), chineseKeys)
    }
}
