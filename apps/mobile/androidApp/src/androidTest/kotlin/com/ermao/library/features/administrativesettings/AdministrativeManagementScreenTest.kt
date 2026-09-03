package com.ermao.library.features.administrativesettings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AdministrativeManagementScreenTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun managementIndexShowsAuthorizedNativeRowsAndNavigatesWithTypedRoute() {
        var destination: AdministrativeSettingsRoute? = null
        val entryRoute = AdministrativeSettingsRoute.Users
        compose.setContent {
            WarmPageTheme {
                ManagementIndexScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = ManagementSnapshot(listOf(ManagementEntry(entryRoute, "2"))),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    capabilities = setOf(AdministrativeCapability.ViewAdministration, AdministrativeCapability.ManageUsers),
                    onNavigate = { destination = it },
                    onRetry = {},
                    onBack = {},
                )
            }
        }

        compose.onNodeWithText("Users and permissions").assertIsDisplayed().performClick()
        assertEquals(entryRoute, destination)
    }

    @Test
    fun managementIndexNeverShowsRetiredMobileRows() {
        compose.setContent {
            WarmPageTheme {
                ManagementIndexScreen(
                    state = AdministrativePageState(
                        phase = AdministrativePagePhase.Content,
                        snapshot = ManagementSnapshot(
                            listOf(
                                ManagementEntry(AdministrativeSettingsRoute.LibrarySources),
                                ManagementEntry(AdministrativeSettingsRoute.OrganizeQueue),
                                ManagementEntry(AdministrativeSettingsRoute.Backups),
                                ManagementEntry(AdministrativeSettingsRoute.Health()),
                            ),
                        ),
                        failure = null,
                        mutationInFlight = false,
                    ),
                    locale = AdministrativeLocale.EnUs,
                    capabilities = AdministrativeCapability.entries.toSet(),
                    onNavigate = {},
                    onRetry = {},
                    onBack = {},
                )
            }
        }

        compose.onNodeWithText("Library sources").assertDoesNotExist()
        compose.onNodeWithText("Smart organization").assertDoesNotExist()
        compose.onNodeWithText("Data and backups").assertDoesNotExist()
        compose.onNodeWithText("System health").assertDoesNotExist()
    }
}
