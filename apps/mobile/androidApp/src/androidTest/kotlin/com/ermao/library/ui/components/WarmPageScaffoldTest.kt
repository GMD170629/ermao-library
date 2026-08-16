package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WarmPageScaffoldTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun englishDetailTopBarKeepsNavigationTitleAndActionVisibleAtLargeText() {
        lateinit var viewportWidth: MutableState<Dp>
        compose.setContent {
            val deviceDensity = LocalDensity.current
            viewportWidth = remember { mutableStateOf(NARROW_VIEWPORT_WIDTH) }
            CompositionLocalProvider(
                LocalDensity provides Density(
                    density = deviceDensity.density,
                    fontScale = 2f,
                ),
            ) {
                WarmPageTheme(darkTheme = false) {
                    WarmPageScaffold(
                        role = WarmPageTopBarRole.Detail,
                        title = DETAIL_TITLE,
                        navigation = WarmPageNavigationAction(
                            icon = Icons.AutoMirrored.Filled.ArrowBack,
                            label = BACK_LABEL,
                            onClick = {},
                        ),
                        actions = listOf(
                            WarmPageTopBarAction(
                                icon = Icons.Outlined.MoreVert,
                                label = MORE_LABEL,
                                onClick = {},
                            ),
                        ),
                        modifier = Modifier
                            .width(viewportWidth.value)
                            .height(VIEWPORT_HEIGHT)
                            .testTag(SCAFFOLD_TAG),
                    ) { padding ->
                        Box(
                            Modifier
                                .fillMaxSize()
                                .padding(padding)
                                .testTag(CONTENT_TAG),
                        )
                    }
                }
            }
        }

        listOf(NARROW_VIEWPORT_WIDTH, PHYSICAL_VIEWPORT_WIDTH).forEach { width ->
            compose.runOnIdle { viewportWidth.value = width }
            compose.waitForIdle()

            val scaffold = compose.onNodeWithTag(SCAFFOLD_TAG)
                .assertIsDisplayed()
                .getUnclippedBoundsInRoot()
            val content = compose.onNodeWithTag(CONTENT_TAG)
                .assertIsDisplayed()
                .getUnclippedBoundsInRoot()
            val navigation = compose.onNodeWithContentDescription(BACK_LABEL)
                .assertIsDisplayed()
                .getUnclippedBoundsInRoot()
            val title = compose.onNodeWithText(DETAIL_TITLE)
                .assertIsDisplayed()
                .getUnclippedBoundsInRoot()
            val action = compose.onNodeWithContentDescription(MORE_LABEL)
                .assertIsDisplayed()
                .getUnclippedBoundsInRoot()

            listOf(BACK_LABEL to navigation, DETAIL_TITLE to title, MORE_LABEL to action).forEach { (label, bounds) ->
                assertTrue("$label is clipped horizontally at $width", bounds.left >= scaffold.left)
                assertTrue("$label is clipped horizontally at $width", bounds.right <= scaffold.right)
                assertTrue("$label is clipped above the Detail bar at $width", bounds.top >= scaffold.top)
                assertTrue("$label is clipped below the Detail bar at $width", bounds.bottom <= content.top)
            }
            assertTrue("Navigation overlaps the English Detail title at $width", navigation.right <= title.left)
            assertTrue("The English Detail title overlaps the action at $width", title.right <= action.left)
        }
    }
}

private val NARROW_VIEWPORT_WIDTH = 320.dp
private val PHYSICAL_VIEWPORT_WIDTH = 411.dp
private val VIEWPORT_HEIGHT = 320.dp
private const val DETAIL_TITLE = "Book Details"
private const val BACK_LABEL = "Navigate back"
private const val MORE_LABEL = "More actions"
private const val SCAFFOLD_TAG = "detail-scaffold"
private const val CONTENT_TAG = "detail-content"
