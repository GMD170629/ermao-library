package com.ermao.library.features.me

import com.ermao.library.features.me.model.SanitizedAvatarMimeType
import com.ermao.library.features.me.model.SanitizedAvatar
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.graphics.toPixelMap
import java.io.ByteArrayOutputStream
import android.graphics.Color
import android.graphics.Bitmap
import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.height
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.R
import com.ermao.library.features.me.model.AboutViewState
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.features.me.model.MeFailure
import com.ermao.library.features.me.model.MeOperation
import com.ermao.library.features.me.model.MeRootViewState
import com.ermao.library.features.me.model.ProfileEditorState
import com.ermao.library.features.me.model.SecurityEditorState
import com.ermao.library.features.me.ui.AboutScreen
import com.ermao.library.features.me.ui.LanguageScreen
import com.ermao.library.features.me.ui.MeRootScreen
import com.ermao.library.features.me.ui.ProfileScreen
import com.ermao.library.features.me.ui.SecurityScreen
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.ui.theme.WarmPageTheme
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MeSettingsScreensTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun rootMatchesSharedTabTitleAndIosSettingsCatalogWithoutDescriptions() {
        val opened = mutableStateOf<String?>(null)
        val restorationTester = StateRestorationTester(compose)
        restorationTester.setContent {
            WarmPageTheme {
                MeRootScreen(
                    state = MeRootViewState(
                        isLoading = false,
                        account = MeAccountViewState("user-1", "Reader", "reader@example.com", null),
                        locale = PersonalSettingsLocale.EnUs,
                        serverName = "Home Library",
                        serverBaseUrl = "https://books.example.com",
                    ),
                    onOpenProfile = { opened.value = "profile" },
                    onOpenSecurity = { opened.value = "security" },
                    onOpenLanguage = { opened.value = "language" },
                    onOpenAbout = { opened.value = "about" },
                    onOpenDownloads = { opened.value = "downloads" },
                    onRetry = {},
                    downloadStatus = "3",
                    appVersion = "1.2.3",
                    emailAndKindleConfigured = true,
                    failedKindleTaskCount = 2,
                    isAdmin = true,
                    canManageSystem = true,
                    onOpenUsers = { opened.value = "users" },
                    onOpenOpds = { opened.value = "opds" },
                    onOpenLogs = { opened.value = "logs" },
                )
            }
        }

        compose.onNodeWithTag("me-root").assertIsDisplayed()
        compose.onNodeWithTag("settings-page-scroll").assertIsDisplayed()
        val initialTitleHeight = compose.onNodeWithTag("warm-page-title")
            .getUnclippedBoundsInRoot().height
        compose.onNodeWithTag("settings-row-profile").assertIsDisplayed().assertHasClickAction().performClick()
        compose.runOnIdle { assertEquals("profile", opened.value) }

        listOf(
            "settings-row-security",
            "settings-row-downloads",
            "settings-row-email-kindle",
            "settings-row-kindle-queue",
            "settings-row-users",
            "settings-row-opds",
            "settings-row-logs",
            "settings-row-value-server",
            "settings-row-language",
            "settings-row-about",
        ).forEach { tag ->
            compose.onNodeWithTag(tag).performScrollTo().assertIsDisplayed()
        }
        val scrolledTitleHeight = compose.onNodeWithTag("warm-page-title")
            .getUnclippedBoundsInRoot().height
        assertTrue(
            "Me must use the same fixed root title treatment as the other primary tabs",
            abs(scrolledTitleHeight.value - initialTitleHeight.value) <= 0.5f,
        )
        listOf(
            "Avatar and display name",
            "头像与显示名称",
            "Login email, password, and sign out",
            "登录邮箱、密码与退出登录",
            "Manage books available on this device",
            "管理此设备上可用的图书",
        ).forEach { removedDescription -> compose.onAllNodesWithText(removedDescription).assertCountEquals(0) }
        restorationTester.emulateSavedInstanceStateRestore()
        val restoredTitleHeight = compose.onNodeWithTag("warm-page-title")
            .getUnclippedBoundsInRoot().height
        assertTrue(
            "Me root title height must stay stable after restoration",
            abs(restoredTitleHeight.value - initialTitleHeight.value) <= 0.5f,
        )
        compose.onNodeWithTag("settings-row-about").assertIsDisplayed()
    }

    @Test
    fun profileRendersOnlyResponseImageAndKeepsPhotoActionsAccessible() {
        fun png(color: Int): ByteArray {
            val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(color)
            return ByteArrayOutputStream().use { output ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)
                bitmap.recycle()
                output.toByteArray()
            }
        }
        val response = mutableStateOf<ByteArray?>(png(Color.RED))
        val editor = mutableStateOf(ProfileEditorState(
            displayName = "Reader", savedDisplayName = "Reader",
            pendingAvatar = SanitizedAvatar(png(Color.BLUE), SanitizedAvatarMimeType.Png),
        ))
        lateinit var context: Context
        compose.setContent {
            context = LocalContext.current
            WarmPageTheme {
                ProfileScreen(
                    state = editor.value,
                    account = MeAccountViewState("user-1", "Reader", "reader@example.com", "/api/auth/avatar"),
                    avatarBytes = response.value,
                    onBack = {}, onDisplayNameChanged = {}, onAvatarReady = {},
                    onSaveName = {}, onUploadAvatar = {}, onDeleteAvatar = {},
                )
            }
        }
        val avatar = compose.onNode(hasContentDescription(context.getString(R.string.me_avatar_content_description)))
        val pixels = avatar.assertIsDisplayed().captureToImage().toPixelMap()
        assertEquals(androidx.compose.ui.graphics.Color.Red, pixels[pixels.width / 2, pixels.height / 2])
        compose.onAllNodesWithText("R").assertCountEquals(0)
        val choose = context.getString(R.string.me_avatar_choose)
        compose.onAllNodesWithText(choose).assertCountEquals(0)
        compose.onNode(hasContentDescription(choose)).assertHasClickAction().assertIsEnabled()
        compose.runOnIdle { editor.value = editor.value.copy(isSaving = true) }
        compose.onNode(hasContentDescription(choose)).assertIsNotEnabled()
        compose.runOnIdle {
            response.value = null
            editor.value = editor.value.copy(isSaving = false)
        }
        avatar.assertDoesNotExist()
        compose.onAllNodesWithText("R").assertCountEquals(0)
    }

    @Test
    fun profileUsesIdentityHeaderAndExplicitSaveWithDirtyAndWorkingStates() {
        val editor = mutableStateOf(
            ProfileEditorState(
                displayName = "Reader",
                savedDisplayName = "Reader",
            ),
        )
        var saveCount = 0

        compose.setContent {
            WarmPageTheme {
                ProfileScreen(
                    state = editor.value,
                    account = MeAccountViewState("user-1", "Reader", "reader@example.com", "https://avatar.example/avatar"),
                    avatarBytes = null,
                    onBack = {},
                    onDisplayNameChanged = { editor.value = editor.value.copy(displayName = it) },
                    onAvatarReady = {},
                    onSaveName = { saveCount++ },
                    onUploadAvatar = {},
                    onDeleteAvatar = {},
                )
            }
        }

        compose.onNodeWithTag("settings-identity").assertIsDisplayed()
        compose.onNodeWithTag("settings-field-display-name").assertIsDisplayed()
        compose.onNodeWithTag("settings-save").assertIsNotEnabled()

        compose.onNodeWithTag("settings-field-display-name").performTextInput(" updated")
        compose.waitForIdle()
        compose.onNodeWithTag("settings-save").assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, saveCount) }

        compose.runOnIdle { editor.value = editor.value.copy(isSaving = true) }
        compose.waitForIdle()
        compose.onNodeWithTag("settings-save").assertIsNotEnabled()
        compose.onNodeWithTag("settings-field-display-name").assertIsNotEnabled()
    }

    @Test
    fun securityKeepsFixedEqualWidthTabsPasswordVisibilityAndDangerConfirmation() {
        val state = mutableStateOf(
            SecurityEditorState(
                email = "reader@example.com",
                savedEmail = "reader@example.com",
            ),
        )
        var logoutCount = 0
        lateinit var context: Context

        compose.setContent {
            context = LocalContext.current
            WarmPageTheme {
                SecurityScreen(
                    state = state.value,
                    serverName = "Home Library",
                    onBack = {},
                    onEmailChanged = { state.value = state.value.copy(email = it) },
                    onEmailCurrentPasswordChanged = { state.value = state.value.copy(emailCurrentPassword = it) },
                    onCurrentPasswordChanged = { state.value = state.value.copy(currentPassword = it) },
                    onNewPasswordChanged = { state.value = state.value.copy(newPassword = it) },
                    onPasswordConfirmationChanged = { state.value = state.value.copy(confirmPassword = it) },
                    onSaveEmail = {},
                    onSavePassword = {},
                    onLogout = { logoutCount++ },
                )
            }
        }

        compose.onNodeWithTag("me-security").assertIsDisplayed()
        val tabRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab)
        val tabs = compose.onAllNodes(tabRole, useUnmergedTree = true)
        tabs.assertCountEquals(2)
        val firstBounds = tabs[0].getUnclippedBoundsInRoot()
        val secondBounds = tabs[1].getUnclippedBoundsInRoot()
        assertTrue(
            "settings tabs must remain at least 48dp high",
            firstBounds.bottom - firstBounds.top >= 48.dp,
        )
        val firstWidth = firstBounds.right - firstBounds.left
        val secondWidth = secondBounds.right - secondBounds.left
        assertTrue("settings tabs must share one width", abs(firstWidth.value - secondWidth.value) <= 1f)

        tabs[1].performClick()
        compose.onNodeWithTag("settings-field-current-password").assertIsDisplayed()
        val showPassword = context.getString(R.string.login_show_password)
        val hidePassword = context.getString(R.string.login_hide_password)
        val currentPasswordIcon = hasContentDescription(showPassword) and
            hasAnyAncestor(hasTestTag("settings-field-current-password"))
        compose.onNode(currentPasswordIcon, useUnmergedTree = true).assertIsDisplayed().performClick()
        compose.onNode(
            hasContentDescription(hidePassword) and
                hasAnyAncestor(hasTestTag("settings-field-current-password")),
            useUnmergedTree = true,
        ).assertIsDisplayed()

        compose.onNodeWithTag("settings-danger-logout").assertIsDisplayed().assertHasClickAction().performClick()
        compose.onNodeWithText(context.getString(R.string.logout_confirm_title)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.logout_confirm_action)).performClick()
        compose.runOnIdle { assertEquals(1, logoutCount) }
    }

    @Test
    fun languageUsesImmediateSegmentedSelectionWithoutSaveAction() {
        val selected = mutableStateOf(PersonalSettingsLocale.EnUs)
        lateinit var context: Context

        compose.setContent {
            context = LocalContext.current
            WarmPageTheme {
                LanguageScreen(
                    selected = selected.value,
                    onBack = {},
                    onSelect = { selected.value = it },
                )
            }
        }

        compose.onNodeWithTag("me-language").assertIsDisplayed()
        compose.onNodeWithTag("settings-language-segmented").assertIsDisplayed()
        compose.onAllNodesWithTag("settings-save").assertCountEquals(0)

        val radioRole = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton)
        compose.onAllNodes(
            radioRole and hasAnyAncestor(hasTestTag("settings-language-segmented")),
            useUnmergedTree = true,
        ).assertCountEquals(2)
        compose.onNodeWithText(context.getString(R.string.me_language_zh_cn)).performClick()
        compose.runOnIdle { assertEquals(PersonalSettingsLocale.ZhCn, selected.value) }
        compose.onNodeWithText(context.getString(R.string.me_language_zh_cn)).assertIsSelected()
    }

    @Test
    fun aboutExposesReadOnlyValuesAcrossLoadingAndErrorStates() {
        val state = mutableStateOf(AboutViewState(isLoading = true, appVersion = "1.2.3"))
        var retryCount = 0
        lateinit var context: Context

        compose.setContent {
            context = LocalContext.current
            WarmPageTheme {
                AboutScreen(
                    state = state.value,
                    onBack = {},
                    onRetry = { retryCount++ },
                )
            }
        }

        compose.onNodeWithTag("me-about").assertIsDisplayed()
        compose.onNodeWithTag("settings-row-value-app-version").assertIsDisplayed()
        compose.onNodeWithTag("settings-row-value-server-version").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.me_loading)).assertIsDisplayed()

        compose.runOnIdle {
            state.value = AboutViewState(
                isLoading = false,
                appVersion = "1.2.3",
                failure = MeFailure(MeOperation.LoadAbout, "ABOUT_UNAVAILABLE"),
            )
        }
        compose.waitForIdle()
        compose.onNodeWithTag("settings-error").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.retry_action)).performClick()
        compose.runOnIdle { assertTrue("About retry action must be wired", retryCount >= 2) }
    }
}
