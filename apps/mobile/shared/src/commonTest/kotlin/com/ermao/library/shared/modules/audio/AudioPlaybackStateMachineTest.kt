package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.modules.audio.application.AudioPlaybackStateMachine
import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.domain.AudioChapter
import com.ermao.library.shared.modules.audio.domain.AudioLaunchIntent
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackError
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioResource
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AudioPlaybackStateMachineTest {
    @Test
    fun resourceSwitchKeepsCommittedSessionUntilNewLaunchCommits() {
        val state = AudioPlaybackStateMachine()
        val first = state.beginLaunch(namespace(), AudioLaunchIntent("resource-1", autoplay = true))
        assertTrue(state.commitLaunch(first.token, publication("resource-1", "asset-1")))
        assertEquals(AudioPlaybackStage.Playing, state.snapshot().stage)

        val replacement = state.beginLaunch(namespace(), AudioLaunchIntent("resource-2", autoplay = true))
        assertEquals("resource-1", state.snapshot().publication?.resource?.resourceId)
        assertTrue(state.failLaunch(replacement.token, AudioPlaybackError("NETWORK_UNAVAILABLE", true)))
        assertEquals("resource-1", state.snapshot().publication?.resource?.resourceId)
        assertEquals(AudioPlaybackStage.Playing, state.snapshot().stage)
    }

    @Test
    fun staleCallbacksCannotOverwriteReplacementOrRetiredNamespace() {
        val state = AudioPlaybackStateMachine()
        val first = state.beginLaunch(namespace(), AudioLaunchIntent("resource-1", autoplay = true))
        state.commitLaunch(first.token, publication("resource-1", "asset-1"))
        val second = state.beginLaunch(namespace(), AudioLaunchIntent("resource-2", autoplay = false))
        state.commitLaunch(second.token, publication("resource-2", "asset-2"))

        assertFalse(state.pause(first.token))
        assertEquals(AudioPlaybackStage.Ready, state.snapshot().stage)
        state.retireSession()
        assertFalse(state.play(second.token))
        assertEquals(AudioPlaybackStage.Idle, state.snapshot().stage)
    }

    @Test
    fun chapterSelectionSeekAndPlaybackRateHaveOneCanonicalState() {
        val state = AudioPlaybackStateMachine()
        val launch = state.beginLaunch(
            namespace(),
            AudioLaunchIntent("resource-1", chapterId = "chapter-2", autoplay = false),
        )
        state.commitLaunch(launch.token, publication("resource-1", "asset-1"))

        assertEquals(30_000, state.snapshot().positionMillis)
        assertEquals("chapter-2", state.snapshot().currentChapterId)
        assertTrue(state.seekBy(launch.token, -15_000))
        assertEquals(15_000, state.snapshot().positionMillis)
        assertTrue(state.setPlaybackRate(2.5))
        assertEquals(2.5, state.snapshot().playbackRate)
    }

    private fun publication(resourceId: String, assetId: String) = AudioPublication(
        namespace = namespace(),
        bookId = "book-1",
        bookTitle = "Book",
        author = "Author",
        coverApiPath = "/api/books/book-1/cover",
        resource = AudioResource(resourceId, "Volume", ReaderSourceFormat.M4b, 0, 60_000, 1, 2),
        availableResources = emptyList(),
        assets = listOf(
            AudioAsset(
                assetId, resourceId, "Track", "/api/assets/$assetId", "audio/mp4", 1_000,
                60_000, 1, 1, 0, "aac",
            ),
        ),
        chapters = listOf(
            AudioChapter("chapter-1", assetId, 0, "One", 0, 30_000),
            AudioChapter("chapter-2", assetId, 1, "Two", 30_000, 60_000),
        ),
    )

    private fun namespace() = ReaderSyncNamespace("server-1", "user-1", 2)
}
