package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderCommandCompleted
import com.ermao.library.shared.modules.reader.ReaderCommandRejected
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test

class ReaderPreferenceSubmissionTest {
    @Test
    fun submitsOnceAndDoesNotTurnSubmissionIntoNavigation() = runBlocking {
        val controller = RecordingController()
        val updated = controller.preferences.value.copy(epub = controller.preferences.value.epub.copy(fontSize = 24))
        assertSame(ReaderCommandCompleted, controller.applyPreferences(updated))
        assertEquals(listOf(updated), controller.submissions)
        assertEquals(updated, controller.preferences.value)
    }

    @Test
    fun saveAndEngineFailuresKeepCauseWithoutRollbackSubmission() = runBlocking {
        for (failure in listOf(ReaderPreferenceSaveFailure(), IllegalStateException("engine detail"))) {
            val controller = RecordingController(failure)
            val updated = controller.preferences.value.copy(epub = controller.preferences.value.epub.copy(fontSize = 24))
            val result = controller.applyPreferences(updated) as ReaderCommandRejected
            assertSame(failure, result.cause)
            assertEquals(if (failure is ReaderPreferenceSaveFailure) "READER_PREFERENCES_SAVE_FAILED" else "READER_PREFERENCES_ENGINE_FAILED", result.reasonCode)
            assertEquals(listOf(updated), controller.submissions)
        }
    }

    private class RecordingController(private val failure: RuntimeException? = null) : ReaderScreenController {
        val submissions = mutableListOf<ReaderPreferences>()
        override val morphology = ReaderMorphology.Reflowable
        override val capabilities = ReaderCapabilities.Epub
        override val currentLocation = MutableStateFlow<ReaderLocation?>(null)
        override val preferences = MutableStateFlow(ReaderPreferences())
        override val restoreWarning = MutableStateFlow<ReaderError?>(null)
        override val resumeNotice = MutableStateFlow<ReaderResumeNotice?>(null)
        override val resumeActionFailed = MutableStateFlow(false)
        override val bookmarks = MutableStateFlow<List<ReaderBookmark>>(emptyList())
        override val bookmarkSyncPending = MutableStateFlow(false)
        override val tableOfContents = emptyList<ReaderTocEntry>()
        override fun updatePreferences(updated: ReaderPreferences) {
            submissions += updated
            failure?.let { throw it }
            preferences.value = updated
        }
        override fun goPrevious(): Boolean = error("Settings must not navigate")
        override fun goNext(): Boolean = error("Settings must not navigate")
        override fun goTo(location: ReaderLocation): Boolean = error("Settings must not restore an anchor")
        override fun goToTotalProgression(totalProgression: Double): Boolean = error("Settings must not seek")
        override fun dismissResumeNotice() = Unit
        override fun returnToResumeNotice(): Boolean = error("Settings must not restore progress")
        override fun toggleCurrentBookmark(): ReaderBookmarkChange? = null
        override fun removeBookmark(id: String) = Unit
        override fun goToBookmark(id: String): Boolean = error("Settings must not open bookmarks")
        override suspend fun flush() = Unit
        override suspend fun close() = Unit
    }
}
