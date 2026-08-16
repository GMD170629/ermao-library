package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.features.library.ui.WorkDetailActionLayout
import com.ermao.library.features.library.ui.workDetailActionLayoutForLabels
import com.ermao.library.ui.theme.WarmPageTheme
import com.ermao.library.ui.theme.WarmPageThemeValues
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WarmPageActionsTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun compactWorkDetailActionsKeepLocalizedLabelsAndIconsIntact() {
        lateinit var activeScenario: MutableState<ActionScenario>
        compose.setContent {
            val deviceDensity = LocalDensity.current
            activeScenario = remember { mutableStateOf(actionScenarios.first()) }
            val scenario = activeScenario.value
            CompositionLocalProvider(
                LocalDensity provides Density(
                    density = deviceDensity.density,
                    fontScale = scenario.fontScale,
                ),
            ) {
                WarmPageTheme(darkTheme = false) {
                    ActionPair(scenario)
                }
            }
        }

        actionScenarios.forEach { scenario ->
            compose.runOnIdle { activeScenario.value = scenario }
            compose.waitForIdle()
            assertActionPair(scenario)
        }
    }

    private fun assertActionPair(scenario: ActionScenario) {
        val secondary = compose.onNodeWithTag(SECONDARY_ACTION_TAG).assertIsDisplayed()
        val primary = compose.onNodeWithTag(PRIMARY_ACTION_TAG).assertIsDisplayed()
        val leadingIcon = compose.onNode(
            hasTestTag(WARM_PAGE_ACTION_LEADING_ICON_TEST_TAG) and
                hasAnyAncestor(hasTestTag(SECONDARY_ACTION_TAG)),
            useUnmergedTree = true,
        ).assertIsDisplayed()
        val secondaryLabel = compose.onNode(
            hasTestTag(WARM_PAGE_ACTION_LABEL_TEST_TAG) and
                hasAnyAncestor(hasTestTag(SECONDARY_ACTION_TAG)),
            useUnmergedTree = true,
        ).assertIsDisplayed()
        val primaryLabel = compose.onNode(
            hasTestTag(WARM_PAGE_ACTION_LABEL_TEST_TAG) and
                hasAnyAncestor(hasTestTag(PRIMARY_ACTION_TAG)),
            useUnmergedTree = true,
        ).assertIsDisplayed()
        val trailingIcon = compose.onNode(
            hasTestTag(WARM_PAGE_ACTION_TRAILING_ICON_TEST_TAG) and
                hasAnyAncestor(hasTestTag(PRIMARY_ACTION_TAG)),
            useUnmergedTree = true,
        ).assertIsDisplayed()

        val secondaryBounds = secondary.getUnclippedBoundsInRoot()
        val primaryBounds = primary.getUnclippedBoundsInRoot()
        val leadingIconBounds = leadingIcon.getUnclippedBoundsInRoot()
        val secondaryLabelBounds = secondaryLabel.getUnclippedBoundsInRoot()
        val primaryLabelBounds = primaryLabel.getUnclippedBoundsInRoot()
        val trailingIconBounds = trailingIcon.getUnclippedBoundsInRoot()
        val secondaryReference = compose.onNodeWithTag(SECONDARY_REFERENCE_TAG)
            .getUnclippedBoundsInRoot()
        val primaryReference = compose.onNodeWithTag(PRIMARY_REFERENCE_TAG)
            .getUnclippedBoundsInRoot()

        val leadingIconWidth = leadingIconBounds.right - leadingIconBounds.left
        val leadingIconHeight = leadingIconBounds.bottom - leadingIconBounds.top
        val trailingIconWidth = trailingIconBounds.right - trailingIconBounds.left
        val trailingIconHeight = trailingIconBounds.bottom - trailingIconBounds.top
        val secondaryLabelWidth = secondaryLabelBounds.right - secondaryLabelBounds.left
        val primaryLabelWidth = primaryLabelBounds.right - primaryLabelBounds.left
        val secondaryReferenceWidth = secondaryReference.right - secondaryReference.left
        val primaryReferenceWidth = primaryReference.right - primaryReference.left

        assertTrue("${scenario.name}: leading icon width collapsed", leadingIconWidth >= 23.dp)
        assertTrue("${scenario.name}: leading icon height collapsed", leadingIconHeight >= 23.dp)
        assertTrue("${scenario.name}: trailing icon width collapsed", trailingIconWidth >= 23.dp)
        assertTrue("${scenario.name}: trailing icon height collapsed", trailingIconHeight >= 23.dp)
        assertTrue(
            "${scenario.name}: secondary label was clipped",
            secondaryLabelWidth + 1.dp >= secondaryReferenceWidth,
        )
        assertTrue(
            "${scenario.name}: primary label was clipped",
            primaryLabelWidth + 1.dp >= primaryReferenceWidth,
        )
        assertTrue("${scenario.name}: leading icon overlaps its label", leadingIconBounds.right <= secondaryLabelBounds.left)
        assertTrue("${scenario.name}: label overlaps trailing icon", primaryLabelBounds.right <= trailingIconBounds.left)
        assertTrue("${scenario.name}: secondary content escapes its button", leadingIconBounds.left >= secondaryBounds.left)
        assertTrue("${scenario.name}: secondary content escapes its button", secondaryLabelBounds.right <= secondaryBounds.right)
        assertTrue("${scenario.name}: primary content escapes its button", primaryLabelBounds.left >= primaryBounds.left)
        assertTrue("${scenario.name}: primary content escapes its button", trailingIconBounds.right <= primaryBounds.right)
        val separatedHorizontally = secondaryBounds.right <= primaryBounds.left
        val separatedVertically = secondaryBounds.bottom <= primaryBounds.top
        assertTrue(
            "${scenario.name}: actions overlap; secondary=$secondaryBounds, primary=$primaryBounds",
            separatedHorizontally || separatedVertically,
        )
    }
}

