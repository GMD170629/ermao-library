package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettingsComponentsTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun saveActionShowsTextAndBecomesDisabledWhileWorking() {
        val working = mutableStateOf(false)
        var clickCount = 0

        compose.setContent {
            WarmPageTheme {
                SettingsSaveAction(
                    contentDescription = "Save settings",
                    label = "Save",
                    enabled = true,
                    working = working.value,
                    onClick = { clickCount++ },
                    modifier = Modifier.testTag("settings-save-component"),
                )
            }
        }

        compose.onNodeWithTag("settings-save-component").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, clickCount) }
        compose.onNodeWithText("Save").assertIsDisplayed()

        compose.runOnIdle { working.value = true }
        compose.waitForIdle()
        compose.onNodeWithTag("settings-save-component").assertIsNotEnabled()
        compose.onAllNodesWithText("Save").assertCountEquals(0)
    }

    @Test
    fun switchAndRadioRowsExposeOneInteractiveSemanticNodeEach() {
        val switchChecked = mutableStateOf(false)
        val radioSelected = mutableStateOf(false)

        compose.setContent {
            WarmPageTheme {
                Column {
                    WarmSettingsSwitchRow(
                        label = "Sync over Wi-Fi",
                        checked = switchChecked.value,
                        onCheckedChange = { switchChecked.value = it },
                        modifier = Modifier.testTag("settings-switch-component"),
                    )
                    WarmSettingsRadioRow(
                        label = "Use system language",
                        selected = radioSelected.value,
                        onClick = { radioSelected.value = true },
                        modifier = Modifier.testTag("settings-radio-component"),
                    )
                }
            }
        }

        val switchRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Switch)
        val radioRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)
        compose.onAllNodes(switchRole, useUnmergedTree = true).assertCountEquals(1)
        compose.onAllNodes(radioRole, useUnmergedTree = true).assertCountEquals(1)
        compose.onNodeWithTag("settings-switch-component").assert(switchRole).assertIsOff().performClick().assertIsOn()
        compose.onNodeWithTag("settings-radio-component").assert(radioRole).assertIsNotSelected().performClick().assertIsSelected()
    }

    @Test
    fun tabsHaveEqualWidthsAndMinimumTouchTarget() {
        compose.setContent {
            WarmPageTheme {
                SettingsTabRow(
                    selectedIndex = 0,
                    tabs = listOf("Email", "Password", "Sessions"),
                    onSelect = {},
                    modifier = Modifier.width(360.dp).testTag("settings-tabs-component"),
                )
            }
        }

        val tabRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab)
        val tabs = compose.onAllNodes(tabRole, useUnmergedTree = true)
        tabs.assertCountEquals(3)
        val bounds = (0 until 3).map { tabs[it].getUnclippedBoundsInRoot() }
        assertTrue(
            "settings tabs must be at least 48dp high",
            bounds.all { it.bottom - it.top >= 48.dp },
        )
        val firstWidth = bounds.first().right - bounds.first().left
        assertTrue(
            "settings tabs must have equal widths",
            bounds.drop(1).all {
                val width = it.right - it.left
                abs(width.value - firstWidth.value) <= 1f
            },
        )
        compose.onNodeWithTag("settings-tabs-component").assertIsDisplayed()
    }

    @Test
    fun segmentedControlKeepsEqualHeightAtTwoHundredPercentFontScale() {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale = 2f)) {
                WarmPageTheme {
                    WarmPageSegmentedControl(
                        options = listOf(
                            WarmPageChoice("zh", "Simplified Chinese"),
                            WarmPageChoice("en", "English (United States)"),
                        ),
                        selected = "en",
                        onSelect = {},
                        modifier = Modifier.width(360.dp),
                    )
                }
            }
        }

        val radioRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)
        val segments = compose.onAllNodes(radioRole, useUnmergedTree = true)
        segments.assertCountEquals(2)
        val bounds = (0 until 2).map { segments[it].getUnclippedBoundsInRoot() }
        assertTrue(
            "large-font segments must share one height",
            abs((bounds[0].bottom - bounds[0].top).value - (bounds[1].bottom - bounds[1].top).value) <= 1f,
        )
        assertTrue(
            "large-font segments must grow beyond the 48dp minimum",
            bounds.all { it.bottom - it.top >= 128.dp },
        )
    }

    @Test
    fun filterBarExposesSelectedFilterAndUpdatesSelection() {
        val selected = mutableStateOf("all")
        compose.setContent {
            WarmPageTheme {
                WarmSettingsFilterBar(
                    options = listOf(
                        WarmSettingsFilterOption("all", "All"),
                        WarmSettingsFilterOption("failed", "Failed"),
                        WarmSettingsFilterOption("queued", "Queued"),
                    ),
                    selected = selected.value,
                    onSelect = { selected.value = it },
                    modifier = Modifier.testTag("settings-filter-component"),
                )
            }
        }

        compose.onNodeWithTag("settings-filter-component").assertIsDisplayed()
        compose.onNodeWithText("All").assertIsSelected()
        compose.onNodeWithText("Failed").assertIsNotSelected().performClick().assertIsSelected()
        compose.runOnIdle { assertEquals("failed", selected.value) }
    }

    @Test
    fun choiceSheetExposesRadioOptionsSelectsAndDismisses() {
        val selected = mutableStateOf("one")
        val visible = mutableStateOf(true)
        compose.setContent {
            WarmPageTheme {
                if (visible.value) {
                    WarmSettingsChoiceSheet(
                        title = "Reading progress",
                        options = listOf(
                            WarmSettingsChoice("one", "one", "Automatic"),
                            WarmSettingsChoice("two", "two", "Current position"),
                            WarmSettingsChoice("three", "three", "Remaining"),
                        ),
                        selected = selected.value,
                        onSelect = { selected.value = it },
                        onDismissRequest = { visible.value = false },
                    )
                }
            }
        }

        compose.onNodeWithTag("settings-choice-sheet").assertIsDisplayed()
        compose.onNodeWithTag("settings-choice-two").assertIsNotSelected().performClick()
        compose.runOnIdle { assertEquals("two", selected.value) }
        compose.onNodeWithTag("settings-choice-sheet").assertDoesNotExist()
    }
}
