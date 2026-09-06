package com.ermao.library.features.library.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkContentsPathSheetTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun longPathTitlesStayWholeAndAncestorsKeepTheirSourceNodeIds() {
        val longCurrentTitle =
            "A very long current directory title that must wrap across lines without being truncated"
        var callbackCount = 0
        var selectedSourceNodeId: String? = "unset"
        val breadcrumbs = listOf(
            WorkContentBreadcrumbPresentation("The Book", null),
            WorkContentBreadcrumbPresentation("Collected stories and essays", "ancestor"),
            WorkContentBreadcrumbPresentation(longCurrentTitle, "current"),
        )

        compose.setContent {
            WarmPageTheme(darkTheme = false) {
                WorkContentsPathSheet(
                    breadcrumbs = breadcrumbs,
                    onSelectSourceNode = {
                        callbackCount += 1
                        selectedSourceNodeId = it
                    },
                    onDismiss = {},
                )
            }
        }

        compose.onNodeWithText("The Book").assertIsDisplayed()
        val currentTitle = compose.onNodeWithText(longCurrentTitle, useUnmergedTree = true)
            .assertIsDisplayed()
            .assertTextEquals(longCurrentTitle)
        val textLayouts = mutableListOf<TextLayoutResult>()
        currentTitle.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { getLayouts ->
            getLayouts(textLayouts)
        }
        val currentLayout = textLayouts.single()
        assertTrue(
            "Long current directory title should wrap instead of staying one line",
            currentLayout.lineCount > 1,
        )
        assertTrue("Full directory title must fit without clipping", !currentLayout.hasVisualOverflow)
        compose.onNodeWithTag("work-contents-path-option-current").assertIsSelected()
        compose.onNodeWithTag("work-contents-path-option-root")
            .assertIsNotSelected()
            .performClick()
        compose.runOnIdle {
            assertEquals(1, callbackCount)
            assertNull(selectedSourceNodeId)
        }
        compose.onNodeWithTag("work-contents-path-option-ancestor").performClick()
        compose.runOnIdle {
            assertEquals(2, callbackCount)
            assertEquals("ancestor", selectedSourceNodeId)
        }
    }
}
