package com.ermao.library.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import com.ermao.library.design.GeneratedDesignTokens
import com.ermao.library.shared.modules.reader.ReaderTheme
import com.ermao.library.shared.modules.reader.ReaderThemeMode

private val LightError = colorOf(GeneratedDesignTokens.App.Danger)
private val LightOnError = colorOf(GeneratedDesignTokens.App.OnDanger)
private val LightErrorContainer = colorOf(GeneratedDesignTokens.App.DangerContainer)
private val LightOnErrorContainer = colorOf(GeneratedDesignTokens.App.OnDangerContainer)
private val DarkError = colorOf("#FFB4AB")
private val DarkOnError = colorOf("#690005")
private val DarkErrorContainer = colorOf("#93000A")
private val DarkOnErrorContainer = colorOf("#FFDAD6")

internal val AppLightColorScheme = lightColorScheme(
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
    outlineVariant = AppLightColors.divider,
    inversePrimary = AppLightColors.brandAccent,
    secondaryContainer = AppLightColors.accentSoft,
    onSecondaryContainer = AppLightColors.textPrimary,
    tertiary = AppLightColors.brandAccent,
    onTertiary = AppLightColors.surface,
    tertiaryContainer = AppLightColors.accentSoft,
    onTertiaryContainer = AppLightColors.textPrimary,
    surfaceTint = AppLightColors.actionAccent,
    inverseSurface = AppLightColors.textPrimary,
    inverseOnSurface = AppLightColors.canvas,
    error = LightError,
    onError = LightOnError,
    errorContainer = LightErrorContainer,
    onErrorContainer = LightOnErrorContainer,
    scrim = AppLightColors.textPrimary,
    surfaceBright = AppLightColors.surfaceRaised,
    surfaceDim = AppLightColors.canvas,
    surfaceContainerLowest = AppLightColors.surfaceRaised,
    surfaceContainerLow = AppLightColors.canvas,
    surfaceContainer = AppLightColors.surface,
    surfaceContainerHigh = AppLightColors.surface,
    surfaceContainerHighest = AppLightColors.surfaceRaised,
)

internal val AppMaterialTypography = Typography(
    displayLarge = WarmPageTypographyTokens.display,
    displayMedium = WarmPageTypographyTokens.display,
    displaySmall = WarmPageTypographyTokens.title,
    headlineLarge = WarmPageTypographyTokens.title,
    headlineMedium = WarmPageTypographyTokens.sectionTitle,
    headlineSmall = WarmPageTypographyTokens.headline,
    titleLarge = WarmPageTypographyTokens.sectionTitle,
    titleMedium = WarmPageTypographyTokens.headline,
    titleSmall = WarmPageTypographyTokens.label,
    bodyLarge = WarmPageTypographyTokens.body,
    bodyMedium = WarmPageTypographyTokens.callout,
    bodySmall = WarmPageTypographyTokens.caption,
    labelLarge = WarmPageTypographyTokens.button,
    labelMedium = WarmPageTypographyTokens.label,
    labelSmall = WarmPageTypographyTokens.caption,
)

@Composable
fun WarmPageTheme(
    content: @Composable () -> Unit,
) {
    CompositionLocalProvider(
        LocalWarmPageColors provides AppLightColors,
        LocalWarmPageSpacing provides WarmPageSpacingTokens,
        LocalWarmPageRadii provides WarmPageRadiusTokens,
        LocalWarmPageMetrics provides WarmPageMetricTokens,
        LocalWarmPageComponentMetrics provides WarmPageComponentMetricTokens,
        LocalWarmPageTypography provides WarmPageTypographyTokens,
    ) {
        MaterialTheme(
            colorScheme = AppLightColorScheme,
            typography = AppMaterialTypography,
            content = content,
        )
    }
}

@Composable
fun WarmPageTheme(
    // Temporary source-compatible adapter for fixtures and tests; the app palette remains light-only.
    @Suppress("UNUSED_PARAMETER") darkTheme: Boolean,
    content: @Composable () -> Unit,
) = WarmPageTheme(content)

