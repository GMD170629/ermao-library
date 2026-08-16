package com.ermao.library.ui.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

class WarmPageTokensTest {
    @Test
    fun appPalettesUseTheFrozenWarmPageValues() {
        assertEquals(Color(0xFFFBFAF8), AppLightColors.canvas)
        assertEquals(Color(0xFF17191D), AppLightColors.textPrimary)
        assertEquals(Color(0xFFFF4F2A), AppLightColors.brandAccent)
        assertEquals(Color(0xFFC83B23), AppLightColors.actionAccent)

        assertEquals(Color(0xFF151311), AppDarkColors.canvas)
        assertEquals(Color(0xFFF3ECE4), AppDarkColors.textPrimary)
        assertEquals(Color(0xFFFF6B48), AppDarkColors.brandAccent)
        assertEquals(Color(0xFFFF7A58), AppDarkColors.actionAccent)
    }

    @Test
    fun readerPalettesRemainIndependentFromAppAppearance() {
        assertEquals(Color(0xFFFDF6EA), ReaderPaperColors.canvas)
        assertEquals(Color(0xFF2B2118), ReaderPaperColors.textPrimary)
        assertEquals(Color(0xFF151311), ReaderNightColors.canvas)
        assertEquals(Color(0xFFEFE7DD), ReaderNightColors.textPrimary)
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
        assertEquals(AppDarkColors.actionAccent, AppLightColorScheme.inversePrimary)

        assertEquals(AppDarkColors.actionAccent, AppDarkColorScheme.primary)
        assertEquals(AppDarkColors.brandAccent, AppDarkColorScheme.secondary)
        assertEquals(AppDarkColors.brandAccent, AppDarkColorScheme.tertiary)
        assertEquals(AppDarkColors.canvas, AppDarkColorScheme.background)
        assertEquals(AppDarkColors.surface, AppDarkColorScheme.surface)
        assertEquals(AppDarkColors.surface, AppDarkColorScheme.surfaceContainer)
        assertEquals(AppDarkColors.surfaceRaised, AppDarkColorScheme.surfaceContainerHighest)
        assertEquals(AppDarkColors.divider, AppDarkColorScheme.outlineVariant)
        assertEquals(AppLightColors.actionAccent, AppDarkColorScheme.inversePrimary)
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
