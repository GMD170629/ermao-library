package com.ermao.library.features.library.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkReadingStatusChoicesTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun normalFontPresentsSupportedManualStatusTargetsAndUpdatesCurrentState() {
        compose.setContent {
            var selected by remember { mutableStateOf(WorkReadingStatus.Unread) }
            WarmPageTheme(darkTheme = false) {
                Box(Modifier.width(360.dp)) {
                    WorkReadingStatusChoices(
                        selected = selected,
                        strings = englishActionsCopy,
                        onSelect = { selected = it },
                    )
                }
            }
        }

        compose.onAllNodes(hasClickAction(), useUnmergedTree = true).assertCountEquals(2)
        compose.onNodeWithTag("work-reading-status-unread").assertIsSelected()
        compose.onNodeWithTag("work-reading-status-finished")
            .assertIsNotSelected()
            .performClick()
            .assertIsSelected()
        compose.onNodeWithTag("work-reading-status-unread").assertIsNotSelected()
    }
}

private val englishActionsCopy = WorkActionsSheetStrings(
    title = "Book Actions",
    addToShelf = "Add to shelf",
    download = "Download book",
    pauseDownload = "Pause this download",
    readingStatus = "Reading status",
    unread = "Unread",
    reading = "Reading",
    finished = "Finished",
    cancel = "Cancel",
)
