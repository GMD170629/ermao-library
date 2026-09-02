package com.ermao.library.features.audio.ui

import com.ermao.library.features.audio.model.AndroidAudioChapter
import com.ermao.library.features.audio.model.AndroidAudioTrack
import kotlin.test.assertEquals
import org.junit.Test

class AudioPlayerUiTest {
    @Test
    fun queueProjectsExactlyOneIndexedRowPerTrack() {
        val tracks = listOf(
            AndroidAudioTrack(
                assetId = "asset-1",
                title = "A deliberately long track title that the UI must ellipsize",
                sourceUri = "https://audio.test/one.mp3",
                durationMillis = 61_000,
                chapters = listOf(
                    AndroidAudioChapter(
                        id = "chapter-1",
                        title = "Nested chapter must not become a second queue row",
                        startMillis = 0,
                    ),
                ),
            ),
            AndroidAudioTrack(
                assetId = "asset-2",
                title = "Second track",
                sourceUri = "https://audio.test/two.mp3",
            ),
        )

        val entries = audioQueueEntries(tracks)

        assertEquals(listOf(1, 2), entries.map(AudioQueueEntry::index))
        assertEquals(listOf("asset-1", "asset-2"), entries.map(AudioQueueEntry::assetId))
        assertEquals(tracks.map(AndroidAudioTrack::title), entries.map(AudioQueueEntry::title))
        assertEquals(listOf(61_000L, 0L), entries.map(AudioQueueEntry::durationMillis))
    }
}
