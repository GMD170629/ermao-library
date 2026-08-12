package com.ermao.library.shared.modules.reader.domain

enum class ReaderTheme(val wireValue: String) {
    Paper("paper"),
    Night("night"),
    System("system"),
}

enum class ReaderReadingMode(val wireValue: String) {
    Paged("paged"),
    ContinuousScroll("continuous_scroll"),
}

enum class ReaderTextAlignment(val wireValue: String) {
    PublisherDefault("publisher_default"),
    Start("start"),
    Justify("justify"),
}

data class ReaderPreferences(
    val fontSize: Double = 1.0,
    val fontFamily: String? = null,
    val lineHeight: Double = 1.2,
    val letterSpacing: Double = 0.0,
    val pageMargins: Double = 1.0,
    val theme: ReaderTheme = ReaderTheme.Paper,
    val readingMode: ReaderReadingMode = ReaderReadingMode.Paged,
    val publisherStyles: Boolean = true,
    val textAlignment: ReaderTextAlignment = ReaderTextAlignment.PublisherDefault,
) {
    init {
        require(fontSize.isFinite() && fontSize in FONT_SIZE_RANGE) { "Font size is outside the supported range" }
        require(fontFamily == null || fontFamily.isNotBlank()) { "Font family is blank" }
        require(lineHeight.isFinite() && lineHeight in LINE_HEIGHT_RANGE) {
            "Line height is outside the supported range"
        }
        require(letterSpacing.isFinite() && letterSpacing in LETTER_SPACING_RANGE) {
            "Letter spacing is outside the supported range"
        }
        require(pageMargins.isFinite() && pageMargins in PAGE_MARGIN_RANGE) {
            "Page margins are outside the supported range"
        }
    }

    private companion object {
        val FONT_SIZE_RANGE = 0.5..3.0
        val LINE_HEIGHT_RANGE = 0.8..3.0
        val LETTER_SPACING_RANGE = -0.1..0.5
        val PAGE_MARGIN_RANGE = 0.0..3.0
    }
}

data class ReaderCapabilities(
    val canGoPrevious: Boolean,
    val canGoNext: Boolean,
    val hasTableOfContents: Boolean,
    val supportsFontSize: Boolean,
    val supportsFontFamily: Boolean,
    val supportsLineHeight: Boolean,
    val supportsLetterSpacing: Boolean,
    val supportsPageMargins: Boolean,
    val supportsTheme: Boolean,
    val supportsReadingMode: Boolean,
    val supportsPublisherStyles: Boolean,
    val supportsTextAlignment: Boolean,
    val supportsSearch: Boolean,
    val supportsAnnotations: Boolean,
) {
    companion object {
        val Epub = ReaderCapabilities(
            canGoPrevious = true,
            canGoNext = true,
            hasTableOfContents = true,
            supportsFontSize = true,
            supportsFontFamily = true,
            supportsLineHeight = true,
            supportsLetterSpacing = true,
            supportsPageMargins = true,
            supportsTheme = true,
            supportsReadingMode = true,
            supportsPublisherStyles = true,
            supportsTextAlignment = true,
            supportsSearch = false,
            supportsAnnotations = false,
        )
    }
}
