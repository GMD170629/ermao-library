package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class ReaderTheme(val wireValue: String) {
    @SerialName("day") Day("day"),
    @SerialName("warm") Warm("warm"),
    @SerialName("green") Green("green"),
    @SerialName("night") Night("night"),
    @SerialName("black") Black("black"),
}

@Serializable
enum class ReaderThemeMode(val wireValue: String) {
    @SerialName("manual") Manual("manual"),
    @SerialName("system") System("system"),
}

@Serializable
enum class ReaderProgressStyle(val wireValue: String) {
    @SerialName("auto") Auto("auto"),
    @SerialName("percent") Percent("percent"),
    @SerialName("position") Position("position"),
    @SerialName("remaining") Remaining("remaining"),
    @SerialName("hidden") Hidden("hidden"),
}

@Serializable
enum class ReaderTapZones(val wireValue: String) {
    @SerialName("standard") Standard("standard"),
    @SerialName("reversed") Reversed("reversed"),
    @SerialName("disabled") Disabled("disabled"),
}

@Serializable
enum class ReaderFontFamily(val wireValue: String) {
    @SerialName("pingfang") Pingfang("pingfang"),
    @SerialName("heiti") Heiti("heiti"),
    @SerialName("songti") Songti("songti"),
    @SerialName("yahei") Yahei("yahei"),
    @SerialName("kaiti") Kaiti("kaiti"),
}

@Serializable
enum class ReaderPageMargin(val wireValue: String) {
    @SerialName("narrow") Narrow("narrow"),
    @SerialName("standard") Standard("standard"),
    @SerialName("wide") Wide("wide"),
}

@Serializable
enum class ReaderSpreadMode(val wireValue: String) {
    @SerialName("auto") Auto("auto"),
    @SerialName("single") Single("single"),
    @SerialName("double") Double("double"),
}

@Serializable
enum class ReaderPageTurnAnimation(val wireValue: String) {
    @SerialName("slide") Slide("slide"),
    @SerialName("off") Off("off"),
}

@Serializable
enum class ReaderReadingMode(val wireValue: String) {
    @SerialName("paginated") Paged("paginated"),
    @SerialName("scrolled") ContinuousScroll("scrolled"),
}

@Serializable
enum class ReaderComicDirection(val wireValue: String) {
    @SerialName("ltr") LeftToRight("ltr"),
    @SerialName("rtl") RightToLeft("rtl"),
}

@Serializable
enum class ReaderComicSpreadMode(val wireValue: String) {
    @SerialName("single") Single("single"),
    @SerialName("double") Double("double"),
}

@Serializable
enum class ReaderComicImageFit(val wireValue: String) {
    @SerialName("width") Width("width"),
    @SerialName("height") Height("height"),
    @SerialName("contain") Contain("contain"),
    @SerialName("original") Original("original"),
}

@Serializable
enum class ReaderComicImageVariant(val wireValue: String) {
    @SerialName("original") Original("original"),
    @SerialName("data-saver") DataSaver("data-saver"),
}

@Serializable
enum class ReaderPdfFit(val wireValue: String) {
    @SerialName("width") Width("width"),
    @SerialName("page") Page("page"),
}

@Serializable
enum class ReaderPdfFlow(val wireValue: String) {
    @SerialName("paged") Paged("paged"),
}

@Serializable
enum class ReaderPdfCropMargins(val wireValue: String) {
    @SerialName("off") Off("off"),
    @SerialName("auto") Auto("auto"),
}

enum class ReaderMorphology { Reflowable, Comic, Pdf }

data class ReaderControlProfile(
    val readingModes: List<ReaderReadingMode>,
    val disabledReadingModes: Set<ReaderReadingMode>,
    val reflowableSpreadModes: List<ReaderSpreadMode> = emptyList(),
    val comicSpreadModes: List<ReaderComicSpreadMode> = emptyList(),
    val showsComicDirection: Boolean = false,
    val showsComicCoverSingle: Boolean = false,
    val showsComicPageGap: Boolean = false,
    val showsPdfControls: Boolean = false,
) {
    companion object {
        fun forMorphology(morphology: ReaderMorphology): ReaderControlProfile = when (morphology) {
            ReaderMorphology.Reflowable -> ReaderControlProfile(
                readingModes = ReaderReadingMode.entries,
                disabledReadingModes = emptySet(),
                reflowableSpreadModes = listOf(ReaderSpreadMode.Single, ReaderSpreadMode.Double),
            )
            ReaderMorphology.Comic -> ReaderControlProfile(
                readingModes = ReaderReadingMode.entries,
                disabledReadingModes = emptySet(),
                comicSpreadModes = ReaderComicSpreadMode.entries,
                showsComicDirection = true,
                showsComicCoverSingle = true,
                showsComicPageGap = true,
            )
            ReaderMorphology.Pdf -> ReaderControlProfile(
                readingModes = emptyList(),
                disabledReadingModes = emptySet(),
                showsPdfControls = true,
            )
        }
    }
}

