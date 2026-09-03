package com.ermao.library.ui.components

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocalLibrary
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.outlined.CollectionsBookmark
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.LocalLibrary
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.height
import com.ermao.library.R
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class WarmPageNavigationTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun compactNavigationSharesOneSurfaceWithAccessoryAndPreservesTabSemantics() {
        val navigationItems = listOf(
            WarmPageNavigationItem(
                id = "home",
                labelResource = R.string.tab_home,
                selectedIcon = Icons.Filled.Home,
                unselectedIcon = Icons.Outlined.Home,
                testTag = "tab-select-home",
            ),
            WarmPageNavigationItem(
                id = "library",
                labelResource = R.string.tab_library,
                selectedIcon = Icons.Filled.LocalLibrary,
                unselectedIcon = Icons.Outlined.LocalLibrary,
                testTag = "tab-select-library",
            ),
            WarmPageNavigationItem(
                id = "shelves",
                labelResource = R.string.tab_shelves,
                selectedIcon = Icons.Filled.CollectionsBookmark,
                unselectedIcon = Icons.Outlined.CollectionsBookmark,
                testTag = "tab-select-shelves",
            ),
            WarmPageNavigationItem(
                id = "me",
                labelResource = R.string.tab_me,
                selectedIcon = Icons.Filled.Person,
                unselectedIcon = Icons.Outlined.Person,
                testTag = "tab-select-me",
            ),
        )

        composeRule.setContent {
            var selected by remember { mutableStateOf("home") }
            WarmPageTheme(darkTheme = false) {
                WarmPageNavigationSuite(
                    items = navigationItems,
                    selected = selected,
                    onSelect = { selected = it },
                    modifier = Modifier.size(400.dp),
                    bottomAccessory = {
                        androidx.compose.foundation.layout.Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(72.dp)
                                .testTag("mini-player-slot"),
                        )
                    },
                ) {
                    androidx.compose.foundation.layout.Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .testTag("navigation-content"),
                    )
                }
            }
        }

        composeRule.onNodeWithTag("bottom-navigation-shell").assertIsDisplayed()
        composeRule.onNodeWithTag("mini-player-slot").assertIsDisplayed()
        val tabRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab)
        navigationItems.forEach { item ->
            val tab = composeRule.onNodeWithTag(item.testTag)
            tab.assertIsDisplayed().assert(tabRole).assertHasClickAction()
            assertTrue(tab.getUnclippedBoundsInRoot().height >= 48.dp)
            tab.performClick().assertIsSelected()
        }
        val miniPlayerBounds = composeRule.onNodeWithTag("mini-player-slot").getUnclippedBoundsInRoot()
        val tabBounds = composeRule.onNodeWithTag("tab-select-home").getUnclippedBoundsInRoot()
        assertTrue(
            "Mini player must finish above the tab controls",
            miniPlayerBounds.bottom <= tabBounds.top,
        )
    }

    @Test
    fun rootNavigationRemainsVisibleWhenScrollableContentReachesItsEnd() {
        val rows = List(60) { "row-$it" }
        val navigationItems = listOf(
            WarmPageNavigationItem(
                id = "home",
                labelResource = R.string.tab_home,
                selectedIcon = Icons.Filled.Home,
                unselectedIcon = Icons.Outlined.Home,
                testTag = "persistent-tab-home",
            ),
            WarmPageNavigationItem(
                id = "library",
                labelResource = R.string.tab_library,
                selectedIcon = Icons.Filled.LocalLibrary,
                unselectedIcon = Icons.Outlined.LocalLibrary,
                testTag = "persistent-tab-library",
            ),
        )

        composeRule.setContent {
            var selected by remember { mutableStateOf("library") }
            WarmPageTheme(darkTheme = false) {
                WarmPageNavigationSuite(
                    items = navigationItems,
                    selected = selected,
                    onSelect = { selected = it },
                ) {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .testTag("scrolling-root-content"),
                    ) {
                        items(rows) { row ->
                            Text(
                                text = row,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(96.dp)
                                    .testTag(row),
                            )
                        }
                    }
                }
            }
        }

        composeRule.onNodeWithTag("scrolling-root-content").performScrollToIndex(rows.lastIndex)

        composeRule.onNodeWithTag(rows.last()).assertIsDisplayed()
        composeRule.onNodeWithTag("persistent-tab-home").assertIsDisplayed()
        composeRule.onNodeWithTag("persistent-tab-library").assertIsDisplayed()
    }
}
