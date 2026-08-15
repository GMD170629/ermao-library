package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ReaderPreferencesTest {
    @Test
    fun defaultsMatchWebReaderV3() {
        val preferences = ReaderPreferences()

        assertEquals(4, preferences.schemaVersion)
        assertEquals(ReaderTheme.Warm, preferences.appearance.theme)
        assertEquals(ReaderThemeMode.Manual, preferences.appearance.themeMode)
        assertEquals(18, preferences.epub.fontSize)
        assertEquals(1.9, preferences.epub.lineHeight)
        assertEquals(ReaderFontFamily.Pingfang, preferences.epub.fontFamily)
        assertEquals(ReaderSpreadMode.Single, preferences.epub.spreadMode)
        assertEquals(ReaderReadingMode.Paged, preferences.epub.flow)
        assertEquals(ReaderComicDirection.LeftToRight, preferences.comic.direction)
        assertEquals(ReaderReadingMode.Paged, preferences.comic.flow)
        assertEquals(ReaderComicSpreadMode.Single, preferences.comic.spreadMode)
        assertEquals(ReaderComicImageVariant.Original, preferences.comic.imageVariant)
        assertEquals(1.0, preferences.pdf.zoom)
        assertEquals(ReaderPdfFit.Page, preferences.pdf.fit)
        assertEquals(ReaderPdfFlow.Paged, preferences.pdf.flow)
        assertEquals(0, preferences.pdf.rotation)
        assertEquals(ReaderPdfCropMargins.Off, preferences.pdf.cropMargins)
        assertTrue(preferences.interaction.swipePageTurn)
        assertFalse(preferences.interaction.keepScreenAwake)
    }

    @Test
    fun legacyPaperNightAndSystemValuesMigrate() {
        val codec = ReaderPreferencesJson()

        val paper = codec.decode("""{"theme":"paper","fontSize":1.2,"readingMode":"paged"}""")
        val night = codec.decode("""{"theme":"night"}""")
        val system = codec.decode("""{"theme":"system","readingMode":"continuous_scroll"}""")

        assertEquals(ReaderTheme.Warm, paper.appearance.theme)
        assertEquals(22, paper.epub.fontSize)
        assertEquals(ReaderTheme.Night, night.appearance.theme)
        assertEquals(ReaderThemeMode.System, system.appearance.themeMode)
        assertEquals(ReaderReadingMode.ContinuousScroll, system.epub.flow)
    }

    @Test
    fun nativeEpubCapabilitiesDisableOnlyUnsupportedWebControls() {
        val ios = ReaderCapabilities.epub(supportsVolumeKeys = false)
        val android = ReaderCapabilities.epub(supportsVolumeKeys = true)

        assertTrue(ios.supportsReadingMode)
        assertTrue(ios.supportsSpreadMode)
        assertTrue(ios.supportsParagraphLayout)
        assertFalse(ios.supportsNegativeLetterSpacing)
        assertFalse(ios.supportsIndependentPublisherStyles)
        assertFalse(ios.supportsPageTurnAnimation)
        assertFalse(ios.supportsSwipeToggle)
        assertFalse(ios.supportsAnnotations)
        assertFalse(ios.supportsVolumeKeyPageTurn)
        assertTrue(android.supportsVolumeKeyPageTurn)
    }

    @Test
    fun controlProfilesMatchWebMorphologyRules() {
        val reflowable = ReaderControlProfile.forMorphology(ReaderMorphology.Reflowable)
        assertEquals(listOf(ReaderReadingMode.Paged, ReaderReadingMode.ContinuousScroll), reflowable.readingModes)
        assertTrue(reflowable.disabledReadingModes.isEmpty())
        assertEquals(listOf(ReaderSpreadMode.Single, ReaderSpreadMode.Double), reflowable.reflowableSpreadModes)

        val comic = ReaderControlProfile.forMorphology(ReaderMorphology.Comic)
        assertTrue(comic.showsComicDirection)
        assertTrue(comic.showsComicCoverSingle)
        assertTrue(comic.showsComicPageGap)

        val pdf = ReaderControlProfile.forMorphology(ReaderMorphology.Pdf)
        assertTrue(pdf.readingModes.isEmpty())
        assertTrue(pdf.showsPdfControls)
    }
}
