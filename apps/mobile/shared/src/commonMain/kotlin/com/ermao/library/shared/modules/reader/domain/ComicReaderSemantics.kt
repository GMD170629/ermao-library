package com.ermao.library.shared.modules.reader.domain

import kotlin.math.floor

/**
 * The rule used to turn a canonical reading order into paged comic spreads.
 *
 * This is deliberately not persisted.  The persisted `coverSingle` preference
 * is the wire-level contract; this value is the renderer-neutral interpretation
 * of that preference.
 */
enum class ComicPairingPolicy {
    PairedFromFirst,
    CoverSingle,
}

/**
 * Viewport facts needed by the comic layout policy.
 *
 * The dimensions are renderer logical units.  They are intentionally not
 * treated as source-image pixels; a platform adapter may map its density-aware
 * viewport into these units before asking for a plan.
 */
data class ComicViewport(
    val width: Int,
    val height: Int,
    val wide: Boolean = true,
) {
    init {
        require(width > 0) { "Comic viewport width must be positive" }
        require(height > 0) { "Comic viewport height must be positive" }
    }
}

/**
 * The complete effective comic presentation.  Native clients render this
 * value; they must not reinterpret `ReaderComicPreferences` independently.
 */
data class ComicPresentationPlan(
    val pageCount: Int,
    val flow: ReaderReadingMode,
    val spreadMode: ReaderComicSpreadMode,
    val pairingPolicy: ComicPairingPolicy,
    val direction: ReaderComicDirection,
    /** The exact logical page requested by the user, even when the spread anchor differs. */
    val currentPageIndex: Int,
    val anchorPageIndex: Int,
    val logicalPageIndices: List<Int>,
    val previousAnchor: Int?,
    val nextAnchor: Int?,
    val progress: Double,
    val cachePageIndices: List<Int>,
    val preloadPageIndices: List<Int>,
    val imageFit: ReaderComicImageFit,
    val imageVariant: ReaderComicImageVariant,
    val zoom: Double,
    val effectivePageWidth: Int,
    val pageGap: Int,
    val decodeMaxWidth: Int,
    val decodeMaxHeight: Int,
    val animatePageTurn: Boolean,
) {
    init {
        require(pageCount > 0) { "Comic presentation requires at least one page" }
        require(currentPageIndex in 0 until pageCount)
        require(anchorPageIndex in 0 until pageCount)
        require(logicalPageIndices.isNotEmpty())
        require(logicalPageIndices.all { it in 0 until pageCount })
        require(previousAnchor == null || previousAnchor in 0 until pageCount)
        require(nextAnchor == null || nextAnchor in 0 until pageCount)
        require(progress.isFinite() && progress in 0.0..1.0)
        require(effectivePageWidth > 0)
        require(pageGap in setOf(0, 8, 16, 24))
        require(decodeMaxWidth > 0 && decodeMaxHeight > 0)
    }
}

data class ComicPresentationInput(
    val pageCount: Int,
    val preferences: ReaderComicPreferences = ReaderComicPreferences(),
    val currentPageIndex: Int = 0,
    val viewport: ComicViewport,
    /** Canonical hrefs are required to validate an exact RestoreLocation command. */
    val resourceHrefs: List<String> = emptyList(),
    val reducedMotion: Boolean = false,
) {
    init {
        require(pageCount > 0) { "Comic page count must be positive" }
        require(currentPageIndex >= 0) { "Comic page index must not be negative" }
        require(resourceHrefs.isEmpty() || resourceHrefs.size == pageCount) {
            "Comic resource href metadata must cover every page"
        }
        require(resourceHrefs.all(String::isNotBlank)) { "Comic resource href metadata contains a blank href" }
    }
}

sealed interface ComicNavigationCommand {
    data object First : ComicNavigationCommand
    data object Last : ComicNavigationCommand
    data object Next : ComicNavigationCommand
    data object Previous : ComicNavigationCommand
    data class GoToIndex(val pageIndex: Int) : ComicNavigationCommand
    data class GoToProgress(val progression: Double) : ComicNavigationCommand
    data class RestoreLocation(val location: ComicPublicationLocation) : ComicNavigationCommand
    data object Retry : ComicNavigationCommand
}

enum class ComicNavigationOutcome {
    Moved,
    NoOp,
    RetryRequested,
    InvalidLocation,
}

data class ComicNavigationResult(
    val outcome: ComicNavigationOutcome,
    val plan: ComicPresentationPlan,
) {
    val moved: Boolean
        get() = outcome == ComicNavigationOutcome.Moved
}

/**
 * Pure state machine for a comic surface.  It owns logical page movement and
 * effective layout only; persistence, network requests and native views stay
 * behind their existing application/platform ports.
 */
class ComicReaderRuntime(input: ComicPresentationInput) {
    private var inputState: ComicPresentationInput = input

    var plan: ComicPresentationPlan = comicPresentationPlan(input)
        private set

