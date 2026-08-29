package com.ermao.library.features.reader.infrastructure

import android.content.res.Configuration
import android.content.res.Resources
import androidx.core.graphics.toColorInt
import com.ermao.library.shared.modules.reader.ReaderFontFamily
import com.ermao.library.shared.modules.reader.ReaderPageMargin
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderTextAlignment
import com.ermao.library.shared.modules.reader.ReaderTheme
import com.ermao.library.shared.modules.reader.ReaderThemeMode
import org.readium.r2.navigator.epub.EpubPreferences
import org.readium.r2.navigator.preferences.Color
import org.readium.r2.navigator.preferences.ColumnCount
import org.readium.r2.navigator.preferences.FontFamily
import org.readium.r2.navigator.preferences.TextAlign
import org.readium.r2.navigator.preferences.Theme
import org.readium.r2.shared.ExperimentalReadiumApi

@OptIn(ExperimentalReadiumApi::class)
internal class ReadiumPreferencesMapper(private val resources: Resources) {
    fun toReadium(preferences: ReaderPreferences): EpubPreferences {
        val epub = preferences.epub
        val theme = effectiveTheme(preferences)
        val colors = theme.colors
        return EpubPreferences(
            backgroundColor = color(colors.background),
            columnCount = ColumnCount.ONE,
            fontFamily = fontFamily(epub.fontFamily),
            fontSize = epub.fontSize / READIUM_CSS_ROOT_FONT_SIZE,
            fontWeight = epub.fontWeight / NORMAL_FONT_WEIGHT,
            lineHeight = epub.lineHeight,
            letterSpacing = epub.letterSpacing.coerceAtLeast(0.0),
            pageMargins = when (epub.pageMargin) {
                ReaderPageMargin.Narrow -> 0.5
                ReaderPageMargin.Standard -> 1.0
                ReaderPageMargin.Wide -> 1.5
            },
            paragraphIndent = epub.typography.paragraphIndent,
            paragraphSpacing = epub.typography.paragraphSpacing,
            publisherStyles = epub.typography.preservePublisherStyles,
            scroll = epub.flow == ReaderReadingMode.ContinuousScroll,
            textAlign = when (epub.typography.textAlign) {
                ReaderTextAlignment.PublisherDefault -> null
                ReaderTextAlignment.Start -> TextAlign.START
                ReaderTextAlignment.Justify -> TextAlign.JUSTIFY
            },
            textColor = color(colors.foreground),
            theme = when (theme) {
                ReaderTheme.Warm -> Theme.SEPIA
                ReaderTheme.Night, ReaderTheme.Black -> Theme.DARK
                ReaderTheme.Day, ReaderTheme.Green -> Theme.LIGHT
            },
        )
    }

    fun effectiveTheme(preferences: ReaderPreferences): ReaderTheme =
        if (preferences.appearance.themeMode == ReaderThemeMode.System) {
            if (resources.configuration.isNightMode) ReaderTheme.Night else ReaderTheme.Day
        } else {
            preferences.appearance.theme
        }

    private fun fontFamily(value: ReaderFontFamily): FontFamily = FontFamily(
        when (value) {
            ReaderFontFamily.Pingfang, ReaderFontFamily.Heiti, ReaderFontFamily.Yahei -> "Shuku Sans"
            ReaderFontFamily.Songti -> "Shuku Songti"
            ReaderFontFamily.Kaiti -> "Shuku Kaiti"
        },
    )

    private fun color(value: String): Color = Color(value.toColorInt())

    private val ReaderTheme.colors: ThemeColors
        get() = when (this) {
            ReaderTheme.Day -> ThemeColors("#F7F7F4", "#1E293B")
            ReaderTheme.Warm -> ThemeColors("#FDF6EA", "#2B2118")
            ReaderTheme.Green -> ThemeColors("#E8F0E3", "#203126")
            ReaderTheme.Night -> ThemeColors("#0F172A", "#E2E8F0")
            ReaderTheme.Black -> ThemeColors("#000000", "#F8FAFC")
        }

    private data class ThemeColors(val background: String, val foreground: String)

    companion object {
        private const val READIUM_CSS_ROOT_FONT_SIZE = 16.0
        private const val NORMAL_FONT_WEIGHT = 400.0
    }
}

private val Configuration.isNightMode: Boolean
    get() = uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
