package com.ermao.library.features.me

import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.R
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.features.me.model.MeRootViewState
import com.ermao.library.features.me.ui.MeRootScreen
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MeRootScreenTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun rendersP0RowsAndKeepsServerIdentityReadOnly() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        var openedProfile = false
        compose.setContent {
            WarmPageTheme {
                MeRootScreen(
                    state = MeRootViewState(
                        isLoading = false,
                        account = MeAccountViewState("user-1", "Reader", "reader@example.com", null),
                        locale = PersonalSettingsLocale.EnUs,
                        serverName = "Home Library",
                        serverBaseUrl = "https://books.example.com",
                    ),
                    onOpenProfile = { openedProfile = true },
                    onOpenSecurity = {},
                    onOpenLanguage = {},
                onOpenAbout = {},
                onOpenDownloads = {},
                    onRetry = {},
                )
            }
        }

        compose.onNodeWithText(context.getString(R.string.me_profile_title)).assertIsDisplayed().performClick()
        compose.onNodeWithText(context.getString(R.string.me_security_title)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.me_language_title)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.me_about_title)).assertIsDisplayed()
        compose.onNodeWithText("https://books.example.com").assert(
            SemanticsMatcher.keyNotDefined(SemanticsActions.OnClick),
        )
        assertTrue(openedProfile)
    }
}
