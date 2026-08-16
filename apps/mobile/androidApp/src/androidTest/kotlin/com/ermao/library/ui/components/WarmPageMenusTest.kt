package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Rule
import org.junit.Test

class WarmPageMenusTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun singleChoiceOptionsExposeSelectionAndRadioRole() {
        composeRule.setContent {
            WarmPageTheme {
                Box {
                    WarmPageSingleChoiceMenu(
                        title = "View",
                        expanded = true,
                        options = listOf(
                            WarmPageMenuOption(value = "grid", label = "Grid"),
                            WarmPageMenuOption(value = "list", label = "List"),
                        ),
                        selected = "grid",
                        onSelect = {},
                        onDismiss = {},
                    )
                }
            }
        }

        val radioRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)
        composeRule.onNodeWithText("Grid").assertIsSelected().assert(radioRole)
        composeRule.onNodeWithText("List").assertIsNotSelected().assert(radioRole)
    }
}