    fun dispatch(command: ComicNavigationCommand): ComicNavigationResult {
        if (command == ComicNavigationCommand.Retry) {
            return ComicNavigationResult(ComicNavigationOutcome.RetryRequested, plan)
        }
        if (command is ComicNavigationCommand.RestoreLocation && !canRestore(command.location)) {
            return ComicNavigationResult(ComicNavigationOutcome.InvalidLocation, plan)
        }
        val target = when (command) {
            ComicNavigationCommand.First -> 0
            ComicNavigationCommand.Last -> comicLastSpreadPage(
                comicOrderedPages(inputState.pageCount),
                plan.spreadMode,
                plan.pairingPolicy,
            )
            ComicNavigationCommand.Next -> plan.nextAnchor ?: plan.anchorPageIndex
            ComicNavigationCommand.Previous -> plan.previousAnchor ?: plan.anchorPageIndex
            is ComicNavigationCommand.GoToIndex -> command.pageIndex
                .coerceIn(0, inputState.pageCount - 1)
            is ComicNavigationCommand.GoToProgress -> comicPageForProgress(
                command.progression,
                comicOrderedPages(inputState.pageCount),
            )
            is ComicNavigationCommand.RestoreLocation -> command.location.pageIndex
                .coerceIn(0, inputState.pageCount - 1)
        }
        val nextInput = inputState.copy(currentPageIndex = target)
        val nextPlan = comicPresentationPlan(nextInput)
        val outcome = if (nextPlan.anchorPageIndex == plan.anchorPageIndex &&
            nextPlan.currentPageIndex == plan.currentPageIndex
        ) {
            ComicNavigationOutcome.NoOp
        } else {
            ComicNavigationOutcome.Moved
        }
        inputState = nextInput
        plan = nextPlan
        return ComicNavigationResult(outcome, nextPlan)
    }

    private fun canRestore(location: ComicPublicationLocation): Boolean {
        val expectedHref = inputState.resourceHrefs.getOrNull(location.pageIndex) ?: return false
        return expectedHref == location.resourceHref
    }

    fun update(
        preferences: ReaderComicPreferences = inputState.preferences,
        viewport: ComicViewport = inputState.viewport,
        reducedMotion: Boolean = inputState.reducedMotion,
    ): ComicPresentationPlan {
        inputState = inputState.copy(
            preferences = preferences,
            viewport = viewport,
            reducedMotion = reducedMotion,
            currentPageIndex = inputState.currentPageIndex,
        )
        plan = comicPresentationPlan(inputState)
        return plan
    }
}

fun comicOrderedPages(pageCount: Int): List<Int> {
    require(pageCount >= 0) { "Comic page count must not be negative" }
    return List(pageCount) { it }
}