@Serializable
enum class ReaderTextAlignment(val wireValue: String) {
    @SerialName("publisher") PublisherDefault("publisher"),
    @SerialName("left") Start("left"),
    @SerialName("justify") Justify("justify"),
}

@Serializable
data class ReaderAppearancePreferences(
    val theme: ReaderTheme = ReaderTheme.Warm,
    val themeMode: ReaderThemeMode = ReaderThemeMode.Manual,
)

@Serializable
data class ReaderDisplayPreferences(
    val progressStyle: ReaderProgressStyle = ReaderProgressStyle.Auto,
    val showClock: Boolean = false,
)

@Serializable
data class ReaderInteractionPreferences(
    val tapZones: ReaderTapZones = ReaderTapZones.Standard,
    val swipePageTurn: Boolean = true,
    val keyboardPageTurn: Boolean = true,
    val volumeKeyPageTurn: Boolean = false,
    val keepScreenAwake: Boolean = false,
)

@Serializable
data class ReaderTypographyPreferences(
    val paragraphIndent: Double = 2.0,
    val paragraphSpacing: Double = 0.0,
    val textAlign: ReaderTextAlignment = ReaderTextAlignment.PublisherDefault,
    val preservePublisherStyles: Boolean = false,
    val allowPublisherColors: Boolean = false,
    val allowPublisherFonts: Boolean = false,
) {
    init {
        require(paragraphIndent.isFinite() && paragraphIndent in 0.0..4.0)
        require(paragraphSpacing.isFinite() && paragraphSpacing in 0.0..1.5)
    }
}

@Serializable
data class ReaderOptimizationPreferences(
    val enabled: Boolean = true,
    val deduplicateIndent: Boolean = true,
    val indentUnindented: Boolean = true,
)

@Serializable
data class ReaderEpubPreferences(
    val fontSize: Int = 18,
    val lineHeight: Double = 1.9,
    val pageWidth: Int = 1350,
    val fontFamily: ReaderFontFamily = ReaderFontFamily.Pingfang,
    val fontWeight: Int = 400,
    val letterSpacing: Double = 0.0,
    val pageMargin: ReaderPageMargin = ReaderPageMargin.Standard,
    val spreadMode: ReaderSpreadMode = ReaderSpreadMode.Single,
    val pageTurnAnimation: ReaderPageTurnAnimation = ReaderPageTurnAnimation.Slide,
    val flow: ReaderReadingMode = ReaderReadingMode.Paged,
    val typography: ReaderTypographyPreferences = ReaderTypographyPreferences(),
    val optimization: ReaderOptimizationPreferences = ReaderOptimizationPreferences(),
) {
    init {
        require(fontSize in 14..30)
        require(lineHeight.isFinite() && lineHeight in 1.4..2.4)
        require(pageWidth in 600..1350)
        require(fontWeight in setOf(400, 500, 700))
        require(letterSpacing.isFinite() && letterSpacing in -0.02..0.08)
    }
}

@Serializable
data class ReaderComicPreferences(
    val direction: ReaderComicDirection = ReaderComicDirection.LeftToRight,
    val spreadMode: ReaderComicSpreadMode = ReaderComicSpreadMode.Single,
    val pageTurnAnimation: ReaderPageTurnAnimation = ReaderPageTurnAnimation.Slide,
    val imageFit: ReaderComicImageFit = ReaderComicImageFit.Width,
    val imageVariant: ReaderComicImageVariant = ReaderComicImageVariant.Original,
    val zoom: Double = 1.0,
    val pageWidth: Int = 1350,
    val flow: ReaderReadingMode = ReaderReadingMode.Paged,
    val coverSingle: Boolean = false,
    val pageGap: Int = 0,
) {
    init {
        require(zoom.isFinite() && zoom in 0.6..2.4)
        require(pageWidth in 600..1350)
        require(pageGap in setOf(0, 8, 16, 24))
    }
}

