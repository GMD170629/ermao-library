package com.ermao.library.platform.persistence

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class SavedLoginCredential(val email: String, val password: String)

interface LoginCredentialStore {
    fun load(profileId: String): SavedLoginCredential?
    fun save(profileId: String, credential: SavedLoginCredential)
    fun remove(profileId: String)
}

object NoOpLoginCredentialStore : LoginCredentialStore {
    override fun load(profileId: String): SavedLoginCredential? = null
    override fun save(profileId: String, credential: SavedLoginCredential) = Unit
    override fun remove(profileId: String) = Unit
}

/** Keeps successful-login credentials encrypted with an app-scoped Android Keystore key. */
class AndroidLoginCredentialStore(context: Context) : LoginCredentialStore {
    private val preferences = context.applicationContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    override fun load(profileId: String): SavedLoginCredential? = runCatching {
        val encoded = preferences.getString(key(profileId), null) ?: return null
        val payload = Base64.decode(encoded, Base64.NO_WRAP)
        require(payload.size > IV_BYTES)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, encryptionKey(), GCMParameterSpec(TAG_BITS, payload, 0, IV_BYTES))
        val plaintext = ByteBuffer.wrap(cipher.doFinal(payload, IV_BYTES, payload.size - IV_BYTES))
        val emailSize = plaintext.int
        require(emailSize in 0..plaintext.remaining())
        val email = ByteArray(emailSize).also(plaintext::get).toString(StandardCharsets.UTF_8)
        val password = ByteArray(plaintext.remaining()).also(plaintext::get).toString(StandardCharsets.UTF_8)
        SavedLoginCredential(email, password)
    }.getOrNull()

    override fun save(profileId: String, credential: SavedLoginCredential) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, encryptionKey())
        val email = credential.email.toByteArray(StandardCharsets.UTF_8)
        val password = credential.password.toByteArray(StandardCharsets.UTF_8)
        val plaintext = ByteBuffer.allocate(Int.SIZE_BYTES + email.size + password.size)
            .putInt(email.size)
            .put(email)
            .put(password)
            .array()
        val encrypted = cipher.doFinal(plaintext)
        val payload = cipher.iv + encrypted
        preferences.edit(commit = true) {
            putString(key(profileId), Base64.encodeToString(payload, Base64.NO_WRAP))
        }
    }

    override fun remove(profileId: String) {
        preferences.edit(commit = true) {
            remove(key(profileId))
        }
    }

    private fun encryptionKey(): SecretKey = synchronized(KEY_LOCK) {
        val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey) ?: KeyGenerator
            .getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEY_STORE)
            .apply {
                init(
                    KeyGenParameterSpec.Builder(
                        KEY_ALIAS,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                    )
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .build(),
                )
            }
            .generateKey()
    }

    private fun key(profileId: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(profileId.toByteArray(StandardCharsets.UTF_8))
        return "login_${Base64.encodeToString(digest, Base64.NO_WRAP or Base64.URL_SAFE)}"
    }

    private companion object {
        const val PREFERENCES = "login_credentials"
        const val ANDROID_KEY_STORE = "AndroidKeyStore"
        const val KEY_ALIAS = "ermao_library_login_credentials_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
        val KEY_LOCK = Any()
    }
}