fun comicSpreadStarts(
    orderedPages: List<Int>,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> {
    if (mode == ReaderComicSpreadMode.Single) return orderedPages.toList()
    if (orderedPages.isEmpty()) return emptyList()
    return if (pairing == ComicPairingPolicy.CoverSingle) {
        orderedPages.filterIndexed { index, _ -> index == 0 || index % 2 == 1 }
    } else {
        val firstPage = orderedPages.first()
        orderedPages.filter { (it - firstPage) % 2 == 0 }
    }
}

fun comicNormalizePage(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): Int {
    if (orderedPages.isEmpty()) return 0
    val clamped = page.coerceIn(orderedPages.first(), orderedPages.last())
    if (mode == ReaderComicSpreadMode.Single) return clamped
    if (pairing == ComicPairingPolicy.CoverSingle) {
        val index = orderedPages.indexOf(clamped)
        if (index <= 0) return orderedPages.first()
        return orderedPages[if (index % 2 == 1) index else index - 1]
    }
    val firstPage = orderedPages.first()
    return if ((clamped - firstPage) % 2 == 0) clamped else clamped - 1
}

fun comicAdjacentSpreadPage(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    offset: Int,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): Int {
    require(offset == -1 || offset == 1) { "Comic spread offset must be -1 or 1" }
    val starts = comicSpreadStarts(orderedPages, mode, pairing)
    val current = comicNormalizePage(orderedPages, page, mode, pairing)
    val index = maxOf(0, starts.indexOf(current))
    return starts.getOrNull(index + offset) ?: current
}

fun comicLastSpreadPage(
    orderedPages: List<Int>,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): Int = comicSpreadStarts(orderedPages, mode, pairing).lastOrNull() ?: 0

fun comicSpreadPages(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> {
    val normalized = comicNormalizePage(orderedPages, page, mode, pairing)
    val index = orderedPages.indexOf(normalized)
    if (index < 0) return emptyList()
    if (mode == ReaderComicSpreadMode.Single) return listOf(normalized)
    if (pairing == ComicPairingPolicy.CoverSingle && index == 0) return listOf(normalized)
    return orderedPages.drop(index).take(2)
}

/** Reverses only the visual slots for RTL; logical progression remains stable. */
fun comicVisualPages(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    direction: ReaderComicDirection,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> {
    val pages = comicSpreadPages(orderedPages, page, mode, pairing)
    return if (direction == ReaderComicDirection.RightToLeft) pages.asReversed() else pages
}

fun comicCacheWindow(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> {
    val current = comicNormalizePage(orderedPages, page, mode, pairing)
    val previous = comicAdjacentSpreadPage(orderedPages, current, mode, -1, pairing)
    val next = comicAdjacentSpreadPage(orderedPages, current, mode, 1, pairing)
    return (comicSpreadPages(orderedPages, previous, mode, pairing) +
        comicSpreadPages(orderedPages, current, mode, pairing) +
        comicSpreadPages(orderedPages, next, mode, pairing)).distinct().sorted()
}

fun comicPreloadWindow(
    orderedPages: List<Int>,
    page: Int,
    mode: ReaderComicSpreadMode,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): List<Int> {
    val current = comicNormalizePage(orderedPages, page, mode, pairing)
    val visible = comicSpreadPages(orderedPages, current, mode, pairing).toSet()
    val previous = comicAdjacentSpreadPage(orderedPages, current, mode, -1, pairing)
    val next = comicAdjacentSpreadPage(orderedPages, current, mode, 1, pairing)
    return (comicSpreadPages(orderedPages, next, mode, pairing) +
        comicSpreadPages(orderedPages, previous, mode, pairing)).distinct().filterNot(visible::contains)
}

fun comicPagePercent(
    page: Int,
    orderedPages: List<Int>,
    mode: ReaderComicSpreadMode = ReaderComicSpreadMode.Single,
    pairing: ComicPairingPolicy = ComicPairingPolicy.PairedFromFirst,
): Double {
    if (orderedPages.isEmpty()) return 0.0
    if (orderedPages.size == 1) return 100.0
    val visibleLastPage = comicSpreadPages(orderedPages, page, mode, pairing).lastOrNull() ?: page
    val index = maxOf(0, orderedPages.indexOf(visibleLastPage))
    return (index.toDouble() / (orderedPages.size - 1).toDouble()) * 100.0
}

/** Maps a normalized progression to the same rounded logical page as Web. */
fun comicPageForProgress(progression: Double, orderedPages: List<Int>): Int {
    if (orderedPages.isEmpty()) return 0
    val normalized = if (progression.isFinite()) progression.coerceIn(0.0, 1.0) else 0.0
    // JavaScript Math.round is floor(value + 0.5) for this non-negative range;
    // kotlin.math.round uses ties-to-even and would diverge at exact halves.
    val index = floor(normalized * (orderedPages.size - 1).toDouble() + 0.5).toInt()
    return orderedPages.getOrElse(index) { orderedPages.first() }
}

fun comicPresentationPlan(input: ComicPresentationInput): ComicPresentationPlan {
    val orderedPages = comicOrderedPages(input.pageCount)
    val paginated = input.preferences.flow == ReaderReadingMode.Paged
    val spreadMode = if (paginated) input.preferences.spreadMode else ReaderComicSpreadMode.Single
    val pairing = if (input.preferences.coverSingle) {
        ComicPairingPolicy.CoverSingle
    } else {
        ComicPairingPolicy.PairedFromFirst
    }
    val currentPage = input.currentPageIndex.coerceIn(0, input.pageCount - 1)
    val anchor = comicNormalizePage(orderedPages, currentPage, spreadMode, pairing)
    val logicalPages = comicSpreadPages(orderedPages, anchor, spreadMode, pairing)
    val previous = comicAdjacentSpreadPage(orderedPages, anchor, spreadMode, -1, pairing)
        .takeUnless { it == anchor }
    val next = comicAdjacentSpreadPage(orderedPages, anchor, spreadMode, 1, pairing)
        .takeUnless { it == anchor }
    val effectivePageWidth = if (input.viewport.wide) {
        minOf(input.preferences.pageWidth, input.viewport.width)
    } else {
        input.viewport.width
    }
    val effectiveGap = if (paginated && spreadMode == ReaderComicSpreadMode.Double) {
        input.preferences.pageGap
    } else {
        0
    }
    val effectiveImageFit = if (paginated) input.preferences.imageFit else ReaderComicImageFit.Width
    return ComicPresentationPlan(
        pageCount = input.pageCount,
        flow = input.preferences.flow,
        spreadMode = spreadMode,
        pairingPolicy = pairing,
        direction = input.preferences.direction,
        currentPageIndex = currentPage,
        anchorPageIndex = anchor,
        logicalPageIndices = logicalPages,
        previousAnchor = previous,
        nextAnchor = next,
        progress = comicPagePercent(anchor, orderedPages, spreadMode, pairing) / 100.0,
        cachePageIndices = comicCacheWindow(orderedPages, anchor, spreadMode, pairing),
        preloadPageIndices = comicPreloadWindow(orderedPages, anchor, spreadMode, pairing),
        imageFit = effectiveImageFit,
        imageVariant = input.preferences.imageVariant,
        zoom = input.preferences.zoom,
        effectivePageWidth = effectivePageWidth,
        pageGap = effectiveGap,
        decodeMaxWidth = effectivePageWidth,
        decodeMaxHeight = input.viewport.height,
        // The flag also covers programmatic smooth scrolling in continuous
        // mode.  Reduced motion always wins on every navigation surface.
        animatePageTurn = input.preferences.pageTurnAnimation == ReaderPageTurnAnimation.Slide &&
            !input.reducedMotion,
    )
}
