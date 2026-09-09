package com.ermao.library.features.administrativesettings

import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import kotlin.math.abs
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AdministrativeSettingsUiTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun opdsCopyUsesTheSavedCatalogAddress() {
        val catalog = "https://books.example/base/opds/v1.2/catalog"
        var copied: String? = null
        compose.setContent {
            WarmPageTheme {
                OpdsScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = OpdsSnapshot(true, true, "https://books.example/base", catalog),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    onCopy = { copied = it },
                    onCommand = {}, onRetry = {}, onBack = {},
                )
            }
        }
        compose.onNodeWithText(catalog).assertIsDisplayed()
        compose.onNodeWithText("Copy").performClick()
        org.junit.Assert.assertEquals(catalog, copied)
    }

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
    fun queueFilterUsesSettingsTabsAndPreservesAllRunningFailedSemantics() {
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
                                KindleTask(
                                    id = "running-1",
                                    title = "A running book",
                                    maskedRecipient = "r***@example.test",
                                    status = QueueStatus.Running,
                                    createdAtLabel = "Today",
                                ),
                                KindleTask(
                                    id = "failed-1",
                                    title = "A failed book",
                                    maskedRecipient = "f***@example.test",
                                    status = QueueStatus.Failed,
                                    createdAtLabel = "Yesterday",
                                ),
                                KindleTask(
                                    id = "completed-1",
                                    title = "A completed book",
                                    maskedRecipient = "c***@example.test",
                                    status = QueueStatus.Completed,
                                    createdAtLabel = "Yesterday",
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
        val tabRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab)
        val tabs = compose.onAllNodes(tabRole, useUnmergedTree = true)
        tabs.assertCountEquals(3)
        val bounds = (0 until 3).map { tabs[it].getUnclippedBoundsInRoot() }
        val firstWidth = bounds.first().right - bounds.first().left
        assertTrue("queue tabs must remain at least 48dp high", bounds.all { it.bottom - it.top >= 48.dp })
        assertTrue(
            "queue tabs must share one width",
            bounds.drop(1).all { abs((it.right - it.left).value - firstWidth.value) <= 1f },
        )
        tabs[0].assertIsSelected()
        compose.onNodeWithText("A queued book").assertIsDisplayed()
        compose.onNodeWithText("A running book").assertIsDisplayed()
        compose.onNodeWithText("A failed book").assertIsDisplayed()
        compose.onNodeWithText("A completed book").assertIsDisplayed()

        tabs[1].performClick().assertIsSelected()
        compose.onNodeWithText("A queued book").assertIsDisplayed()
        compose.onNodeWithText("A running book").assertIsDisplayed()
        compose.onNodeWithText("A failed book").assertDoesNotExist()
        compose.onNodeWithText("A completed book").assertDoesNotExist()

        tabs[2].performClick().assertIsSelected()
        compose.onNodeWithText("A queued book").assertDoesNotExist()
        compose.onNodeWithText("A running book").assertDoesNotExist()
        compose.onNodeWithText("A failed book").assertIsDisplayed()
        compose.onNodeWithText("A completed book").assertDoesNotExist()

        tabs[0].performClick().assertIsSelected()
        compose.onNodeWithText("A completed book").assertIsDisplayed()
    }

    @Test
    fun importTaskFilterUsesSharedTabsAndPreservesStatusGrouping() {
        compose.setContent {
            WarmPageTheme {
                ImportTasksScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = ImportTasksSnapshot(
                            queueHealthy = true,
                            runningCount = 2,
                            tasks = listOf(
                                ImportTask("queued-1", "queued.epub", "/queued.epub", createdAtLabel = "Today", status = QueueStatus.Queued),
                                ImportTask("running-1", "running.epub", "/running.epub", createdAtLabel = "Today", status = QueueStatus.Running),
                                ImportTask("failed-1", "failed.epub", "/failed.epub", createdAtLabel = "Yesterday", status = QueueStatus.Failed),
                                ImportTask("completed-1", "completed.epub", "/completed.epub", createdAtLabel = "Yesterday", status = QueueStatus.Completed),
                            ),
                        ),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    onNavigate = {},
                    onCommand = {},
                    onRetry = {},
                    onBack = {},
                )
            }
        }

        val tabRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab)
        val tabs = compose.onAllNodes(tabRole, useUnmergedTree = true)
        tabs.assertCountEquals(3)
        compose.onNodeWithText("queued.epub").assertIsDisplayed()
        compose.onNodeWithText("running.epub").assertIsDisplayed()
        compose.onNodeWithText("failed.epub").assertIsDisplayed()
        compose.onNodeWithText("completed.epub").assertIsDisplayed()

        tabs[1].performClick().assertIsSelected()
        compose.onNodeWithText("queued.epub").assertIsDisplayed()
        compose.onNodeWithText("running.epub").assertIsDisplayed()
        compose.onNodeWithText("failed.epub").assertDoesNotExist()
        compose.onNodeWithText("completed.epub").assertDoesNotExist()

        tabs[2].performClick().assertIsSelected()
        compose.onNodeWithText("queued.epub").assertDoesNotExist()
        compose.onNodeWithText("running.epub").assertDoesNotExist()
        compose.onNodeWithText("failed.epub").assertIsDisplayed()
        compose.onNodeWithText("completed.epub").assertDoesNotExist()
    }
}
