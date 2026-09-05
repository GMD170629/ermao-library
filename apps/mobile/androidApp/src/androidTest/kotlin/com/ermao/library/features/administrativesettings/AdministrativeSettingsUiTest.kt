package com.ermao.library.features.administrativesettings

import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AdministrativeSettingsUiTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun emailKindleTabsStayInTheSettingsTopBar() {
        compose.setContent {
            WarmPageTheme {
                EmailKindleSettingsScreen(
                    selectedTab = EmailKindleTab.Kindle,
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = EmailKindleSnapshot(
                            kindle = KindleSettings("kindle@example.test", smtpConfigured = true, senderEmail = "sender@example.test"),
                            smtp = SmtpSettings(
                                host = "smtp.example.test",
                                port = 587,
                                encryption = SmtpEncryption.StartTls,
                                senderEmail = "sender@example.test",
                                username = "sender@example.test",
                                passwordConfigured = true,
                                senderName = "Library",
                                maximumAttachmentMegabytes = 20.0,
                            ),
                            canManageSmtp = true,
                        ),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    onCommand = {},
                    onRetry = {},
                    onBack = {},
                )
            }
        }

        compose.onNodeWithTag("administrative-page-EmailAndKindle").assertIsDisplayed()
        compose.onNodeWithTag("administrative-email-tabs").assertIsDisplayed()
        compose.onNodeWithText("Kindle").assertIsDisplayed()
        compose.onNode(
            SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab) and hasText("SMTP"),
        ).performClick()
        compose.onNodeWithTag("administrative-email-tabs").assertIsDisplayed()
    }

    @Test
    fun queueFilterUsesStableBarAndShowsEmptyStateForSelectedFilter() {
        compose.setContent {
            WarmPageTheme {
                KindleQueueScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = KindleQueueSnapshot(
                            tasks = listOf(
                                KindleTask(
                                    id = "queued-1",
                                    title = "A queued book",
                                    maskedRecipient = "k***@example.test",
                                    status = QueueStatus.Queued,
                                    createdAtLabel = "Today",
                                ),
                            ),
                        ),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    onCommand = {},
                    onRetry = {},
                    onBack = {},
                )
            }
        }

        compose.onNodeWithTag("administrative-kindle-queue-filters").assertIsDisplayed()
        compose.onNode(hasText("Failed") and hasClickAction()).performClick()
        compose.onNodeWithText("Nothing here yet").assertIsDisplayed()
        compose.onNode(hasText("Failed") and hasClickAction()).assertIsDisplayed()
    }
}
