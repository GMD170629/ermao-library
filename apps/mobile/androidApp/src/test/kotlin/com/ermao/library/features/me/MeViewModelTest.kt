package com.ermao.library.features.me

import com.ermao.library.features.me.application.MeViewModel
import com.ermao.library.features.me.application.SettingsClient
import com.ermao.library.features.me.application.SettingsSideEffects
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.shared.modules.personalsettings.PersonalAccount
import com.ermao.library.shared.modules.personalsettings.PersonalAvatar
import com.ermao.library.shared.modules.personalsettings.PersonalPasswordChange
import com.ermao.library.shared.modules.personalsettings.PersonalPreferences
import com.ermao.library.shared.modules.personalsettings.PersonalServerAbout
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsResult
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsContent
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsSnapshot
import com.ermao.library.features.me.model.SanitizedAvatar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MeViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun passwordChangePurgesBeforeApiAndLogsOutAfterSuccess() = runTest(dispatcher) {
        val events = mutableListOf<String>()
        val client = FakeSettingsClient(events)
        val viewModel = viewModel(client, RecordingSideEffects(events))
        advanceUntilIdle()

        viewModel.updateSecurityCurrentPassword("old-password")
        viewModel.updateNewPassword("new-password")
        viewModel.updatePasswordConfirmation("new-password")
        viewModel.savePassword()
        advanceUntilIdle()

        assertEquals(listOf("load", "load-avatar", "purge", "password-api", "password-logout"), events)
    }

    @Test
    fun purgeFailurePreventsPasswordApiAndSuccess() = runTest(dispatcher) {
        val events = mutableListOf<String>()
        val client = FakeSettingsClient(events)
        val viewModel = viewModel(client, RecordingSideEffects(events, failPurge = true))
        advanceUntilIdle()

        viewModel.updateSecurityCurrentPassword("old-password")
        viewModel.updateNewPassword("new-password")
        viewModel.updatePasswordConfirmation("new-password")
        viewModel.savePassword()
        advanceUntilIdle()

        assertEquals(listOf("load", "load-avatar", "purge"), events)
        assertEquals("LOCAL_PURGE_FAILED", viewModel.securityState.value.failure?.code)
        assertFalse(viewModel.securityState.value.isSaving)
    }

    @Test
    fun emailChangeLivesInSecurityAndRefreshesSession() = runTest(dispatcher) {
        val events = mutableListOf<String>()
        val client = FakeSettingsClient(events)
        val viewModel = viewModel(client, RecordingSideEffects(events))
        advanceUntilIdle()

        viewModel.updateEmail("new@example.com")
        viewModel.updateEmailCurrentPassword("current-password")
        viewModel.saveEmail()
        advanceUntilIdle()

        assertEquals("new@example.com", viewModel.securityState.value.email)
        assertEquals(listOf("load", "load-avatar", "email-api", "refresh"), events)
    }

    private fun viewModel(client: SettingsClient, sideEffects: SettingsSideEffects) = MeViewModel(
        client = client,
        sideEffects = sideEffects,
        serverName = "Home Library",
        serverBaseUrl = "https://books.example.com",
        appVersion = "1.0.0",
        initialAccount = ACCOUNT.toViewState(),
        initialLocale = PersonalSettingsLocale.EnUs,
    )

    private class FakeSettingsClient(
        private val events: MutableList<String>,
    ) : SettingsClient {
        override suspend fun load(): PersonalSettingsResult<PersonalSettingsSnapshot> {
            events += "load"
            return PersonalSettingsContent(PersonalSettingsSnapshot(ACCOUNT, PersonalPreferences(PersonalSettingsLocale.EnUs)))
        }

        override suspend fun loadAvatar(avatarUrl: String, etag: String?): PersonalSettingsResult<PersonalAvatar> {
            events += "load-avatar"
            return PersonalSettingsContent(PersonalAvatar(byteArrayOf(), null, null, false))
        }

        override suspend fun updateName(name: String) = PersonalSettingsContent(ACCOUNT.copy(displayName = name))

        override suspend fun updateEmail(email: String, currentPassword: String): PersonalSettingsResult<PersonalAccount> {
            events += "email-api"
            return PersonalSettingsContent(ACCOUNT.copy(email = email))
        }

        override suspend fun updatePassword(
            currentPassword: String,
            newPassword: String,
        ): PersonalSettingsResult<PersonalPasswordChange> {
            events += "password-api"
            return PersonalSettingsContent(PersonalPasswordChange(requiresLogin = true))
        }

        override suspend fun uploadAvatar(avatar: SanitizedAvatar) = PersonalSettingsContent(ACCOUNT)
        override suspend fun deleteAvatar() = PersonalSettingsContent(ACCOUNT.copy(avatarUrl = null))
        override suspend fun updateLocale(locale: PersonalSettingsLocale) =
            PersonalSettingsContent(PersonalPreferences(locale))
        override suspend fun loadServerAbout() =
            PersonalSettingsContent(PersonalServerAbout("server-1", "1.0.0"))
    }

    private class RecordingSideEffects(
        private val events: MutableList<String>,
        private val failPurge: Boolean = false,
    ) : SettingsSideEffects {
        override suspend fun refreshSession() {
            events += "refresh"
        }

        override suspend fun purgeCurrentNamespace() {
            events += "purge"
            if (failPurge) error("purge failed")
        }

        override suspend fun logoutAfterPasswordChange() {
            events += "password-logout"
        }

        override suspend fun logout() {
            events += "logout"
        }

        override fun requireReauthentication() {
            events += "reauth"
        }
    }

    private companion object {
        val ACCOUNT = PersonalAccount("user-1", "reader@example.com", "Reader", "/api/auth/avatar")
    }
}

private fun PersonalAccount.toViewState() = MeAccountViewState(id, displayName, email, avatarUrl)
