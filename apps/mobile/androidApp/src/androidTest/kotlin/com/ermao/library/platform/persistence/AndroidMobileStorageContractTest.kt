package com.ermao.library.platform.persistence

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidMobileStorageContractTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun initializationPreservesLegacyReaderFilesDatabaseAndPreferences() {
        val token = UUID.randomUUID().toString()
        val legacyDirectories = listOf(
            File(context.filesDir, "reader-progress"),
            File(context.filesDir, "reader-progress-v2"),
            File(context.filesDir, "reader-publications"),
            File(context.filesDir, "reader-publications-v1"),
            File(context.filesDir, "reader-publications-v2"),
            File(context.cacheDir, "reader/pdf-range-v1"),
            File(context.cacheDir, "reader/pdf-range-v2"),
            File(context.cacheDir, "reader/pdf-range-v3"),
        )
        val directoryStates = legacyDirectories.mapIndexed { index, directory ->
            val existedBefore = directory.exists()
            if (!existedBefore) check(directory.mkdirs() || directory.isDirectory)
            val marker = directory.takeIf { it.isDirectory }?.resolve(".contract-test-$token-$index")
            marker?.writeText("legacy-reader-data")
            LegacyDirectoryState(directory, existedBefore, marker)
        }

        val legacyDatabaseName = "reader-progress.db"
        val legacyDatabasePath = context.getDatabasePath(legacyDatabaseName)
        val databaseExistedBefore = legacyDatabasePath.exists()
        if (!databaseExistedBefore) {
            context.openOrCreateDatabase(legacyDatabaseName, Context.MODE_PRIVATE, null).close()
        }

        val legacyPreferences = listOf("reader_bookmarks_v1", "reader-navigation-v1").map { name ->
            val preferences = context.getSharedPreferences(name, Context.MODE_PRIVATE)
            val key = "contract-test-$token"
            val existedBefore = preferences.contains(key)
            val previousValue = preferences.getString(key, null)
            check(preferences.edit().putString(key, "legacy-reader-data").commit())
            LegacyPreferenceState(preferences, key, existedBefore, previousValue)
        }

        val contractPreferences = context.getSharedPreferences("mobile-storage-contract", Context.MODE_PRIVATE)
        val contractVersionExistedBefore = contractPreferences.contains("version")
        val contractVersionBefore = contractPreferences.getInt("version", 0)

        try {
            check(
                contractPreferences.edit()
                    .putInt("version", AndroidMobileStorageContract.CURRENT_VERSION - 1)
                    .commit(),
            )
            AndroidMobileStorageContract.initialize(context)

            directoryStates.forEach { state ->
                assertTrue("Legacy Reader path was removed: ${state.directory}", state.directory.exists())
                state.marker?.let { marker ->
                    assertTrue("Legacy Reader contents were removed: $marker", marker.exists())
                    assertEquals("legacy-reader-data", marker.readText())
                }
            }
            assertTrue("Legacy Reader database was removed", legacyDatabasePath.exists())
            legacyPreferences.forEach { state ->
                assertEquals("legacy-reader-data", state.preferences.getString(state.key, null))
            }
        } finally {
            directoryStates.forEach { state ->
                state.marker?.delete()
                if (!state.existedBefore && state.directory.isDirectory && state.directory.list()?.isEmpty() == true) {
                    state.directory.delete()
                }
            }
            if (!databaseExistedBefore) context.deleteDatabase(legacyDatabaseName)
            legacyPreferences.forEach { state ->
                val editor = state.preferences.edit()
                if (state.existedBefore) editor.putString(state.key, state.previousValue)
                else editor.remove(state.key)
                check(editor.commit())
            }
            val editor = contractPreferences.edit()
            if (contractVersionExistedBefore) editor.putInt("version", contractVersionBefore)
            else editor.remove("version")
            check(editor.commit())
        }
    }

    private data class LegacyDirectoryState(
        val directory: File,
        val existedBefore: Boolean,
        val marker: File?,
    )

    private data class LegacyPreferenceState(
        val preferences: android.content.SharedPreferences,
        val key: String,
        val existedBefore: Boolean,
        val previousValue: String?,
    )
}
