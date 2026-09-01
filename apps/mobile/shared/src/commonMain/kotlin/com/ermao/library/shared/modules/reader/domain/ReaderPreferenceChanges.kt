package com.ermao.library.shared.modules.reader.domain

/** Rebase queued edits onto the latest committed settings without losing unrelated changes. */
fun mergeReaderPreferenceChanges(base: ReaderPreferences, requested: ReaderPreferences, current: ReaderPreferences): ReaderPreferences {
    fun <T> select(before: T, after: T, latest: T): T = if (before == after) latest else after
    return current.copy(
        appearance = current.appearance.copy(
            theme = select(base.appearance.theme, requested.appearance.theme, current.appearance.theme),
            themeMode = select(base.appearance.themeMode, requested.appearance.themeMode, current.appearance.themeMode),
        ),
        display = current.display.copy(
            progressStyle = select(base.display.progressStyle, requested.display.progressStyle, current.display.progressStyle),
            showClock = select(base.display.showClock, requested.display.showClock, current.display.showClock),
        ),
        interaction = current.interaction.copy(
            tapZones = select(base.interaction.tapZones, requested.interaction.tapZones, current.interaction.tapZones),
            swipePageTurn = select(base.interaction.swipePageTurn, requested.interaction.swipePageTurn, current.interaction.swipePageTurn),
            keyboardPageTurn = select(base.interaction.keyboardPageTurn, requested.interaction.keyboardPageTurn, current.interaction.keyboardPageTurn),
            volumeKeyPageTurn = select(base.interaction.volumeKeyPageTurn, requested.interaction.volumeKeyPageTurn, current.interaction.volumeKeyPageTurn),
            keepScreenAwake = select(base.interaction.keepScreenAwake, requested.interaction.keepScreenAwake, current.interaction.keepScreenAwake),
        ),
        epub = current.epub.copy(
            readingProgression = select(base.epub.readingProgression, requested.epub.readingProgression, current.epub.readingProgression),
            writingMode = select(base.epub.writingMode, requested.epub.writingMode, current.epub.writingMode),
            fontSize = select(base.epub.fontSize, requested.epub.fontSize, current.epub.fontSize),
            lineHeight = select(base.epub.lineHeight, requested.epub.lineHeight, current.epub.lineHeight),
            pageWidth = select(base.epub.pageWidth, requested.epub.pageWidth, current.epub.pageWidth),
            fontFamily = select(base.epub.fontFamily, requested.epub.fontFamily, current.epub.fontFamily),
            fontWeight = select(base.epub.fontWeight, requested.epub.fontWeight, current.epub.fontWeight),
            letterSpacing = select(base.epub.letterSpacing, requested.epub.letterSpacing, current.epub.letterSpacing),
            pageMargin = select(base.epub.pageMargin, requested.epub.pageMargin, current.epub.pageMargin),
            spreadMode = select(base.epub.spreadMode, requested.epub.spreadMode, current.epub.spreadMode),
            pageTurnAnimation = select(base.epub.pageTurnAnimation, requested.epub.pageTurnAnimation, current.epub.pageTurnAnimation),
            flow = select(base.epub.flow, requested.epub.flow, current.epub.flow),
            typography = current.epub.typography.copy(
                paragraphIndent = select(base.epub.typography.paragraphIndent, requested.epub.typography.paragraphIndent, current.epub.typography.paragraphIndent),
                paragraphSpacing = select(base.epub.typography.paragraphSpacing, requested.epub.typography.paragraphSpacing, current.epub.typography.paragraphSpacing),
                textAlign = select(base.epub.typography.textAlign, requested.epub.typography.textAlign, current.epub.typography.textAlign),
                preservePublisherStyles = select(base.epub.typography.preservePublisherStyles, requested.epub.typography.preservePublisherStyles, current.epub.typography.preservePublisherStyles),
            ),
            optimization = current.epub.optimization.copy(
                enabled = select(base.epub.optimization.enabled, requested.epub.optimization.enabled, current.epub.optimization.enabled),
                deduplicateIndent = select(base.epub.optimization.deduplicateIndent, requested.epub.optimization.deduplicateIndent, current.epub.optimization.deduplicateIndent),
                indentUnindented = select(base.epub.optimization.indentUnindented, requested.epub.optimization.indentUnindented, current.epub.optimization.indentUnindented),
            ),
        ),
        comic = current.comic.copy(
            direction = select(base.comic.direction, requested.comic.direction, current.comic.direction),
            spreadMode = select(base.comic.spreadMode, requested.comic.spreadMode, current.comic.spreadMode),
            pageTurnAnimation = select(base.comic.pageTurnAnimation, requested.comic.pageTurnAnimation, current.comic.pageTurnAnimation),
            imageFit = select(base.comic.imageFit, requested.comic.imageFit, current.comic.imageFit),
            imageVariant = select(base.comic.imageVariant, requested.comic.imageVariant, current.comic.imageVariant),
            zoom = select(base.comic.zoom, requested.comic.zoom, current.comic.zoom),
            pageWidth = select(base.comic.pageWidth, requested.comic.pageWidth, current.comic.pageWidth),
            flow = select(base.comic.flow, requested.comic.flow, current.comic.flow),
            coverSingle = select(base.comic.coverSingle, requested.comic.coverSingle, current.comic.coverSingle),
            pageGap = select(base.comic.pageGap, requested.comic.pageGap, current.comic.pageGap),
        ),
        pdf = current.pdf.copy(
            zoom = select(base.pdf.zoom, requested.pdf.zoom, current.pdf.zoom),
            pageWidth = select(base.pdf.pageWidth, requested.pdf.pageWidth, current.pdf.pageWidth),
            fit = select(base.pdf.fit, requested.pdf.fit, current.pdf.fit),
            flow = select(base.pdf.flow, requested.pdf.flow, current.pdf.flow),
            rotation = select(base.pdf.rotation, requested.pdf.rotation, current.pdf.rotation),
            cropMargins = select(base.pdf.cropMargins, requested.pdf.cropMargins, current.pdf.cropMargins),
        ),
    )
}

