package com.ermao.library.features.reader.infrastructure

import android.content.Context
import androidx.core.content.edit
import com.ermao.library.shared.modules.reader.ReaderDeviceIdentity
import java.util.UUID

internal class AndroidReaderDeviceIdentity(context: Context) : ReaderDeviceIdentity {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    override fun stableDeviceId(): String {
        preferences.getString(DEVICE_ID_KEY, null)?.let { return it }
        val generated = UUID.randomUUID().toString()
        preferences.edit(commit = true) { putString(DEVICE_ID_KEY, generated) }
        check(preferences.getString(DEVICE_ID_KEY, null) == generated) {
            "Reader device identity could not be persisted"
        }
        return generated
    }

    private companion object {
        const val PREFERENCES_NAME = "reader-device-identity"
        const val DEVICE_ID_KEY = "installation-id"
    }
}
