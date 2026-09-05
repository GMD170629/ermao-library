package com.ermao.library.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ermao.library.design.GeneratedDesignTokens

@Immutable
data class WarmPageColors(
    val canvas: Color,
    val surface: Color,
    val surfaceRaised: Color,
    val textPrimary: Color,
    val textSecondary: Color,
    val textTertiary: Color,
    val divider: Color,
    val brandAccent: Color,
    val actionAccent: Color,
    val accentSoft: Color,
    val onAction: Color,
)

@Immutable
data class WarmPageSpacing(
    val none: Dp,
    val half: Dp,
    val one: Dp,
    val oneAndHalf: Dp,
    val two: Dp,
    val three: Dp,
    val four: Dp,
    val five: Dp,
    val six: Dp,
    val eight: Dp,
)

@Immutable
data class WarmPageRadii(
    val control: Dp,
    val task: Dp,
    val coverCompact: Dp,
    val coverHero: Dp,
    val panel: Dp,
    val dialog: Dp,
    val pill: Dp,
)

internal val AppLightColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.App.Canvas),
    surface = colorOf(GeneratedDesignTokens.App.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.App.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.App.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.App.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.App.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.App.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.App.BrandAccent),
    actionAccent = colorOf(GeneratedDesignTokens.App.ActionAccent),
    accentSoft = colorOf(GeneratedDesignTokens.App.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.App.OnAction),
)

val ReaderPaperColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.Reader.Warm.Canvas),
    surface = colorOf(GeneratedDesignTokens.Reader.Warm.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.Reader.Warm.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.Reader.Warm.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.Reader.Warm.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.Reader.Warm.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.Reader.Warm.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.Reader.Warm.Accent),
    actionAccent = colorOf(GeneratedDesignTokens.Reader.Warm.Accent),
    accentSoft = colorOf(GeneratedDesignTokens.Reader.Warm.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.Reader.Warm.OnAccent),
)

val ReaderNightColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.Reader.Night.Canvas),
    surface = colorOf(GeneratedDesignTokens.Reader.Night.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.Reader.Night.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.Reader.Night.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.Reader.Night.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.Reader.Night.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.Reader.Night.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.Reader.Night.Accent),
    actionAccent = colorOf(GeneratedDesignTokens.Reader.Night.Accent),
    accentSoft = colorOf(GeneratedDesignTokens.Reader.Night.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.Reader.Night.OnAccent),
)

fun readerColors(theme: com.ermao.library.shared.modules.reader.ReaderTheme): WarmPageColors = when (theme) {
    com.ermao.library.shared.modules.reader.ReaderTheme.Warm -> ReaderPaperColors
    com.ermao.library.shared.modules.reader.ReaderTheme.Night -> ReaderNightColors
    com.ermao.library.shared.modules.reader.ReaderTheme.Day -> readerPalette(
        canvas = GeneratedDesignTokens.Reader.Day.Canvas,
        surface = GeneratedDesignTokens.Reader.Day.Surface,
        surfaceRaised = GeneratedDesignTokens.Reader.Day.SurfaceRaised,
        textPrimary = GeneratedDesignTokens.Reader.Day.TextPrimary,
        textSecondary = GeneratedDesignTokens.Reader.Day.TextSecondary,
        textTertiary = GeneratedDesignTokens.Reader.Day.TextTertiary,
        divider = GeneratedDesignTokens.Reader.Day.Divider,
        accent = GeneratedDesignTokens.Reader.Day.Accent,
        accentSoft = GeneratedDesignTokens.Reader.Day.AccentSoft,
        onAccent = GeneratedDesignTokens.Reader.Day.OnAccent,
    )
    com.ermao.library.shared.modules.reader.ReaderTheme.Green -> readerPalette(
        canvas = GeneratedDesignTokens.Reader.Green.Canvas,
        surface = GeneratedDesignTokens.Reader.Green.Surface,
        surfaceRaised = GeneratedDesignTokens.Reader.Green.SurfaceRaised,
        textPrimary = GeneratedDesignTokens.Reader.Green.TextPrimary,
        textSecondary = GeneratedDesignTokens.Reader.Green.TextSecondary,
        textTertiary = GeneratedDesignTokens.Reader.Green.TextTertiary,
        divider = GeneratedDesignTokens.Reader.Green.Divider,
        accent = GeneratedDesignTokens.Reader.Green.Accent,
        accentSoft = GeneratedDesignTokens.Reader.Green.AccentSoft,
        onAccent = GeneratedDesignTokens.Reader.Green.OnAccent,
    )
    com.ermao.library.shared.modules.reader.ReaderTheme.Black -> readerPalette(
        canvas = GeneratedDesignTokens.Reader.Black.Canvas,
        surface = GeneratedDesignTokens.Reader.Black.Surface,
        surfaceRaised = GeneratedDesignTokens.Reader.Black.SurfaceRaised,
        textPrimary = GeneratedDesignTokens.Reader.Black.TextPrimary,
        textSecondary = GeneratedDesignTokens.Reader.Black.TextSecondary,
        textTertiary = GeneratedDesignTokens.Reader.Black.TextTertiary,
        divider = GeneratedDesignTokens.Reader.Black.Divider,
        accent = GeneratedDesignTokens.Reader.Black.Accent,
        accentSoft = GeneratedDesignTokens.Reader.Black.AccentSoft,
        onAccent = GeneratedDesignTokens.Reader.Black.OnAccent,
    )
}

