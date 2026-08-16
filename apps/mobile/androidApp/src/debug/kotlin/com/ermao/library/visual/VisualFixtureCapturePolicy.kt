package com.ermao.library.visual

/**
 * A single capture surface keeps system chrome deterministic across ordinary
 * content and Material bottom sheets, which render in a separate window.
 */
internal enum class VisualFixtureCaptureSurface {
    WholeDisplay,
}

internal fun visualFixtureCaptureSurface(
    scenario: VisualFixtureScenario,
): VisualFixtureCaptureSurface = when (scenario) {
    VisualFixtureScenario.HomeDefault,
    VisualFixtureScenario.LibraryWorks,
    VisualFixtureScenario.LibraryFilter,
    VisualFixtureScenario.WorkAbout,
    VisualFixtureScenario.WorkVolumes,
    VisualFixtureScenario.WorkSingleEbook,
    VisualFixtureScenario.WorkActions,
    -> VisualFixtureCaptureSurface.WholeDisplay
}

internal data class VisualFixtureSystemBarPolicy(
    val visible: Boolean,
    /** Android's light-system-bars flag means dark foreground icons. */
    val useDarkForeground: Boolean,
)

internal fun visualFixtureSystemBarPolicy(
    appearance: VisualFixtureAppearance,
): VisualFixtureSystemBarPolicy = VisualFixtureSystemBarPolicy(
    visible = true,
    useDarkForeground = appearance == VisualFixtureAppearance.Light,
)

internal fun applicationPixelsMatch(
    previous: IntArray,
    current: IntArray,
    width: Int,
    height: Int,
    statusBarHeight: Int,
    navigationBarHeight: Int,
): Boolean {
    require(width > 0 && height > 0)
    require(previous.size >= width * height)
    require(current.size >= width * height)
    require(statusBarHeight in 0..height)
    require(navigationBarHeight in 0..height)
    require(statusBarHeight + navigationBarHeight <= height)

    for (y in statusBarHeight until height - navigationBarHeight) {
        val rowOffset = y * width
        for (x in 0 until width) {
            val index = rowOffset + x
            if (previous[index] != current[index]) return false
        }
    }
    return true
}

internal fun isDynamicSystemChromePixel(
    x: Int,
    y: Int,
    width: Int,
    height: Int,
): Boolean {
    if (x !in 0 until width || y !in 0 until height) return false
    val scale = height.toFloat() / REFERENCE_CAPTURE_HEIGHT_PX.toFloat()
    val statusBarHeight = (REFERENCE_STATUS_BAR_MASK_HEIGHT_PX * scale).toInt()
    val navigationBarHeight = (REFERENCE_NAVIGATION_BAR_MASK_HEIGHT_PX * scale).toInt()
    return y < statusBarHeight || y >= height - navigationBarHeight
}

internal fun visualFixtureStatusBarMaskHeight(height: Int): Int =
    (REFERENCE_STATUS_BAR_MASK_HEIGHT_PX * height.toFloat() / REFERENCE_CAPTURE_HEIGHT_PX.toFloat()).toInt()

internal fun visualFixtureNavigationBarMaskHeight(height: Int): Int =
    (REFERENCE_NAVIGATION_BAR_MASK_HEIGHT_PX * height.toFloat() / REFERENCE_CAPTURE_HEIGHT_PX.toFloat()).toInt()

private const val REFERENCE_CAPTURE_HEIGHT_PX = 2400
private const val REFERENCE_STATUS_BAR_MASK_HEIGHT_PX = 128
private const val REFERENCE_NAVIGATION_BAR_MASK_HEIGHT_PX = 128