@androidx.compose.runtime.Composable
private fun ActionPair(scenario: ActionScenario) {
    val theme = WarmPageThemeValues
    Column(modifier = Modifier.width(scenario.contentWidth)) {
        val secondary: @androidx.compose.runtime.Composable (Modifier) -> Unit = { modifier ->
            WarmPageSecondaryAction(
                label = scenario.secondaryLabel,
                leadingIcon = Icons.Outlined.BookmarkBorder,
                onClick = {},
                modifier = modifier.testTag(SECONDARY_ACTION_TAG),
            )
        }
        val primary: @androidx.compose.runtime.Composable (Modifier) -> Unit = { modifier ->
            WarmPagePrimaryAction(
                label = scenario.primaryLabel,
                trailingIcon = Icons.Filled.PlayArrow,
                onClick = {},
                modifier = modifier.testTag(PRIMARY_ACTION_TAG),
            )
        }
        when (
            workDetailActionLayoutForLabels(
                availableWidth = scenario.contentWidth,
                fontScale = scenario.fontScale,
                secondaryLabel = scenario.secondaryLabel,
                primaryLabel = scenario.primaryLabel,
            )
        ) {
            WorkDetailActionLayout.Inline -> {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
                ) {
                    secondary(Modifier.weight(1f))
                    primary(Modifier.weight(1f))
                }
            }
            WorkDetailActionLayout.Stacked -> {
                Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
                    secondary(Modifier.fillMaxWidth())
                    primary(Modifier.fillMaxWidth())
                }
            }
        }
        Text(
            text = scenario.secondaryLabel,
            style = theme.typography.button,
            modifier = Modifier.testTag(SECONDARY_REFERENCE_TAG),
        )
        Text(
            text = scenario.primaryLabel,
            style = theme.typography.button,
            modifier = Modifier.testTag(PRIMARY_REFERENCE_TAG),
        )
    }
}

private data class ActionScenario(
    val name: String,
    val secondaryLabel: String,
    val primaryLabel: String,
    val contentWidth: Dp,
    val fontScale: Float,
)

private val actionScenarios = listOf(
    ActionScenario(
        "English screenshot width",
        "Add to shelf",
        "Continue Reading",
        379.dp,
        1f,
    ),
    ActionScenario(
        "English narrow",
        "Add to shelf",
        "Continue Reading",
        328.dp,
        1f,
    ),
    ActionScenario(
        "English listening",
        "Add to shelf",
        "Continue Listening",
        379.dp,
        1f,
    ),
    ActionScenario(
        "Chinese default",
        "加入书架",
        "继续阅读",
        379.dp,
        1f,
    ),
    ActionScenario(
        "English 200%",
        "Add to shelf",
        "Continue Reading",
        379.dp,
        2f,
    ),
    ActionScenario(
        "Chinese 200%",
        "加入书架",
        "继续阅读",
        379.dp,
        2f,
    ),
)

private const val SECONDARY_ACTION_TAG = "test-secondary-action"
private const val PRIMARY_ACTION_TAG = "test-primary-action"
private const val SECONDARY_REFERENCE_TAG = "test-secondary-reference"
private const val PRIMARY_REFERENCE_TAG = "test-primary-reference"
