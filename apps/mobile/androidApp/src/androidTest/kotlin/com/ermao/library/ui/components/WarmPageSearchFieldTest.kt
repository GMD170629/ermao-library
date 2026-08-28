package com.ermao.library.ui.components

import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.height
import androidx.compose.ui.focus.FocusManager
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.text.AnnotatedString
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class WarmPageSearchFieldTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun catalogSearchAndNativeTabsShareHeightAndPreserveSearchIntents() {
        lateinit var focusManager: FocusManager
        compose.setContent {
            focusManager = LocalFocusManager.current
            var query by remember { mutableStateOf("") }
            var selected by remember { mutableStateOf("all") }
            WarmPageTheme(darkTheme = false) {
                WarmPageCatalogHeader(
                    query = query,
                    placeholder = "Search shelves or collections",
                    clearLabel = "Clear",
                    onQueryChanged = { query = it }, onClearQuery = { query = "" },
                    tabs = listOf(WarmPageCatalogTab("all", "All"), WarmPageCatalogTab("shelves", "Shelves"), WarmPageCatalogTab("collections", "Collections")),
                    selectedTab = selected, onSelectTab = { selected = it },
                    searchModifier = Modifier.testTag("catalog-search"),
                )
            }
        }
        val field = compose.onNodeWithTag("catalog-search")
        val tab = compose.onNodeWithTag("catalog-tab-shelves")
        assertEquals(field.getUnclippedBoundsInRoot().height, tab.getUnclippedBoundsInRoot().height)
        field.performTextInput("Reading")
        tab.performClick().assertIsSelected()
        field.assertTextEquals("Reading")
        compose.onNodeWithContentDescription("Clear").performClick()
        field.assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("")))
        compose.runOnIdle { focusManager.clearFocus() }
    }

    @Test
    fun chineseCatalogTabsKeepNativeSelectionAndSearchHeight() {
        compose.setContent {
            var selected by remember { mutableStateOf("all") }
            WarmPageTheme(darkTheme = false) {
                WarmPageCatalogHeader(
                    query = "", placeholder = "搜索书名、作者或系列", clearLabel = "清除",
                    onQueryChanged = {}, onClearQuery = {},
                    tabs = listOf(WarmPageCatalogTab("all", "全部"), WarmPageCatalogTab("library", "我的书库")),
                    selectedTab = selected, onSelectTab = { selected = it },
                    searchModifier = Modifier.testTag("catalog-search"),
                )
            }
        }
        val tab = compose.onNodeWithTag("catalog-tab-library")
        assertEquals(compose.onNodeWithTag("catalog-search").getUnclippedBoundsInRoot().height, tab.getUnclippedBoundsInRoot().height)
        tab.performClick().assertIsSelected()
    }

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
