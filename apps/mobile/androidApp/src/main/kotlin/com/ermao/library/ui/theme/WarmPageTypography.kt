package com.ermao.library.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.ermao.library.design.GeneratedDesignTokens

@Immutable
data class WarmPageTypography(
    val display: TextStyle,
    val title: TextStyle,
    val sectionTitle: TextStyle,
    val headline: TextStyle,
    val body: TextStyle,
    val callout: TextStyle,
    val label: TextStyle,
    val caption: TextStyle,
    val button: TextStyle,
    val readerChapter: TextStyle,
    val readerBody: TextStyle,
    val readerAuxiliary: TextStyle,
)

private val SystemSans = FontFamily.SansSerif
private val ReaderSerif = FontFamily.Serif

val WarmPageTypographyTokens = WarmPageTypography(
    display = tokenTextStyle(
        GeneratedDesignTokens.Display.Size,
        GeneratedDesignTokens.Display.LineHeight,
        GeneratedDesignTokens.Display.Weight,
        GeneratedDesignTokens.Display.FamilyRole,
    ),
    title = tokenTextStyle(
        GeneratedDesignTokens.Title.Size,
        GeneratedDesignTokens.Title.LineHeight,
        GeneratedDesignTokens.Title.Weight,
        GeneratedDesignTokens.Title.FamilyRole,
    ),
    sectionTitle = tokenTextStyle(
        GeneratedDesignTokens.SectionTitle.Size,
        GeneratedDesignTokens.SectionTitle.LineHeight,
        GeneratedDesignTokens.SectionTitle.Weight,
        GeneratedDesignTokens.SectionTitle.FamilyRole,
    ),
    headline = tokenTextStyle(
        GeneratedDesignTokens.Headline.Size,
        GeneratedDesignTokens.Headline.LineHeight,
        GeneratedDesignTokens.Headline.Weight,
        GeneratedDesignTokens.Headline.FamilyRole,
    ),
    body = tokenTextStyle(
        GeneratedDesignTokens.Body.Size,
        GeneratedDesignTokens.Body.LineHeight,
        GeneratedDesignTokens.Body.Weight,
        GeneratedDesignTokens.Body.FamilyRole,
    ),
    callout = tokenTextStyle(
        GeneratedDesignTokens.Callout.Size,
        GeneratedDesignTokens.Callout.LineHeight,
        GeneratedDesignTokens.Callout.Weight,
        GeneratedDesignTokens.Callout.FamilyRole,
    ),
    label = tokenTextStyle(
        GeneratedDesignTokens.Label.Size,
        GeneratedDesignTokens.Label.LineHeight,
        GeneratedDesignTokens.Label.Weight,
        GeneratedDesignTokens.Label.FamilyRole,
    ),
    caption = tokenTextStyle(
        GeneratedDesignTokens.Caption.Size,
        GeneratedDesignTokens.Caption.LineHeight,
        GeneratedDesignTokens.Caption.Weight,
        GeneratedDesignTokens.Caption.FamilyRole,
    ),
    button = tokenTextStyle(
        GeneratedDesignTokens.Button.Size,
        GeneratedDesignTokens.Button.LineHeight,
        GeneratedDesignTokens.Button.Weight,
        GeneratedDesignTokens.Button.FamilyRole,
    ),
    readerChapter = tokenTextStyle(
        GeneratedDesignTokens.ReaderChapter.Size,
        GeneratedDesignTokens.ReaderChapter.LineHeight,
        GeneratedDesignTokens.ReaderChapter.Weight,
        GeneratedDesignTokens.ReaderChapter.FamilyRole,
    ),
    readerBody = tokenTextStyle(
        GeneratedDesignTokens.ReaderBody.Size,
        GeneratedDesignTokens.ReaderBody.LineHeight,
        GeneratedDesignTokens.ReaderBody.Weight,
        GeneratedDesignTokens.ReaderBody.FamilyRole,
    ),
    readerAuxiliary = tokenTextStyle(
        GeneratedDesignTokens.ReaderAuxiliary.Size,
        GeneratedDesignTokens.ReaderAuxiliary.LineHeight,
        GeneratedDesignTokens.ReaderAuxiliary.Weight,
        GeneratedDesignTokens.ReaderAuxiliary.FamilyRole,
    ),
)

private fun tokenTextStyle(
    size: Double,
    lineHeight: Double,
    weight: Double,
    familyRole: String,
): TextStyle = TextStyle(
    fontFamily = when (familyRole) {
        "systemSans" -> SystemSans
        "readerSerif" -> ReaderSerif
        else -> error("Unsupported generated typography family role: $familyRole")
    },
    fontWeight = FontWeight(weight.toInt()),
    fontSize = size.sp,
    lineHeight = lineHeight.sp,
)

internal val LocalWarmPageTypography = staticCompositionLocalOf { WarmPageTypographyTokens }
