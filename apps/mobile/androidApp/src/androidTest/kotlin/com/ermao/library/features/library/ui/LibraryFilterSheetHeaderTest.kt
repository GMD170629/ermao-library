package com.ermao.library.features.library.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LibraryFilterSheetHeaderTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun narrowLargeTextKeepsTitleReadableAboveFullSizeActions() {
        compose.setContent {
            val deviceDensity = LocalDensity.current
            CompositionLocalProvider(
                LocalDensity provides Density(
                    density = deviceDensity.density,
                    fontScale = 2f,
                ),
            ) {
                WarmPageTheme(darkTheme = false) {
                    Box(Modifier.width(320.dp)) {
                        LibraryFilterSheetHeader(
                            title = "Filter works",
                            cancelLabel = "Cancel",
                            clearLabel = "Clear all",
                            onCancel = {},
                            onClear = {},
                        )
                    }
                }
            }
        }

        val title = compose.onNodeWithTag("library-filter-title").assertIsDisplayed()
        val cancel = compose.onNodeWithTag("library-filter-cancel")
            .assertIsDisplayed()
            .assertHeightIsAtLeast(48.dp)
        val clear = compose.onNodeWithTag("library-filter-clear")
            .assertIsDisplayed()
            .assertHeightIsAtLeast(48.dp)
        val titleBounds = title.getUnclippedBoundsInRoot()
        val cancelBounds = cancel.getUnclippedBoundsInRoot()
        val clearBounds = clear.getUnclippedBoundsInRoot()

        assertTrue(
            "The filter title must have its own readable row above the actions",
            titleBounds.bottom <= minOf(cancelBounds.top, clearBounds.top),
        )
        assertTrue(
            "Cancel and Clear all must not overlap",
            cancelBounds.right <= clearBounds.left,
        )
    }
}
