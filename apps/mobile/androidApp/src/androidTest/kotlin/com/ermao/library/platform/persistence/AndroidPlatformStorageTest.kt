package com.ermao.library.platform.persistence

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.edit
import com.ermao.library.shared.core.network.AndroidEncryptedCookieVault
import com.ermao.library.shared.core.network.PersistedCookie
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.auth.domain.VerifiedSessionRecord
import java.util.UUID
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidPlatformStorageTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun encryptedCookieVaultRoundTripsAndDoesNotStoreCleartext() = runBlocking {
        val profileId = "instrumented-${UUID.randomUUID()}"
        val vault = AndroidEncryptedCookieVault(context)
        val cookie = PersistedCookie(
            name = "shuku_session",
            value = "instrumented-secret-${UUID.randomUUID()}",
            encoding = "URI_ENCODING",
            receivedAtMillis = 1_000L,
            effectiveExpiresAtMillis = null,
            requestScheme = "https",
            requestHost = "books.example.com",
            domain = null,
            path = "/",
            secure = true,
            httpOnly = true,
            extensions = emptyMap(),
        )

        try {
            vault.mutate(profileId) { listOf(cookie) }

            assertEquals(listOf(cookie), vault.load(profileId))
            val storedValues = context
                .getSharedPreferences("ermao_session_cookies", 0)
                .all
                .values
                .joinToString()
            assertFalse(storedValues.contains(cookie.value))
        } finally {
            vault.clear(profileId)
        }
    }

    @Test
    fun loginCredentialStoreRoundTripsAndDoesNotStoreCleartext() {
        val profileId = "login-${UUID.randomUUID()}"
        val credential = SavedLoginCredential(
            email = "reader-${UUID.randomUUID()}@example.com",
            password = "password-${UUID.randomUUID()}",
        )
        val store = AndroidLoginCredentialStore(context)

        try {
            store.save(profileId, credential)

            assertEquals(credential, store.load(profileId))
            val storedValues = context.getSharedPreferences("login_credentials", 0).all.values.joinToString()
            assertFalse(storedValues.contains(credential.email))
            assertFalse(storedValues.contains(credential.password))
        } finally {
            store.remove(profileId)
        }
    }

    @Test
    fun serverProfileStoreRoundTripsActivationAndRemoval() = runBlocking {
        val store = AndroidServerProfileStore(context)
        val first = profile("first-${UUID.randomUUID()}", isActive = true)
        val second = profile("second-${UUID.randomUUID()}", isActive = false)

        try {
            store.upsert(first)
            store.upsert(second)
            assertEquals(first, store.activeProfile())

            store.activate(second.id)
            assertEquals(second.copy(isActive = true), store.activeProfile())
            assertEquals(
                listOf(first.id, second.id),
                store.profiles().map(ServerProfile::id).filter { it == first.id || it == second.id },
            )

            store.save(
                VerifiedSessionRecord(
                    profileId = second.id,
                    serverIdentity = second.serverIdentity,
                    userId = "user-test",
                    email = "reader@example.com",
                    displayName = "Reader",
                    authorizationVersion = 1,
                    isAdmin = false,
                    canManageSystem = false,
                    allLibraryScopes = true,
                    canViewManualImports = false,
                    monitorFolderIds = emptyList(),
                    lastValidatedAtEpochMillis = 1_000,
                    avatarUrl = null,
                    locale = "en-US",
                ),
            )
            store.remove(second.id)
            assertNull(store.profiles().firstOrNull { it.id == second.id })
            assertNull(store.load(second.id))
        } finally {
            store.remove(first.id)
            store.remove(second.id)
        }
    }

    @Test
    fun legacyProfilePayloadMigratesToV2WithoutChangingProfileId() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val file = File(context.cacheDir, "profiles-${UUID.randomUUID()}.preferences_pb")
        val dataStore = PreferenceDataStoreFactory.create(scope = scope, produceFile = { file })
        val legacy = AndroidStoredServerProfile(
            id = "legacy-${UUID.randomUUID()}",
            displayName = "Legacy Library",
            baseUrl = "https://books.example.com/base",
            serverIdentity = "server-legacy",
            isActive = true,
            tlsMode = StoredTlsMode.SystemTrust,
        )
        dataStore.edit { it[legacyProfilesPayloadKey] = Json.encodeToString(listOf(legacy)) }
        val store = AndroidServerProfileStore(context, dataStoreOverride = dataStore)

        try {
            assertEquals(legacy.id, store.activeProfile()?.id)
            val preferences = dataStore.data.first()
            assertNull(preferences[legacyProfilesPayloadKey])
            assertEquals(true, preferences[profilesV2PayloadKey]?.contains("\"schemaVersion\":2"))
            assertEquals(true, preferences[profilesV2PayloadKey]?.contains(legacy.id))
        } finally {
            scope.cancel()
            file.delete()
        }
    }

    private fun profile(id: String, isActive: Boolean): ServerProfile {
        val parsed = ServerBaseUrl.parse("https://books.example.com/library")
        check(parsed is ServerBaseUrlParseResult.Valid)
        return ServerProfile(
            id = id,
            displayName = "Instrumented Library",
            baseUrl = parsed.baseUrl,
            serverIdentity = "server-$id",
            isActive = isActive,
            tlsMode = TlsMode.SystemTrust,
        )
    }
}
