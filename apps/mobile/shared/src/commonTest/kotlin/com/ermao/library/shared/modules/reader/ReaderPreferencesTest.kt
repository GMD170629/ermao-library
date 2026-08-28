package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ReaderPreferencesTest {
    @Test
    fun queuedChangesKeepLatestValuesFromOtherControls() {
        val base = ReaderPreferences()
        val first = base.copy(epub = base.epub.copy(fontSize = 24))
        val second = base.copy(epub = base.epub.copy(lineHeight = 2.2))
        val merged = mergeReaderPreferenceChanges(base, second, first)
        assertEquals(24, merged.epub.fontSize)
        assertEquals(2.2, merged.epub.lineHeight)
        val last = base.copy(epub = base.epub.copy(fontSize = 30))
        assertEquals(30, mergeReaderPreferenceChanges(base, last, merged).epub.fontSize)
    }

    @Test
    fun controlsDistinguishUnsupportedInapplicableAndContextualLimits() {
        val preferences = ReaderPreferences()
        val reflow = readerPlatformCapabilities(ReaderMorphology.Reflowable, volumeKeys = false, pdfFit = false)
        fun state(control: ReaderControl, current: ReaderPreferences = preferences, ready: Boolean = true) =
            resolveReaderControl(control, ReaderMorphology.Reflowable, reflow, current, ready)
        assertEquals(ReaderControlAvailability.Available, state(ReaderControl.FontFamily))
        assertEquals(ReaderControlAvailability.NotImplemented, state(ReaderControl.VolumeKeys))
        assertEquals(ReaderControlAvailability.NotImplemented, state(ReaderControl.NegativeLetterSpacing))
        assertEquals(ReaderControlAvailability.NotApplicable, state(ReaderControl.PdfFit))
        assertEquals(ReaderControlAvailability.TemporarilyUnavailable, state(ReaderControl.FontSize, ready = false))
        val scrolling = preferences.copy(epub = preferences.epub.copy(flow = ReaderReadingMode.ContinuousScroll))
        assertEquals(ReaderControlAvailability.TemporarilyUnavailable, state(ReaderControl.Spread, scrolling))
        val publisher = preferences.copy(epub = preferences.epub.copy(
            typography = preferences.epub.typography.copy(preservePublisherStyles = true),
        ))
        assertEquals(ReaderControlAvailability.Available, state(ReaderControl.LineHeight, publisher))
        assertEquals(ReaderControlAvailability.Available, state(ReaderControl.PublisherStyles, publisher))
        assertEquals(ReaderControlAvailability.Available, state(ReaderControl.FontSize, publisher))
        assertEquals(ReaderControlAvailability.TemporarilyUnavailable, resolveReaderControl(
            ReaderControl.ParagraphIndent, ReaderMorphology.Reflowable, reflow, preferences, true,
            setOf(ReaderControl.ParagraphIndent),
        ))
    }

    @Test
    fun resetClearsAllReadingFormats() {
        val defaults = resetReaderPreferences()
        assertEquals(ReaderPreferences(), defaults)
        val catalogReset = ReaderSettingsCatalog.settings.first { it.id == "reset" }
        val changed = ReaderPreferences(epub = ReaderEpubPreferences(fontSize = 24), comic = ReaderComicPreferences(pageGap = 16), pdf = ReaderPdfPreferences(rotation = 90))
        assertEquals(defaults, catalogReset.change(changed, ""))
    }
    @Test
    fun defaultsMatchWebReaderV3() {
        val preferences = ReaderPreferences()

        assertEquals(5, preferences.schemaVersion)
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
        assertTrue(ios.supportsPageTurnAnimation)
        assertFalse(ios.supportsSwipeToggle)
        assertFalse(ios.supportsAnnotations)
        assertFalse(ios.supportsVolumeKeyPageTurn)
        assertTrue(android.supportsVolumeKeyPageTurn)
    }

    @Test
    fun catalogPreservesCustomValuesAndExposesEveryMorphology() {
        val preferences = ReaderPreferences(epub = ReaderEpubPreferences(lineHeight = 1.85, letterSpacing = 0.03))
        val line = ReaderSettingsCatalog.settings.first { it.id == "lineHeight" }
        assertEquals("1.85", line.value(preferences))
        assertEquals(listOf("1.6", "1.9", "2.2"), line.options.map { it.value })
        assertEquals(0.03, line.change(preferences, "2.2").epub.letterSpacing)
        assertEquals(listOf("single", "double"), ReaderSettingsCatalog.settings.first { it.id == "textSpread" }.options.map { it.value })
        ReaderMorphology.entries.forEach { format ->
            assertTrue(ReaderSettingsCatalog.settings.any { format in it.formats && it.section.endsWith("Appearance") })
        }
    }

    @Test
    fun versionFourMigrationRetainsMasterAndIsIdempotent() {
        val codec = ReaderPreferencesJson()
        val original = ReaderPreferences(epub = ReaderEpubPreferences(lineHeight = 1.85, letterSpacing = 0.03, typography = ReaderTypographyPreferences(preservePublisherStyles = true)))
        val legacy = codec.encode(original).replace("\"schemaVersion\":5", "\"schemaVersion\":4")
        val migrated = codec.decode(legacy)
        assertEquals(original, migrated)
        assertEquals(migrated, codec.decode(codec.encode(migrated)))
        assertEquals(null, codec.canonicalizeOrNull("{\"schemaVersion\":99}"))
        assertEquals(null, codec.canonicalizeOrNull("{\"schemaVersion\":5,\"epub\":{\"fontSize\":999}}"))
    }
}
