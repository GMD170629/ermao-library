package com.ermao.library.features.me

import android.content.Context
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.R
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.features.me.model.MeRootViewState
import com.ermao.library.features.me.ui.MeRootScreen
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.ui.theme.WarmPageTheme
import java.util.concurrent.atomic.AtomicReference
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
        val renderedContext = AtomicReference<Context>()
        var logoutCount = 0
        var openedProfile = false
        compose.setContent {
            renderedContext.set(LocalContext.current)
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
                    onLogout = { logoutCount++ },
                )
            }
        }

        compose.waitForIdle()
        val context = checkNotNull(renderedContext.get())
        compose.onNodeWithTag("settings-identity").assertIsDisplayed()
        compose.onNodeWithTag("settings-danger-logout").assertIsDisplayed().performClick()
        compose.onNodeWithText(context.getString(R.string.logout_confirm_title)).assertIsDisplayed()
        org.junit.Assert.assertEquals(0, logoutCount)
        compose.onNodeWithText(context.getString(R.string.cancel)).performClick()
        org.junit.Assert.assertEquals(0, logoutCount)
        compose.onNodeWithTag("settings-danger-logout").performClick()
        compose.onNode(hasText(context.getString(R.string.logout_confirm_action)) and hasAnyAncestor(isDialog())).performClick()
        org.junit.Assert.assertEquals(1, logoutCount)
        compose.onNodeWithText(context.getString(R.string.me_profile_title)).assertIsDisplayed().performClick()
        compose.onNodeWithText(context.getString(R.string.me_security_title)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.me_language_title)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.me_about_title)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("https://books.example.com").assert(
            SemanticsMatcher.keyNotDefined(SemanticsActions.OnClick),
        )
        assertTrue(openedProfile)
    }
}