fun changedReaderControls(before: ReaderPreferences, after: ReaderPreferences): Set<ReaderControl> = buildSet {
    if (before.appearance.theme != after.appearance.theme) add(ReaderControl.Theme)
    if (before.appearance.themeMode != after.appearance.themeMode) add(ReaderControl.SystemTheme)
    if (before.display.progressStyle != after.display.progressStyle) add(ReaderControl.ProgressStyle)
    if (before.display.showClock != after.display.showClock) add(ReaderControl.Clock)
    if (before.interaction.keepScreenAwake != after.interaction.keepScreenAwake) add(ReaderControl.KeepAwake)
    if (before.interaction.tapZones != after.interaction.tapZones) add(ReaderControl.TapZones)
    if (before.interaction.swipePageTurn != after.interaction.swipePageTurn) add(ReaderControl.Swipe)
    if (before.interaction.keyboardPageTurn != after.interaction.keyboardPageTurn) add(ReaderControl.Keyboard)
    if (before.interaction.volumeKeyPageTurn != after.interaction.volumeKeyPageTurn) add(ReaderControl.VolumeKeys)
    if (before.epub.writingMode != after.epub.writingMode) add(ReaderControl.WritingMode)
    if (before.epub.readingProgression != after.epub.readingProgression) add(ReaderControl.ReadingProgression)
    if (before.epub.fontSize != after.epub.fontSize) add(ReaderControl.FontSize)
    if (before.epub.fontFamily != after.epub.fontFamily) add(ReaderControl.FontFamily)
    if (before.epub.fontWeight != after.epub.fontWeight) add(ReaderControl.FontWeight)
    if (before.epub.lineHeight != after.epub.lineHeight) add(ReaderControl.LineHeight)
    if (before.epub.pageMargin != after.epub.pageMargin) add(ReaderControl.PageMargins)
    if (before.epub.pageWidth != after.epub.pageWidth) add(ReaderControl.PageWidth)
    if (before.epub.flow != after.epub.flow) add(ReaderControl.ReadingMode)
    if (before.epub.spreadMode != after.epub.spreadMode) add(ReaderControl.Spread)
    if (before.epub.pageTurnAnimation != after.epub.pageTurnAnimation) add(ReaderControl.CommandAnimation)
    if (before.epub.typography.paragraphIndent != after.epub.typography.paragraphIndent) add(ReaderControl.ParagraphIndent)
    if (before.epub.typography.paragraphSpacing != after.epub.typography.paragraphSpacing) add(ReaderControl.ParagraphSpacing)
    if (before.epub.typography.textAlign != after.epub.typography.textAlign) add(ReaderControl.TextAlignment)
    if (before.epub.typography.preservePublisherStyles != after.epub.typography.preservePublisherStyles) add(ReaderControl.PublisherStyles)
    if (before.epub.optimization.enabled != after.epub.optimization.enabled) add(ReaderControl.SmartOptimization)
    if (before.epub.optimization.deduplicateIndent != after.epub.optimization.deduplicateIndent) add(ReaderControl.DeduplicateIndent)
    if (before.epub.optimization.indentUnindented != after.epub.optimization.indentUnindented) add(ReaderControl.IndentUnindented)
    if (before.comic.flow != after.comic.flow) add(ReaderControl.ReadingMode)
    if (before.comic.spreadMode != after.comic.spreadMode) add(ReaderControl.Spread)
    if (before.comic.pageTurnAnimation != after.comic.pageTurnAnimation) add(ReaderControl.CommandAnimation)
    if (before.comic.zoom != after.comic.zoom) add(ReaderControl.ComicZoom)
    if (before.comic.imageFit != after.comic.imageFit) add(ReaderControl.ComicFit)
    if (before.comic.imageVariant != after.comic.imageVariant) add(ReaderControl.ComicQuality)
    if (before.comic.pageWidth != after.comic.pageWidth) add(ReaderControl.PageWidth)
    if (before.comic.direction != after.comic.direction) add(ReaderControl.ComicDirection)
    if (before.comic.coverSingle != after.comic.coverSingle) add(ReaderControl.ComicCoverSingle)
    if (before.comic.pageGap != after.comic.pageGap) add(ReaderControl.ComicPageGap)
    if (before.pdf.zoom != after.pdf.zoom) add(ReaderControl.PdfZoom)
    if (before.pdf.fit != after.pdf.fit) add(ReaderControl.PdfFit)
    if (before.pdf.rotation != after.pdf.rotation) add(ReaderControl.PdfRotation)
    if (before.pdf.cropMargins != after.pdf.cropMargins) add(ReaderControl.PdfCrop)
    if (before.epub.letterSpacing != after.epub.letterSpacing) {
        add(if (after.epub.letterSpacing < 0) ReaderControl.NegativeLetterSpacing else ReaderControl.LetterSpacing)
    }
}
