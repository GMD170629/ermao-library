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
        val reflow = readerPlatformCapabilities(
            ReaderMorphology.Reflowable,
            volumeKeys = false,
            pdfZoom = false,
            pdfFit = false,
        )
        fun state(control: ReaderControl, current: ReaderPreferences = preferences, ready: Boolean = true) =
            ReaderSettingsCatalog.resolveReaderControl(
                control,
                ReaderMorphology.Reflowable,
                reflow,
                current,
                ready,
            )
        assertEquals(ReaderControlAvailability.Available, state(ReaderControl.FontFamily))
        assertEquals(ReaderControlAvailability.NotImplemented, state(ReaderControl.VolumeKeys))
        assertEquals(ReaderControlAvailability.NotImplemented, state(ReaderControl.NegativeLetterSpacing))
        assertEquals(ReaderControlAvailability.NotApplicable, state(ReaderControl.PdfFit))
        assertEquals(ReaderControlAvailability.TemporarilyUnavailable, state(ReaderControl.FontSize, ready = false))
        val scrolling = preferences.copy(epub = preferences.epub.copy(flow = ReaderReadingMode.ContinuousScroll))
        assertEquals(ReaderControlAvailability.TemporarilyUnavailable, state(ReaderControl.Spread, scrolling))
        assertEquals(ReaderControlAvailability.TemporarilyUnavailable, ReaderSettingsCatalog.resolveReaderControl(
            ReaderControl.ParagraphIndent, ReaderMorphology.Reflowable, reflow, preferences, true,
            setOf(ReaderControl.ParagraphIndent),
        ))
    }

    @Test
    fun settingStateOwnsAvailabilityReasonAndWebPrecedence() {
        val preferences = ReaderPreferences()
        val capabilities = readerPlatformCapabilities(
            ReaderMorphology.Reflowable,
            volumeKeys = false,
            pdfZoom = false,
            pdfFit = false,
        )
        val volumeKeys = ReaderSettingsCatalog.settings.first { it.id == "volumeKeyPageTurn" }
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.TemporarilyUnavailable, "engineNotReady"),
            ReaderSettingsCatalog.resolveReaderSetting(
                volumeKeys,
                ReaderMorphology.Reflowable,
                capabilities,
                preferences,
                ready = false,
            ),
        )
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.TemporarilyUnavailable, "publicationConstraint"),
            ReaderSettingsCatalog.resolveReaderSetting(
                volumeKeys,
                ReaderMorphology.Reflowable,
                capabilities,
                preferences,
                ready = true,
                nativeUnavailable = setOf(ReaderControl.VolumeKeys),
            ),
        )
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.NotImplemented, "notImplemented"),
            ReaderSettingsCatalog.resolveReaderSetting(
                volumeKeys,
                ReaderMorphology.Reflowable,
                capabilities,
                preferences,
                ready = true,
            ),
        )

        val vertical = preferences.copy(epub = preferences.epub.copy(writingMode = ReaderWritingMode.Vertical))
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.TemporarilyUnavailable, "verticalWritingMode"),
            ReaderSettingsCatalog.resolveReaderSetting(
                ReaderSettingsCatalog.settings.first { it.id == "textFlow" },
                ReaderMorphology.Reflowable,
                capabilities,
                vertical,
                ready = true,
            ),
        )
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.TemporarilyUnavailable, "narrowViewport"),
            ReaderSettingsCatalog.resolveReaderSetting(
                ReaderSettingsCatalog.settings.first { it.id == "textPageWidth" },
                ReaderMorphology.Reflowable,
                capabilities,
                preferences,
                ready = true,
                wideViewport = false,
            ),
        )
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.NotApplicable),
            ReaderSettingsCatalog.resolveReaderSetting(
                ReaderSettingsCatalog.settings.first { it.id == "comicSpread" },
                ReaderMorphology.Reflowable,
                capabilities,
                preferences,
                ready = false,
            ),
        )

        val pdfCapabilities = readerPlatformCapabilities(
            ReaderMorphology.Pdf,
            volumeKeys = false,
            pdfZoom = true,
            pdfFit = false,
        )
        assertEquals(
            ReaderSettingState(ReaderControlAvailability.NotImplemented, "zoomUnavailable"),
            ReaderSettingsCatalog.resolveReaderSetting(
                ReaderSettingsCatalog.settings.first { it.id == "pdfZoom" },
                ReaderMorphology.Pdf,
                pdfCapabilities,
                preferences,
                ready = true,
                canZoom = false,
            ),
        )
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
    fun defaultsMatchReaderContract() {
        val preferences = ReaderPreferences()

        assertEquals(6, preferences.schemaVersion)
        assertEquals(ReaderTheme.Warm, preferences.appearance.theme)
        assertEquals(ReaderThemeMode.Manual, preferences.appearance.themeMode)
        assertEquals(18, preferences.epub.fontSize)
        assertEquals(1.9, preferences.epub.lineHeight)
        assertEquals(ReaderFontFamily.Pingfang, preferences.epub.fontFamily)
        assertEquals(ReaderSpreadMode.Single, preferences.epub.spreadMode)
        assertEquals(ReaderReadingMode.Paged, preferences.epub.flow)
        assertEquals(ReaderReadingProgression.LeftToRight, preferences.epub.readingProgression)
        assertEquals(ReaderWritingMode.Horizontal, preferences.epub.writingMode)
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
    fun nativeEpubCapabilitiesDisableOnlyUnsupportedWebControls() {
        val ios = ReaderCapabilities.epub(supportsVolumeKeys = false)
        val android = ReaderCapabilities.epub(supportsVolumeKeys = true)

        assertTrue(ios.supportsReadingMode)
        assertTrue(ios.supportsReadingProgression)
        assertTrue(ios.supportsWritingMode)
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
        assertEquals(listOf("auto", "single", "double"), ReaderSettingsCatalog.settings.first { it.id == "textSpread" }.options.map { it.value })
        ReaderMorphology.entries.forEach { format ->
            assertTrue(ReaderSettingsCatalog.settings.any { format in it.formats && it.section.endsWith("Appearance") })
        }
    }

    @Test
    fun codecAcceptsOnlyCurrentSchemaAndRejectsUnknownFields() {
        val codec = ReaderPreferencesJson
        assertEquals(ReaderPreferences(), codec.decode(codec.encode(ReaderPreferences())))
        assertEquals(null, codec.canonicalizeOrNull("{}"))
        assertEquals(null, codec.canonicalizeOrNull("{\"schemaVersion\":99}"))
        assertEquals(null, codec.canonicalizeOrNull("{\"schemaVersion\":6,\"unexpectedField\":true}"))
        assertEquals(null, codec.canonicalizeOrNull("{\"schemaVersion\":6,\"epub\":{\"fontSize\":999}}"))
    }

    @Test
    fun textLayoutSerializesAndParticipatesInMergingAndChangedControls() {
        val codec = ReaderPreferencesJson
        val base = ReaderPreferences()
        val changed = base.copy(epub = base.epub.copy(
            readingProgression = ReaderReadingProgression.RightToLeft,
            writingMode = ReaderWritingMode.Vertical,
        ))
        assertEquals(changed, codec.decode(codec.encode(changed)))
        assertEquals(
            setOf(ReaderControl.ReadingProgression, ReaderControl.WritingMode),
            changedReaderControls(base, changed),
        )
        val concurrent = base.copy(epub = base.epub.copy(fontSize = 24))
        val merged = mergeReaderPreferenceChanges(base, changed, concurrent)
        assertEquals(ReaderReadingProgression.RightToLeft, merged.epub.readingProgression)
        assertEquals(ReaderWritingMode.Vertical, merged.epub.writingMode)
        assertEquals(24, merged.epub.fontSize)
    }

}
