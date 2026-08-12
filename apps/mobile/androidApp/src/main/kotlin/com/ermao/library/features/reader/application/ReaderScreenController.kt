package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import kotlinx.coroutines.flow.StateFlow

internal interface ReaderScreenController {
    val currentLocation: StateFlow<ReaderLocation?>
    val preferences: StateFlow<ReaderPreferences>
    val restoreWarning: StateFlow<ReaderError?>
    val tableOfContents: List<ReaderTocEntry>

    fun goPrevious(): Boolean

    fun goNext(): Boolean

    fun goTo(location: ReaderLocation): Boolean

    fun goToTotalProgression(totalProgression: Double): Boolean

    fun updatePreferences(updated: ReaderPreferences)

    suspend fun flush()

    suspend fun close()
}
