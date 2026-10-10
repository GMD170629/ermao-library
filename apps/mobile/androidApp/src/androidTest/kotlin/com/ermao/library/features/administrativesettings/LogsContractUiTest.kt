package com.ermao.library.features.administrativesettings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LogsContractUiTest {
    @get:Rule val compose = createComposeRule()

    @Test fun rawLogSearchAndExportRetainTheSelectedQuery() {
        var exported: LogQuery? = null
        val raw = "failure token=test-secret path=/private/book"
        compose.setContent {
            WarmPageTheme {
                LogsScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = LogsSnapshot(LogQuery(), 1, 3, listOf(
                            LogRecord("log-1", "2026-10-10", LogLevel.Error, "worker", raw),
                            LogRecord("log-2", "2026-10-10", LogLevel.Information, "system", "completed"),
                        )),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    onCommand = { if (it is AdministrativeCommand.ExportLogs) exported = it.query },
                    onRetry = {}, onBack = {},
                )
            }
        }
        compose.onNodeWithText("worker · $raw").assertIsDisplayed()
        compose.onNodeWithText(AdministrativeCopy.SearchLogs.text(AdministrativeLocale.EnUs)).performTextInput("test-secret")
        compose.onNodeWithText("system · completed").assertDoesNotExist()
        compose.onNode(hasText(AdministrativeCopy.Failed.text(AdministrativeLocale.EnUs)) and hasClickAction()).performClick()
        compose.onNodeWithText(AdministrativeCopy.ExportFilteredLogs.text(AdministrativeLocale.EnUs)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(LogQuery(search = "test-secret", level = LogLevel.Error), exported) }
    }

    @Test fun retentionDialogDisplaysDaysAndSavesThreeDays() {
        var saved: AdministrativeCommand.SaveLogRetention? = null
        compose.setContent {
            WarmPageTheme {
                LogsScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = LogsSnapshot(LogQuery(), 1, 3, emptyList()),
                        failure = null, mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    onCommand = { if (it is AdministrativeCommand.SaveLogRetention) saved = it },
                    onRetry = {}, onBack = {},
                )
            }
        }
        compose.onNodeWithContentDescription(AdministrativeCopy.ManageLogRetention.text(AdministrativeLocale.EnUs)).performClick()
        compose.onNodeWithText(AdministrativeCopy.RetentionDays.text(AdministrativeLocale.EnUs)).assertIsDisplayed()
        compose.onNodeWithText("3").assertIsDisplayed()
        compose.onNodeWithText(AdministrativeCopy.SaveRetention.text(AdministrativeLocale.EnUs)).performClick()
        compose.runOnIdle { assertEquals(3, saved?.days) }
    }
}