@Serializable
data class ReaderPdfPreferences(
    val zoom: Double = 1.0,
    val pageWidth: Int = 1350,
    val fit: ReaderPdfFit = ReaderPdfFit.Page,
    val flow: ReaderPdfFlow = ReaderPdfFlow.Paged,
    val rotation: Int = 0,
    val cropMargins: ReaderPdfCropMargins = ReaderPdfCropMargins.Off,
) {
    init {
        require(zoom.isFinite() && zoom in 0.6..2.4)
        require(pageWidth in 600..1350)
        require(rotation in setOf(0, 90, 180, 270))
    }
}

@Serializable
data class ReaderPreferences(
    val schemaVersion: Int = SCHEMA_VERSION,
    val appearance: ReaderAppearancePreferences = ReaderAppearancePreferences(),
    val display: ReaderDisplayPreferences = ReaderDisplayPreferences(),
    val interaction: ReaderInteractionPreferences = ReaderInteractionPreferences(),
    val epub: ReaderEpubPreferences = ReaderEpubPreferences(),
    val comic: ReaderComicPreferences = ReaderComicPreferences(),
    val pdf: ReaderPdfPreferences = ReaderPdfPreferences(),
) {
    init {
        require(schemaVersion == SCHEMA_VERSION) { "Unsupported reader preferences schema" }
    }

    companion object {
        const val SCHEMA_VERSION = 4
    }
}

/** Runtime availability for the complete Web Reader control surface on native EPUB. */
data class ReaderCapabilities(
    val canGoPrevious: Boolean,
    val canGoNext: Boolean,
    val hasTableOfContents: Boolean,
    val supportsBookmarks: Boolean,
    val supportsAnnotations: Boolean,
    val supportsTheme: Boolean,
    val supportsSystemTheme: Boolean,
    val supportsFontSize: Boolean,
    val supportsFontFamily: Boolean,
    val supportsFontWeight: Boolean,
    val supportsLineHeight: Boolean,
    val supportsPositiveLetterSpacing: Boolean,
    val supportsNegativeLetterSpacing: Boolean,
    val supportsPageMargins: Boolean,
    val supportsPageWidth: Boolean,
    val supportsReadingMode: Boolean,
    val supportsSpreadMode: Boolean,
    val supportsParagraphLayout: Boolean,
    val supportsIndependentPublisherStyles: Boolean,
    val supportsProgressStyles: Boolean,
    val supportsClock: Boolean,
    val supportsKeepAwake: Boolean,
    val supportsTapZones: Boolean,
    val supportsSwipeToggle: Boolean,
    val supportsPageTurnAnimation: Boolean,
    val supportsSmartOptimization: Boolean,
    val supportsKeyboardPageTurn: Boolean,
    val supportsVolumeKeyPageTurn: Boolean,
    val supportsComicDirection: Boolean = false,
    val supportsComicCoverSingle: Boolean = false,
    val supportsComicPageGap: Boolean = false,
    val supportsPdfZoomPreference: Boolean = false,
    val supportsPdfFit: Boolean = false,
    val supportsPdfRotation: Boolean = false,
    val supportsPdfCropMargins: Boolean = false,
    val supportsPublisherStyles: Boolean = false,
) {
    companion object {
        fun epub(supportsVolumeKeys: Boolean, supportsCustomFonts: Boolean = true) = ReaderCapabilities(
            canGoPrevious = true,
            canGoNext = true,
            hasTableOfContents = true,
            supportsBookmarks = true,
            supportsAnnotations = false,
            supportsTheme = true,
            supportsSystemTheme = true,
            supportsFontSize = true,
            supportsFontFamily = supportsCustomFonts,
            supportsFontWeight = true,
            supportsLineHeight = true,
            supportsPositiveLetterSpacing = true,
            supportsNegativeLetterSpacing = false,
            supportsPageMargins = true,
            supportsPageWidth = false,
            supportsReadingMode = true,
            supportsSpreadMode = true,
            supportsParagraphLayout = true,
            supportsIndependentPublisherStyles = false,
            supportsProgressStyles = true,
            supportsClock = true,
            supportsKeepAwake = true,
            supportsTapZones = true,
            supportsSwipeToggle = false,
            supportsPageTurnAnimation = true,
            supportsSmartOptimization = false,
            supportsKeyboardPageTurn = true,
            supportsVolumeKeyPageTurn = supportsVolumeKeys,
            supportsPublisherStyles = true,
        )

        val Epub: ReaderCapabilities = epub(supportsVolumeKeys = false)
    }
}
