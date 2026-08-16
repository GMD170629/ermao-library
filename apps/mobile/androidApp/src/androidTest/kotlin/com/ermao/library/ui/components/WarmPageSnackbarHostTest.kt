package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Button
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WarmPageSnackbarHostTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun snackbarAnnouncesARecoverableOutcomeAndExposesItsAction() {
        val result = AtomicReference<SnackbarResult?>()
        compose.setContent {
            WarmPageTheme(darkTheme = false) {
                val hostState = remember { SnackbarHostState() }
                val scope = rememberCoroutineScope()
                Box(Modifier.fillMaxSize()) {
                    Button(
                        onClick = {
                            scope.launch {
                                result.set(
                                    hostState.showSnackbar(
                                        message = "Bookmark added",
                                        actionLabel = "Undo",
                                        withDismissAction = true,
                                        duration = SnackbarDuration.Indefinite,
                                    ),
                                )
                            }
                        },
                        modifier = Modifier.testTag("show-snackbar"),
                    ) {
                        Text("Show")
                    }
                    WarmPageSnackbarHost(
                        hostState = hostState,
                        modifier = Modifier.align(Alignment.BottomCenter),
                    )
                }
            }
        }

        compose.onNodeWithTag("show-snackbar").performClick()
        compose.onNodeWithTag("warm-page-snackbar").assertIsDisplayed()
        compose.onNodeWithText("Bookmark added").assertIsDisplayed()
        compose.onNodeWithText("Undo").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(SnackbarResult.ActionPerformed, result.get()) }
    }
}
