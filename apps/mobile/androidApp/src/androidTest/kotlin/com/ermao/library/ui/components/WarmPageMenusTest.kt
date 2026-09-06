package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.performClick
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue

class WarmPageMenusTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun longActionTitlesStayWithinCompactMenuAndDisabledActionsStayDisabled() {
        var selected: String? = null
        composeRule.setContent {
            WarmPageTheme {
                Box {
                    WarmPageActionMenu(
                        expanded = true,
                        title = "A long book or directory title that must wrap inside the compact menu",
                        actions = listOf(
                            WarmPageMenuAction("edit", "Edit"),
                            WarmPageMenuAction("regenerate", "Regenerate cover", enabled = false),
                        ),
                        onSelect = { selected = it },
                        onDismiss = {},
                        modifier = Modifier.testTag("compact-action-menu"),
                    )
                }
            }
        }
        val menu = composeRule.onNodeWithTag("compact-action-menu").assertIsDisplayed()
            .getUnclippedBoundsInRoot()
        assertTrue("Long titles must not stretch the popup", menu.right - menu.left <= 224.dp)
        composeRule.onNodeWithText("Regenerate cover").assertIsDisplayed().assertIsNotEnabled()
        composeRule.onNodeWithText("Edit").performClick()
        composeRule.runOnIdle { assertEquals("edit", selected) }
    }

    @Test
    fun firstMiddleAndLastChoiceKeepTheSameTextBoundsWhenSelectionMoves() {
        val labels = listOf("First", "Middle option", "Last")
        composeRule.setContent {
            val selected = remember { mutableStateOf(labels.first()) }
            WarmPageTheme {
                Box {
                    WarmPageSingleChoiceMenu(
                        expanded = true,
                        options = labels.mapIndexed { index, label ->
                            WarmPageMenuOption(label, label, if (index == 0) Icons.Filled.Check else null)
                        },
                        selected = selected.value,
                        onSelect = { selected.value = it },
                        onDismiss = {},
                    )
                }
            }
        }
        val original = labels.map {
            composeRule.onNodeWithText(it, useUnmergedTree = true).getUnclippedBoundsInRoot()
        }
        original.forEach {
            assertEquals(original.first().left, it.left)
            assertEquals(original.first().right, it.right)
        }
        labels.forEach { selected ->
            composeRule.onNodeWithText(selected).performClick().assertIsSelected()
            labels.forEachIndexed { index, label ->
                assertEquals(original[index], composeRule.onNodeWithText(label, useUnmergedTree = true).getUnclippedBoundsInRoot())
            }
        }
    }

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