@Composable
fun ReaderWarmPageTheme(
    readerTheme: ReaderTheme,
    themeMode: ReaderThemeMode = ReaderThemeMode.Manual,
    content: @Composable () -> Unit,
) {
    val systemDark = isSystemInDarkTheme()
    val effectiveTheme = if (themeMode == ReaderThemeMode.System) {
        if (systemDark) ReaderTheme.Night else ReaderTheme.Day
    } else {
        readerTheme
    }
    val usesNightPalette = effectiveTheme == ReaderTheme.Night || effectiveTheme == ReaderTheme.Black
    val colors = readerColors(effectiveTheme)
    val materialColors = readerMaterialColorScheme(colors, usesNightPalette)

    CompositionLocalProvider(
        LocalWarmPageColors provides colors,
        LocalWarmPageSpacing provides WarmPageSpacingTokens,
        LocalWarmPageRadii provides WarmPageRadiusTokens,
        LocalWarmPageMetrics provides WarmPageMetricTokens,
        LocalWarmPageComponentMetrics provides WarmPageComponentMetricTokens,
        LocalWarmPageTypography provides WarmPageTypographyTokens,
    ) {
        MaterialTheme(
            colorScheme = materialColors,
            typography = AppMaterialTypography,
            content = content,
        )
    }
}

private fun readerMaterialColorScheme(colors: WarmPageColors, dark: Boolean): ColorScheme {
    val inverseColors = if (dark) readerColors(ReaderTheme.Day) else readerColors(ReaderTheme.Night)
    val error = if (dark) DarkError else LightError
    val onError = if (dark) DarkOnError else LightOnError
    val errorContainer = if (dark) DarkErrorContainer else LightErrorContainer
    val onErrorContainer = if (dark) DarkOnErrorContainer else LightOnErrorContainer
    return if (dark) {
        darkColorScheme(
            primary = colors.actionAccent,
            onPrimary = colors.onAction,
            primaryContainer = colors.accentSoft,
            onPrimaryContainer = colors.textPrimary,
            inversePrimary = inverseColors.actionAccent,
            secondary = colors.brandAccent,
            onSecondary = colors.surface,
            secondaryContainer = colors.accentSoft,
            onSecondaryContainer = colors.textPrimary,
            tertiary = colors.brandAccent,
            onTertiary = colors.surface,
            tertiaryContainer = colors.accentSoft,
            onTertiaryContainer = colors.textPrimary,
            background = colors.canvas,
            onBackground = colors.textPrimary,
            surface = colors.surface,
            onSurface = colors.textPrimary,
            surfaceVariant = colors.accentSoft,
            onSurfaceVariant = colors.textSecondary,
            surfaceTint = colors.actionAccent,
            inverseSurface = inverseColors.surface,
            inverseOnSurface = inverseColors.textPrimary,
            error = error,
            onError = onError,
            errorContainer = errorContainer,
            onErrorContainer = onErrorContainer,
            outline = colors.divider,
            outlineVariant = colors.divider,
            scrim = inverseColors.canvas,
            surfaceBright = colors.surfaceRaised,
            surfaceDim = colors.canvas,
            surfaceContainer = colors.surface,
            surfaceContainerHigh = colors.surfaceRaised,
            surfaceContainerHighest = colors.surfaceRaised,
            surfaceContainerLow = colors.surface,
            surfaceContainerLowest = colors.canvas,
        )
    } else {
        lightColorScheme(
            primary = colors.actionAccent,
            onPrimary = colors.onAction,
            primaryContainer = colors.accentSoft,
            onPrimaryContainer = colors.textPrimary,
            inversePrimary = inverseColors.actionAccent,
            secondary = colors.brandAccent,
            onSecondary = colors.surface,
            secondaryContainer = colors.accentSoft,
            onSecondaryContainer = colors.textPrimary,
            tertiary = colors.brandAccent,
            onTertiary = colors.surface,
            tertiaryContainer = colors.accentSoft,
            onTertiaryContainer = colors.textPrimary,
            background = colors.canvas,
            onBackground = colors.textPrimary,
            surface = colors.surface,
            onSurface = colors.textPrimary,
            surfaceVariant = colors.accentSoft,
            onSurfaceVariant = colors.textSecondary,
            surfaceTint = colors.actionAccent,
            inverseSurface = inverseColors.surface,
            inverseOnSurface = inverseColors.textPrimary,
            error = error,
            onError = onError,
            errorContainer = errorContainer,
            onErrorContainer = onErrorContainer,
            outline = colors.divider,
            outlineVariant = colors.divider,
            scrim = inverseColors.canvas,
            surfaceBright = colors.surfaceRaised,
            surfaceDim = colors.canvas,
            surfaceContainer = colors.surface,
            surfaceContainerHigh = colors.surface,
            surfaceContainerHighest = colors.surfaceRaised,
            surfaceContainerLow = colors.canvas,
            surfaceContainerLowest = colors.surfaceRaised,
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

    val metrics: WarmPageMetrics
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageMetrics.current

    val components: WarmPageComponentMetrics
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageComponentMetrics.current

    val typography: WarmPageTypography
        @Composable
        @ReadOnlyComposable
        get() = LocalWarmPageTypography.current
}
