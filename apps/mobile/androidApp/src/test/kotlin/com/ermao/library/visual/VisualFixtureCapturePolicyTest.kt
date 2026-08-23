package com.ermao.library.visual

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VisualFixtureCapturePolicyTest {
    @Test
    fun everyFixtureScenarioUsesTheSameWholeDisplayCaptureSurface() {
        VisualFixtureScenario.entries.forEach { scenario ->
            assertEquals(
                "$scenario must not switch system chrome on or off by changing capture backends",
                VisualFixtureCaptureSurface.WholeDisplay,
                visualFixtureCaptureSurface(scenario),
            )
        }
    }

    @Test
    fun eightOverlayAndTwentyOrdinaryVariantsShareTheSameSystemBarPolicy() {
        val overlayScenarios = setOf(
            VisualFixtureScenario.LibraryFilter,
            VisualFixtureScenario.BookActions,
        )
        val variants = VisualFixtureScenario.entries.flatMap { scenario ->
            VisualFixtureLocale.entries.flatMap { locale ->
                VisualFixtureAppearance.entries.map { appearance ->
                    VisualFixtureVariant(scenario, locale, appearance)
                }
            }
        }
        val overlays = variants.filter { it.scenario in overlayScenarios }
        val ordinary = variants.filterNot { it.scenario in overlayScenarios }

        assertEquals(8, overlays.size)
        assertEquals(20, ordinary.size)
        variants.forEach { variant ->
            val policy = visualFixtureSystemBarPolicy(variant.appearance)
            assertTrue(policy.visible)
            assertEquals(
                variant.appearance == VisualFixtureAppearance.Light,
                policy.useDarkForeground,
            )
        }
        VisualFixtureAppearance.entries.forEach { appearance ->
            assertEquals(
                ordinary.first { it.appearance == appearance }.let {
                    visualFixtureSystemBarPolicy(it.appearance)
                },
                overlays.first { it.appearance == appearance }.let {
                    visualFixtureSystemBarPolicy(it.appearance)
                },
            )
        }
    }

    @Test
    fun stableFrameComparisonIgnoresSystemChromeButNotSheetAnimation() {
        val width = 4
        val height = 6
        val first = IntArray(width * height) { 0xff101010.toInt() }
        val chromeOnlyChange = first.copyOf().apply {
            fill(0xfffefefe.toInt(), fromIndex = 0, toIndex = width)
            fill(0xffeeeeee.toInt(), fromIndex = width * (height - 1), toIndex = width * height)
        }
        assertTrue(
            applicationPixelsMatch(
                previous = first,
                current = chromeOnlyChange,
                width = width,
                height = height,
                statusBarHeight = 1,
                navigationBarHeight = 1,
            ),
        )

        val movingSheet = chromeOnlyChange.copyOf().apply {
            this[width * 3 + 1] = 0xffffffff.toInt()
        }
        assertFalse(
            applicationPixelsMatch(
                previous = first,
                current = movingSheet,
                width = width,
                height = height,
                statusBarHeight = 1,
                navigationBarHeight = 1,
            ),
        )
    }
}
