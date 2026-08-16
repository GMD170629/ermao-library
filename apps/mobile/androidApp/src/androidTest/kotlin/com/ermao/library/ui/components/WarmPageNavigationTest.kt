package com.ermao.library.ui.components

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocalLibrary
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.LocalLibrary
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Rule
import org.junit.Test

class WarmPageNavigationTest {
    @get:Rule
    val composeRule = createComposeRule()

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
