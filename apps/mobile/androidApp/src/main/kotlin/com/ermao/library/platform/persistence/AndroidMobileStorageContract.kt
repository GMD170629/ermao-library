package com.ermao.library.platform.persistence

import android.content.Context
import androidx.core.content.edit
import java.io.File

/**
 * Owns destructive local storage boundaries for native mobile contracts.
 *
 * The Book/Resource/Asset cutover has no trustworthy Work/Version/Volume
 * mapping. On first launch of this contract, only superseded download
 * artifacts are removed and the new stores start empty. Reader v5 owns a
 * separate namespace; legacy Reader databases, directories, caches, and
 * preferences are intentionally ignored and preserved.
 */
object AndroidMobileStorageContract {
    const val CURRENT_VERSION = 3

    private const val PREFERENCES = "mobile-storage-contract"
    private const val VERSION_KEY = "version"

    fun initialize(context: Context) {
        val applicationContext = context.applicationContext
        val preferences = applicationContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (preferences.getInt(VERSION_KEY, 0) >= CURRENT_VERSION) return

        val filesDirectory = applicationContext.filesDir
        val legacyDownloadFiles = listOf(
            File(filesDirectory, "managed-downloads-v1"),
            File(filesDirectory, "managed-downloads-v2"),
        )

        // Keep the marker at the old version if cleanup cannot finish. This
        // makes the next process retry the download cleanup. Reader legacy
        // data is deliberately not part of this operation.
        runCatching {
            legacyDownloadFiles.forEach(::deleteRecursivelyIfPresent)
            preferences.edit { putInt(VERSION_KEY, CURRENT_VERSION) }
        }
    }

    private fun deleteRecursivelyIfPresent(file: File) {
        if (file.exists() && !file.deleteRecursively()) {
            error("Unable to clear legacy download storage: ${file.name}")
        }
    }
}