private fun readerPalette(
    canvas: String,
    surface: String,
    surfaceRaised: String,
    textPrimary: String,
    textSecondary: String,
    textTertiary: String,
    divider: String,
    accent: String,
    accentSoft: String,
    onAccent: String,
) = WarmPageColors(
    canvas = colorOf(canvas),
    surface = colorOf(surface),
    surfaceRaised = colorOf(surfaceRaised),
    textPrimary = colorOf(textPrimary),
    textSecondary = colorOf(textSecondary),
    textTertiary = colorOf(textTertiary),
    divider = colorOf(divider),
    brandAccent = colorOf(accent),
    actionAccent = colorOf(accent),
    accentSoft = colorOf(accentSoft),
    onAction = colorOf(onAccent),
)

val WarmPageSpacingTokens = WarmPageSpacing(
    none = GeneratedDesignTokens.Spacing.Space0.dp,
    half = GeneratedDesignTokens.Spacing.Space0_5.dp,
    one = GeneratedDesignTokens.Spacing.Space1.dp,
    oneAndHalf = GeneratedDesignTokens.Spacing.Space1_5.dp,
    two = GeneratedDesignTokens.Spacing.Space2.dp,
    three = GeneratedDesignTokens.Spacing.Space3.dp,
    four = GeneratedDesignTokens.Spacing.Space4.dp,
    five = GeneratedDesignTokens.Spacing.Space5.dp,
    six = GeneratedDesignTokens.Spacing.Space6.dp,
    eight = GeneratedDesignTokens.Spacing.Space8.dp,
)

val WarmPageRadiusTokens = WarmPageRadii(
    control = GeneratedDesignTokens.Radii.Control.dp,
    task = GeneratedDesignTokens.Radii.Task.dp,
    coverCompact = GeneratedDesignTokens.Radii.CoverCompact.dp,
    coverHero = GeneratedDesignTokens.Radii.CoverHero.dp,
    panel = GeneratedDesignTokens.Radii.Panel.dp,
    dialog = GeneratedDesignTokens.Radii.Dialog.dp,
    pill = GeneratedDesignTokens.Radii.Pill.dp,
)

internal val LocalWarmPageColors = staticCompositionLocalOf { AppLightColors }
internal val LocalWarmPageSpacing = staticCompositionLocalOf { WarmPageSpacingTokens }
internal val LocalWarmPageRadii = staticCompositionLocalOf { WarmPageRadiusTokens }

internal fun colorOf(hex: String): Color {
    require(hex.length == 7 && hex.first() == '#') { "Expected #RRGGBB design token" }
    return Color(0xFF000000 or hex.drop(1).toLong(16))
}
