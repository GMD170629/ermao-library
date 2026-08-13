package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReaderBookmark
import kotlinx.coroutines.flow.StateFlow

internal data class ReaderResumeNotice(
    val capturedAtEpochMillis: Long,
    val percent: Double,
    val chapterLabel: String?,
)

internal interface ReaderScreenController {
    val capabilities: ReaderCapabilities
    val currentLocation: StateFlow<ReaderLocation?>
    val preferences: StateFlow<ReaderPreferences>
    val restoreWarning: StateFlow<ReaderError?>
    val resumeNotice: StateFlow<ReaderResumeNotice?>
    val resumeActionFailed: StateFlow<Boolean>
    val bookmarks: StateFlow<List<ReaderBookmark>>
    val bookmarkSyncPending: StateFlow<Boolean>
    val tableOfContents: List<ReaderTocEntry>

    fun goPrevious(): Boolean

    fun goNext(): Boolean

    fun goTo(location: ReaderLocation): Boolean

    fun goToTotalProgression(totalProgression: Double): Boolean

    fun dismissResumeNotice()

    fun returnToResumeNotice(): Boolean

    fun updatePreferences(updated: ReaderPreferences)

    fun toggleCurrentBookmark()

    fun removeBookmark(id: String)

    fun goToBookmark(id: String): Boolean

    suspend fun flush()

    suspend fun close()
}
