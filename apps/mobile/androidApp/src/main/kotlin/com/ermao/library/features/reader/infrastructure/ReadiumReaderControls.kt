package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderControl
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.epub.EpubPreferencesEditor
import org.readium.r2.navigator.epub.css.FontWeight
import org.readium.r2.navigator.preferences.FontFamily
import org.readium.r2.shared.ExperimentalReadiumApi

/** Only these licensed, bundled assets are exposed to the publication's local server. */
@OptIn(ExperimentalReadiumApi::class)
internal fun readerNavigatorConfiguration(): EpubNavigatorFragment.Configuration =
    EpubNavigatorFragment.Configuration(
        servedAssets = listOf("fonts/reader/.*"),
        // Continuous-scroll readers must keep touch page turns enabled. The
        // application handles tap-zone viewport advances through the same
        // navigator session instead of asking Readium's paginated JS to turn.
        disablePageTurnsWhileScrolling = false,
    ).apply {
        listOf("Shuku Sans" to "sans", "Shuku Songti" to "songti", "Shuku Kaiti" to "kaiti")
            .forEach { (family, asset) ->
                addFontFamilyDeclaration(FontFamily(family)) {
                    addFontFace {
                        addSource("fonts/reader/$asset.woff2")
                        setFontWeight(FontWeight.NORMAL)
                    }
                }
            }
    }

/** Query Readium's publication/language/layout rules, not the original filename. */
@OptIn(ExperimentalReadiumApi::class)
internal fun EpubPreferencesEditor.unavailableReaderControls(): Set<ReaderControl> = buildSet {
    fun check(control: ReaderControl, effective: Boolean) { if (!effective) add(control) }
    check(ReaderControl.FontFamily, fontFamily.isEffective)
    check(ReaderControl.FontSize, fontSize.isEffective)
    check(ReaderControl.FontWeight, fontWeight.isEffective)
    check(ReaderControl.LineHeight, lineHeight.isEffective)
    check(ReaderControl.LetterSpacing, letterSpacing.isEffective)
    check(ReaderControl.PageMargins, pageMargins.isEffective)
    check(ReaderControl.ParagraphIndent, paragraphIndent.isEffective)
    check(ReaderControl.ParagraphSpacing, paragraphSpacing.isEffective)
    check(ReaderControl.TextAlignment, textAlign.isEffective)
    check(ReaderControl.ReadingMode, scroll.isEffective)
    check(ReaderControl.Spread, columnCount.isEffective)
    check(ReaderControl.PublisherStyles, publisherStyles.isEffective)
}
