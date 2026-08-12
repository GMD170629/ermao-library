package com.ermao.library.features.reader.infrastructure

import android.content.res.Configuration
import android.content.res.Resources
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderTextAlignment
import com.ermao.library.shared.modules.reader.ReaderTheme
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.navigator.epub.EpubPreferences
import org.readium.r2.navigator.preferences.FontFamily
import org.readium.r2.navigator.preferences.TextAlign
import org.readium.r2.navigator.preferences.Theme

@OptIn(ExperimentalReadiumApi::class)
internal class ReadiumPreferencesMapper(private val resources: Resources) {
    fun toReadium(preferences: ReaderPreferences): EpubPreferences = EpubPreferences(
        fontFamily = preferences.fontFamily?.let(::fontFamily),
        fontSize = preferences.fontSize,
        lineHeight = preferences.lineHeight,
        letterSpacing = preferences.letterSpacing,
        pageMargins = preferences.pageMargins,
        publisherStyles = preferences.publisherStyles,
        scroll = preferences.readingMode == ReaderReadingMode.ContinuousScroll,
        textAlign = when (preferences.textAlignment) {
            ReaderTextAlignment.PublisherDefault -> null
            ReaderTextAlignment.Start -> TextAlign.START
            ReaderTextAlignment.Justify -> TextAlign.JUSTIFY
        },
        theme = when (preferences.theme) {
            ReaderTheme.Paper -> Theme.SEPIA
            ReaderTheme.Night -> Theme.DARK
            ReaderTheme.System -> if (resources.configuration.isNightMode) Theme.DARK else Theme.LIGHT
        },
    )

    private fun fontFamily(value: String): FontFamily = when (value.lowercase()) {
        "serif" -> FontFamily.SERIF
        "sans-serif", "sans_serif" -> FontFamily.SANS_SERIF
        "monospace" -> FontFamily.MONOSPACE
        else -> FontFamily(value)
    }
}

private val Configuration.isNightMode: Boolean
    get() = uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
