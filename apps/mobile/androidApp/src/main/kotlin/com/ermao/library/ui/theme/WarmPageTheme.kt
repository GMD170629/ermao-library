package com.ermao.library.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import com.ermao.library.shared.modules.reader.ReaderTheme

private val AppLightColorScheme = lightColorScheme(
    primary = AppLightColors.actionAccent,
    onPrimary = AppLightColors.onAction,
    primaryContainer = AppLightColors.accentSoft,
    onPrimaryContainer = AppLightColors.textPrimary,
    secondary = AppLightColors.brandAccent,
    onSecondary = AppLightColors.surface,
    background = AppLightColors.canvas,
    onBackground = AppLightColors.textPrimary,
    surface = AppLightColors.surface,
    onSurface = AppLightColors.textPrimary,
    surfaceVariant = AppLightColors.accentSoft,
    onSurfaceVariant = AppLightColors.textSecondary,
    outline = AppLightColors.divider,
)

private val AppDarkColorScheme = darkColorScheme(
    primary = AppDarkColors.actionAccent,
    onPrimary = AppDarkColors.onAction,
    primaryContainer = AppDarkColors.accentSoft,
    onPrimaryContainer = AppDarkColors.textPrimary,
    secondary = AppDarkColors.brandAccent,
    onSecondary = AppDarkColors.surface,
    background = AppDarkColors.canvas,
    onBackground = AppDarkColors.textPrimary,
    surface = AppDarkColors.surface,
    onSurface = AppDarkColors.textPrimary,
    surfaceVariant = AppDarkColors.accentSoft,
    onSurfaceVariant = AppDarkColors.textSecondary,
    outline = AppDarkColors.divider,
)

@Composable
fun WarmPageTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) AppDarkColors else AppLightColors
    val materialColors = if (darkTheme) AppDarkColorScheme else AppLightColorScheme

    CompositionLocalProvider(
        LocalWarmPageColors provides colors,
        LocalWarmPageSpacing provides WarmPageSpacingTokens,
        LocalWarmPageRadii provides WarmPageRadiusTokens,
        LocalWarmPageTypography provides WarmPageTypographyTokens,
    ) {
        MaterialTheme(
            colorScheme = materialColors,
            typography = androidx.compose.material3.Typography(
                displayLarge = WarmPageTypographyTokens.display,
                headlineLarge = WarmPageTypographyTokens.title,
                titleLarge = WarmPageTypographyTokens.sectionTitle,
                titleMedium = WarmPageTypographyTokens.headline,
                bodyLarge = WarmPageTypographyTokens.body,
                bodyMedium = WarmPageTypographyTokens.callout,
                labelLarge = WarmPageTypographyTokens.button,
                labelMedium = WarmPageTypographyTokens.label,
                labelSmall = WarmPageTypographyTokens.caption,
            ),
            content = content,
        )
    }
}

@Composable
fun ReaderWarmPageTheme(
    readerTheme: ReaderTheme,
    content: @Composable () -> Unit,
) {
    val systemDark = isSystemInDarkTheme()
    val usesNightPalette = readerTheme == ReaderTheme.Night || readerTheme == ReaderTheme.System && systemDark
    val colors = if (usesNightPalette) ReaderNightColors else ReaderPaperColors
    val materialColors = if (usesNightPalette) {
        darkColorScheme(
            primary = colors.actionAccent,
            onPrimary = colors.onAction,
            background = colors.canvas,
            onBackground = colors.textPrimary,
            surface = colors.surface,
            onSurface = colors.textPrimary,
            surfaceVariant = colors.accentSoft,
            onSurfaceVariant = colors.textSecondary,
            outline = colors.divider,
        )
    } else {
        lightColorScheme(
            primary = colors.actionAccent,
            onPrimary = colors.onAction,
            background = colors.canvas,
            onBackground = colors.textPrimary,
            surface = colors.surface,
            onSurface = colors.textPrimary,
            surfaceVariant = colors.accentSoft,
            onSurfaceVariant = colors.textSecondary,
            outline = colors.divider,
        )
    }

    CompositionLocalProvider(
        LocalWarmPageColors provides colors,
        LocalWarmPageSpacing provides WarmPageSpacingTokens,
        LocalWarmPageRadii provides WarmPageRadiusTokens,
        LocalWarmPageTypography provides WarmPageTypographyTokens,
    ) {
        MaterialTheme(
            colorScheme = materialColors,
            typography = androidx.compose.material3.Typography(
                displayLarge = WarmPageTypographyTokens.display,
                headlineLarge = WarmPageTypographyTokens.title,
                titleLarge = WarmPageTypographyTokens.sectionTitle,
                titleMedium = WarmPageTypographyTokens.headline,
                bodyLarge = WarmPageTypographyTokens.body,
                bodyMedium = WarmPageTypographyTokens.callout,
                labelLarge = WarmPageTypographyTokens.button,
                labelMedium = WarmPageTypographyTokens.label,
                labelSmall = WarmPageTypographyTokens.caption,
            ),
            content = content,
        )
    }
}

object WarmPageThemeValues {
    val colors: WarmPageColors
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageColors.current

    val spacing: WarmPageSpacing
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageSpacing.current

    val radii: WarmPageRadii
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageRadii.current

    val typography: WarmPageTypography
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageTypography.current
}
