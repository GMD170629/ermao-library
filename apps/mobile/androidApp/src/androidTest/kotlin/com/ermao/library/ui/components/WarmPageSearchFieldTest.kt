package com.ermao.library.ui.components

import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class WarmPageSearchFieldTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun placeholderFitsInsideTheSearchFieldWithoutVerticalClipping() {
        compose.setContent {
            WarmPageTheme {
                WarmPageSearchField(
                    value = "",
                    placeholder = "搜索书名、作者或系列",
                    onValueChange = {},
                    onClear = {},
                    clearLabel = "清除",
                    modifier = androidx.compose.ui.Modifier.testTag("search-field"),
                )
            }
        }

        val fieldBounds = compose.onNodeWithTag("search-field").getUnclippedBoundsInRoot()
        val textBounds = compose.onNodeWithText("搜索书名、作者或系列", useUnmergedTree = true)
            .getUnclippedBoundsInRoot()

        assertTrue(textBounds.top >= fieldBounds.top)
        assertTrue(textBounds.bottom <= fieldBounds.bottom)
    }
}
