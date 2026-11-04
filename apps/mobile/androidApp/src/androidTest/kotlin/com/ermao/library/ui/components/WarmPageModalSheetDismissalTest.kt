package com.ermao.library.ui.components

import androidx.activity.OnBackPressedDispatcher
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WarmPageModalSheetDismissalTest {
    @get:Rule val compose = createComposeRule()

    private lateinit var back: OnBackPressedDispatcher
    private lateinit var animatedDismiss: () -> Unit
    private var dismissals = 0
    private var completions = 0
    private var underlyingClicks = 0

    @Test
    fun repeatedNativeBackRemovesTheDialogAndRestoresUnderlyingInput() {
        showSheet()
        overlapDismissals { back.onBackPressed(); back.onBackPressed() }
        assertDismissed()
    }

    @Test
    fun nativeBackInterruptingButtonAnimationStillCompletesExactlyOnce() {
        showSheet()
        overlapDismissals { animatedDismiss(); back.onBackPressed(); back.onBackPressed() }
        assertDismissed()
    }

    @Test
    fun refusedDismissalDoesNotHideTheSheetOrRunCompletion() {
        showSheet(canDismiss = false)
        overlapDismissals { animatedDismiss(); back.onBackPressed() }
        compose.onNodeWithTag("dismissal-sheet").assertIsDisplayed()
        assertEquals(0, dismissals)
        assertEquals(0, completions)
    }

    private fun showSheet(canDismiss: Boolean = true) {
        compose.setContent {
            var visible by remember { mutableStateOf(true) }
            WarmPageTheme(darkTheme = false) {
                Column {
                    TextButton(
                        onClick = { underlyingClicks++ },
                        modifier = Modifier.testTag("underlying-action"),
                    ) { Text("Navigate") }
                    if (visible) {
                        WarmPageModalBottomSheet(
                            onDismissRequest = { dismissals++; visible = false },
                            onDismissCompleted = { completions++ },
                            canDismiss = { canDismiss },
                            modifier = Modifier.testTag("dismissal-sheet"),
                        ) {
                            back = requireNotNull(LocalOnBackPressedDispatcherOwner.current).onBackPressedDispatcher
                            animatedDismiss = requireNotNull(LocalWarmPageModalSheetDismiss.current)
                            Text("Sheet content")
                        }
                    }
                }
            }
        }
        compose.onNodeWithTag("dismissal-sheet").assertIsDisplayed()
    }

    private fun overlapDismissals(action: () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.runOnUiThread(action)
        compose.mainClock.advanceTimeBy(1_000)
        compose.mainClock.autoAdvance = true
        compose.waitForIdle()
    }

    private fun assertDismissed() {
        compose.onNodeWithTag("dismissal-sheet").assertDoesNotExist()
        compose.onNodeWithTag("underlying-action").performClick()
        compose.runOnIdle {
            assertEquals(1, dismissals)
            assertEquals(1, completions)
            assertEquals(1, underlyingClicks)
        }
    }
}
