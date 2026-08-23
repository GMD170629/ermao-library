package com.ermao.library.platform.persistence

import android.content.Context
import androidx.core.content.edit
import java.io.File

/**
 * Owns destructive local storage boundaries for native mobile contracts.
 *
 * The Book/Resource/Asset cutover has no trustworthy Work/Version/Volume
 * mapping. On first launch of this contract, old private artifacts are
 * removed and the new stores start empty. Completed downloads remain a
 * first-class feature: they are stored below the v3 root after this boundary.
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
        val cacheDirectory = applicationContext.cacheDir
        val oldFiles = listOf(
            File(filesDirectory, "managed-downloads-v1"),
            File(filesDirectory, "managed-downloads-v2"),
            File(filesDirectory, "reader-progress"),
            File(filesDirectory, "reader-progress-v2"),
            File(filesDirectory, "reader-publications"),
            File(filesDirectory, "reader-publications-v1"),
            File(filesDirectory, "reader-publications-v2"),
        )
        val oldCaches = listOf(
            File(cacheDirectory, "reader/pdf-range-v1"),
            File(cacheDirectory, "reader/pdf-range-v2"),
        )

        // Keep the marker at the old version if cleanup cannot finish. This
        // makes the next process retry instead of silently retaining legacy
        // identity-bound data.
        runCatching {
            (oldFiles + oldCaches).forEach(::deleteRecursivelyIfPresent)
            applicationContext.deleteDatabase("reader-progress.db")
            applicationContext.deleteSharedPreferences("reader_bookmarks_v1")
            applicationContext.deleteSharedPreferences("reader-navigation-v1")
            preferences.edit { putInt(VERSION_KEY, CURRENT_VERSION) }
        }
    }

    private fun deleteRecursivelyIfPresent(file: File) {
        if (file.exists() && !file.deleteRecursively()) {
            error("Unable to clear legacy mobile storage: ${file.name}")
        }
    }
}
