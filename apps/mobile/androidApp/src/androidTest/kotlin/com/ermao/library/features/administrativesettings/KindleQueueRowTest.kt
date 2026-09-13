package com.ermao.library.features.administrativesettings

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class KindleQueueRowTest {
    @get:Rule val compose = createComposeRule()

    @Test fun inlineActionsKeepTaskIdentityConfirmationAndBusyState() {
        val commands = mutableListOf<AdministrativeCommand>()
        val busy = mutableStateOf(false)
        compose.setContent {
            WarmPageTheme {
                KindleQueueScreen(
                    state = AdministrativePageState(phase = AdministrativePagePhase.Content,
                        snapshot = KindleQueueSnapshot(listOf(
                            KindleTask("running", "A running book", "a***@kindle.com", QueueStatus.Running,
                                progress = 0.35f, createdAtLabel = "Today"),
                            KindleTask("failed", "A long book title that still leaves room for retry and delete", "b***@kindle.com",
                                QueueStatus.Failed, statusCode = "Connection unexpectedly closed", createdAtLabel = "Today"),
                        )), failure = null, mutationInFlight = busy.value),
                    locale = AdministrativeLocale.EnUs, onCommand = { commands += it }, onRetry = {}, onBack = {},
                )
            }
        }
        compose.onNodeWithText("a***@kindle.com", substring = true).assertDoesNotExist()
        compose.onNodeWithText("b***@kindle.com", substring = true).assertDoesNotExist()
        compose.onNodeWithText("Today").assertDoesNotExist()
        compose.onNodeWithText("Connection unexpectedly closed").assertIsDisplayed()
        compose.onNodeWithContentDescription("Cancel task").performClick()
        compose.onNodeWithContentDescription("Retry task").performClick()
        compose.runOnIdle {
            assertEquals(listOf(AdministrativeCommand.CancelKindleTask("running"),
                AdministrativeCommand.RetryKindleTask("failed")), commands)
        }
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val output = java.io.File(instrumentation.targetContext.getExternalFilesDir(null), "content-list-kindle.png")
        instrumentation.uiAutomation.takeScreenshot().let { bitmap ->
            output.outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
        compose.onNodeWithContentDescription("Delete").performClick()
        compose.onNodeWithText("Cancel").performClick()
        compose.runOnIdle { assertEquals(2, commands.size) }
        compose.onNodeWithContentDescription("Delete").performClick()
        compose.onNodeWithText("Delete").performClick()
        compose.runOnIdle {
            assertEquals(AdministrativeCommand.DeleteKindleTask("failed"), commands.last())
            busy.value = true
        }
        compose.onNodeWithContentDescription("Retry task").assertIsNotEnabled()
        compose.onNodeWithContentDescription("Delete").assertIsNotEnabled()
        compose.onNodeWithContentDescription("Cancel task").assertIsNotEnabled()
    }
}
