package com.ermao.library.shared.core.network

import android.content.Context
import android.util.Base64
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import com.ermao.library.shared.core.storage.PlatformStorageException

class AndroidEncryptedCookieVault(
    context: Context,
) : CookieVault {
    private val preferences = context.applicationContext.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )
    private val mutex = Mutex()
    private val json = Json {
        ignoreUnknownKeys = false
        explicitNulls = false
    }

    override suspend fun load(profileId: String): List<PersistedCookie> = storageOperation("load") {
        mutex.withLock {
            val profileKey = profileKey(profileId)
            val encoded = preferences.getString(profileKey, null) ?: return@withLock emptyList()
            val clearText = decrypt(encoded, profileKey)
            json.decodeFromString(ListSerializer(PersistedCookie.serializer()), clearText)
        }
    }

    override suspend fun save(profileId: String, cookies: List<PersistedCookie>) {
        storageOperation("save") {
            mutex.withLock {
                val clearText = json.encodeToString(ListSerializer(PersistedCookie.serializer()), cookies)
                val profileKey = profileKey(profileId)
                check(preferences.edit().putString(profileKey, encrypt(clearText, profileKey)).commit()) {
                    "Unable to persist the cookie session"
                }
            }
        }
    }

    override suspend fun clear(profileId: String) {
        storageOperation("clear") {
            mutex.withLock {
                check(preferences.edit().remove(profileKey(profileId)).commit()) {
                    "Unable to clear the cookie session"
                }
            }
        }
    }

    private suspend fun <T> storageOperation(action: String, block: suspend () -> T): T = try {
        block()
    } catch (error: PlatformStorageException) {
        throw error
    } catch (error: Throwable) {
        throw PlatformStorageException("Unable to $action secure session cookies", error)
    }

    private fun encrypt(value: String, profileKey: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, encryptionKey())
        cipher.updateAAD(profileKey.toByteArray(StandardCharsets.UTF_8))
        val encrypted = cipher.doFinal(value.toByteArray(StandardCharsets.UTF_8))
        return listOf(cipher.iv, encrypted).joinToString(SEPARATOR) {
            Base64.encodeToString(it, Base64.NO_WRAP)
        }
    }

    private fun decrypt(value: String, profileKey: String): String {
        val parts = value.split(SEPARATOR, limit = 2)
        require(parts.size == 2) { "Invalid encrypted cookie payload" }
        val initializationVector = Base64.decode(parts[0], Base64.NO_WRAP)
        val encrypted = Base64.decode(parts[1], Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, encryptionKey(), GCMParameterSpec(GCM_TAG_BITS, initializationVector))
        cipher.updateAAD(profileKey.toByteArray(StandardCharsets.UTF_8))
        return String(cipher.doFinal(encrypted), StandardCharsets.UTF_8)
    }

    private fun encryptionKey(): SecretKey = synchronized(KEY_LOCK) {
        val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey) ?: run {
            val generator = KeyGenerator.getInstance("AES", ANDROID_KEY_STORE)
            generator.init(
                android.security.keystore.KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or
                        android.security.keystore.KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generator.generateKey()
        }
    }

    private fun profileKey(profileId: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(profileId.toByteArray(StandardCharsets.UTF_8))
        return "profile_" + Base64.encodeToString(digest, Base64.NO_WRAP or Base64.URL_SAFE)
    }

    private companion object {
        const val PREFERENCES_NAME = "ermao_session_cookies"
        const val ANDROID_KEY_STORE = "AndroidKeyStore"
        const val KEY_ALIAS = "com.ermao.library.session-cookie-key.v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val GCM_TAG_BITS = 128
        const val SEPARATOR = "."
        val KEY_LOCK = Any()
    }
}
