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
)

internal val AppLightColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.AppLight.Canvas),
    surface = colorOf(GeneratedDesignTokens.AppLight.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.AppLight.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.AppLight.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.AppLight.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.AppLight.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.AppLight.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.AppLight.BrandAccent),
    actionAccent = colorOf(GeneratedDesignTokens.AppLight.ActionAccent),
    accentSoft = colorOf(GeneratedDesignTokens.AppLight.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.AppLight.OnAction),
)

internal val AppDarkColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.AppDark.Canvas),
    surface = colorOf(GeneratedDesignTokens.AppDark.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.AppDark.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.AppDark.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.AppDark.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.AppDark.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.AppDark.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.AppDark.BrandAccent),
    actionAccent = colorOf(GeneratedDesignTokens.AppDark.ActionAccent),
    accentSoft = colorOf(GeneratedDesignTokens.AppDark.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.AppDark.OnAction),
)

val ReaderPaperColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.ReaderPaper.Canvas),
    surface = colorOf(GeneratedDesignTokens.ReaderPaper.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.ReaderPaper.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.ReaderPaper.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.ReaderPaper.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.ReaderPaper.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.ReaderPaper.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.ReaderPaper.BrandAccent),
    actionAccent = colorOf(GeneratedDesignTokens.ReaderPaper.ActionAccent),
    accentSoft = colorOf(GeneratedDesignTokens.ReaderPaper.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.ReaderPaper.OnAction),
)

val ReaderNightColors = WarmPageColors(
    canvas = colorOf(GeneratedDesignTokens.ReaderNight.Canvas),
    surface = colorOf(GeneratedDesignTokens.ReaderNight.Surface),
    surfaceRaised = colorOf(GeneratedDesignTokens.ReaderNight.SurfaceRaised),
    textPrimary = colorOf(GeneratedDesignTokens.ReaderNight.TextPrimary),
    textSecondary = colorOf(GeneratedDesignTokens.ReaderNight.TextSecondary),
    textTertiary = colorOf(GeneratedDesignTokens.ReaderNight.TextTertiary),
    divider = colorOf(GeneratedDesignTokens.ReaderNight.Divider),
    brandAccent = colorOf(GeneratedDesignTokens.ReaderNight.BrandAccent),
    actionAccent = colorOf(GeneratedDesignTokens.ReaderNight.ActionAccent),
    accentSoft = colorOf(GeneratedDesignTokens.ReaderNight.AccentSoft),
    onAction = colorOf(GeneratedDesignTokens.ReaderNight.OnAction),
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
)

internal val LocalWarmPageColors = staticCompositionLocalOf { AppLightColors }
internal val LocalWarmPageSpacing = staticCompositionLocalOf { WarmPageSpacingTokens }
internal val LocalWarmPageRadii = staticCompositionLocalOf { WarmPageRadiusTokens }

internal fun colorOf(hex: String): Color {
    require(hex.length == 7 && hex.first() == '#') { "Expected #RRGGBB design token" }
    return Color(0xFF000000 or hex.drop(1).toLong(16))
}
