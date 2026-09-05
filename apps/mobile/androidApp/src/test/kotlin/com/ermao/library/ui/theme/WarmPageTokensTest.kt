package com.ermao.library.ui.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

class WarmPageTokensTest {
    @Test
    fun appPaletteUsesTheFrozenLightOnlyValues() {
        assertEquals(Color(0xFFFBFAF8), AppLightColors.canvas)
        assertEquals(Color(0xFF17191D), AppLightColors.textPrimary)
        assertEquals(Color(0xFFFF4F2A), AppLightColors.brandAccent)
        assertEquals(Color(0xFFC83B23), AppLightColors.actionAccent)
    }

    @Test
    fun readerPalettesRemainIndependentFromAppAppearance() {
        assertEquals(Color(0xFFFDF6EA), ReaderPaperColors.canvas)
        assertEquals(Color(0xFF2B2118), ReaderPaperColors.textPrimary)
        assertEquals(Color(0xFF0F172A), ReaderNightColors.canvas)
        assertEquals(Color(0xFFE2E8F0), ReaderNightColors.textPrimary)
    }

    @Test
    fun materialSchemesExplicitlyMapWarmPageSurfaceAndInteractionRoles() {
        assertEquals(AppLightColors.actionAccent, AppLightColorScheme.primary)
        assertEquals(AppLightColors.brandAccent, AppLightColorScheme.secondary)
        assertEquals(AppLightColors.brandAccent, AppLightColorScheme.tertiary)
        assertEquals(AppLightColors.canvas, AppLightColorScheme.background)
        assertEquals(AppLightColors.surface, AppLightColorScheme.surface)
        assertEquals(AppLightColors.surface, AppLightColorScheme.surfaceContainer)
        assertEquals(AppLightColors.surfaceRaised, AppLightColorScheme.surfaceContainerHighest)
        assertEquals(AppLightColors.divider, AppLightColorScheme.outlineVariant)
        assertEquals(AppLightColors.brandAccent, AppLightColorScheme.inversePrimary)
    }

    @Test
    fun everyMaterialTypographySlotUsesAnIntentionalWarmPageRole() {
        assertEquals(WarmPageTypographyTokens.display, AppMaterialTypography.displayLarge)
        assertEquals(WarmPageTypographyTokens.display, AppMaterialTypography.displayMedium)
        assertEquals(WarmPageTypographyTokens.title, AppMaterialTypography.displaySmall)
        assertEquals(WarmPageTypographyTokens.title, AppMaterialTypography.headlineLarge)
        assertEquals(WarmPageTypographyTokens.sectionTitle, AppMaterialTypography.headlineMedium)
        assertEquals(WarmPageTypographyTokens.headline, AppMaterialTypography.headlineSmall)
        assertEquals(WarmPageTypographyTokens.sectionTitle, AppMaterialTypography.titleLarge)
        assertEquals(WarmPageTypographyTokens.headline, AppMaterialTypography.titleMedium)
        assertEquals(WarmPageTypographyTokens.label, AppMaterialTypography.titleSmall)
        assertEquals(WarmPageTypographyTokens.body, AppMaterialTypography.bodyLarge)
        assertEquals(WarmPageTypographyTokens.callout, AppMaterialTypography.bodyMedium)
        assertEquals(WarmPageTypographyTokens.caption, AppMaterialTypography.bodySmall)
        assertEquals(WarmPageTypographyTokens.button, AppMaterialTypography.labelLarge)
        assertEquals(WarmPageTypographyTokens.label, AppMaterialTypography.labelMedium)
        assertEquals(WarmPageTypographyTokens.caption, AppMaterialTypography.labelSmall)
    }
}
