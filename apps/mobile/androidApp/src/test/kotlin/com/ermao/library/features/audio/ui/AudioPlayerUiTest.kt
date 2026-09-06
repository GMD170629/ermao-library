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

    @Test
    fun chapterListProjectsOnlyExplicitChaptersAndKeepsTrackWithoutOneOut() {
        val tracks = listOf(
            AndroidAudioTrack(
                assetId = "asset-1",
                title = "Track one",
                sourceUri = "https://audio.test/one.mp3",
                durationMillis = 60_000,
                chapters = listOf(
                    AndroidAudioChapter(
                        id = "chapter-1",
                        title = "Chapter one",
                        startMillis = 0,
                        endMillis = 30_000,
                    ),
                    AndroidAudioChapter(
                        id = "chapter-2",
                        title = "Chapter two",
                        startMillis = 30_000,
                        endMillis = 60_000,
                    ),
                ),
            ),
            AndroidAudioTrack(
                assetId = "asset-2",
                title = "Track two without chapters",
                sourceUri = "https://audio.test/two.mp3",
                durationMillis = 60_000,
            ),
        )

        val entries = audioChapterEntries(tracks)

        assertEquals(listOf(1, 2), entries.map(AudioChapterEntry::index))
        assertEquals(listOf("chapter-1", "chapter-2"), entries.map(AudioChapterEntry::chapterId))
        assertEquals(listOf("asset-1", "asset-1"), entries.map(AudioChapterEntry::assetId))
        assertEquals(listOf(30_000L, 30_000L), entries.map(AudioChapterEntry::durationMillis))
    }

    @Test
    fun chapterListIsEmptyWhenAllTracksHaveNoExplicitChapters() {
        val tracks = listOf(
            AndroidAudioTrack(
                assetId = "asset-1",
                title = "Track one",
                sourceUri = "https://audio.test/one.mp3",
                durationMillis = 60_000,
            ),
            AndroidAudioTrack(
                assetId = "asset-2",
                title = "Track two",
                sourceUri = "https://audio.test/two.mp3",
                durationMillis = 60_000,
            ),
        )

        assertEquals(emptyList(), audioChapterEntries(tracks))
    }
}
