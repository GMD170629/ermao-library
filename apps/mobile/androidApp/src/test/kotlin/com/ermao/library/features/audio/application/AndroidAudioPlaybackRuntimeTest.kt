package com.ermao.library.features.audio.application

import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import com.ermao.library.features.audio.model.AndroidAudioChapter
import com.ermao.library.features.audio.model.AndroidAudioLaunchIntent
import com.ermao.library.features.audio.model.AndroidAudioNamespace
import com.ermao.library.features.audio.model.AndroidAudioPhase
import com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot
import com.ermao.library.features.audio.model.AndroidAudioTrack
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.assertEquals
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AndroidAudioPlaybackRuntimeTest {
    @Test
    fun playingScrubPausesOnceAndKeepsPreviewUntilEngineConfirms() = runTest {
        val controller = FakeMediaController(initialPositionMillis = 1_000, startsPlaying = true)
        val progress = RecordingProgressSink()
        val runtime = newRuntime(controller, progress)
        try {
            val playCountBeforeScrub = controller.playCount
            runtime.beginScrubbing()
            runtime.updateScrubbing(10_000)
            assertEquals(AndroidAudioPhase.Paused, runtime.snapshot.value.phase)
            assertEquals(10_000, runtime.snapshot.value.positionMillis)
            assertEquals(1, controller.pauseCount)

            controller.emitPosition(1_500)
            assertEquals(10_000, runtime.snapshot.value.positionMillis)

            runtime.finishScrubbing()
            assertEquals(AndroidAudioPhase.Loading, runtime.snapshot.value.phase)
            assertEquals(listOf(10_000L), controller.seekPositions)
            assertEquals(1, controller.pauseCount)

            controller.emitPosition(1_750)
            assertEquals(10_000, runtime.snapshot.value.positionMillis)
            controller.emitSeekConfirmation(10_000)

            assertEquals(AndroidAudioPhase.Playing, runtime.snapshot.value.phase)
            assertEquals(10_000, runtime.snapshot.value.positionMillis)
            assertEquals(playCountBeforeScrub + 1, controller.playCount)
            assertEquals(10_000, progress.captures.single().positionMillis)

            controller.currentPosition = 10_750
            advanceTimeBy(AndroidAudioPlaybackRuntime.POSITION_REFRESH_INTERVAL_MILLIS + 1)
            runCurrent()
            assertEquals(10_750, runtime.snapshot.value.positionMillis)
        } finally {
            runtime.close()
        }
    }

    @Test
    fun pausedScrubDoesNotAutoplayAfterEngineConfirms() = runTest {
        val controller = FakeMediaController(initialPositionMillis = 1_000, startsPlaying = false)
        val runtime = newRuntime(controller)
        try {
            runtime.beginScrubbing()
            runtime.updateScrubbing(20_000)
            runtime.finishScrubbing()
            assertEquals(AndroidAudioPhase.Loading, runtime.snapshot.value.phase)

            controller.emitSeekConfirmation(20_000)

            assertEquals(AndroidAudioPhase.Paused, runtime.snapshot.value.phase)
            assertEquals(20_000, runtime.snapshot.value.positionMillis)
            assertEquals(0, controller.playCount)
        } finally {
            runtime.close()
        }
    }

    private fun TestScope.newRuntime(
        controller: FakeMediaController,
        progress: RecordingProgressSink = RecordingProgressSink(),
    ): AndroidAudioPlaybackRuntime = AndroidAudioPlaybackRuntime(
        controller = controller,
        scope = CoroutineScope(SupervisorJob() + StandardTestDispatcher(testScheduler)),
        progressSink = progress,
    ).also {
        it.launch(testIntent(autoplay = controller.startsPlaying))
    }

    private fun testIntent(autoplay: Boolean): AndroidAudioLaunchIntent = AndroidAudioLaunchIntent(
        namespace = AndroidAudioNamespace("https://audio.test", "user", 1),
        bookId = "book",
        resourceId = "resource",
        title = "Test audiobook",
        tracks = listOf(
            AndroidAudioTrack(
                assetId = "track-1",
                title = "Track 1",
                sourceUri = "https://audio.test/track-1.mp3",
                mimeType = "audio/mpeg",
                durationMillis = 60_000,
                chapters = listOf(
                    AndroidAudioChapter("chapter-1", "Chapter 1", 0),
                    AndroidAudioChapter("chapter-2", "Chapter 2", 30_000),
                ),
            ),
        ),
        assetId = "track-1",
        positionMillis = 1_000,
        autoplay = autoplay,
    )

    private class RecordingProgressSink : AndroidAudioProgressSink {
        val captures = mutableListOf<AndroidAudioPlaybackSnapshot>()

        override fun capture(snapshot: AndroidAudioPlaybackSnapshot, immediate: Boolean) {
            captures += snapshot
        }
    }

    private class FakeMediaController(
        initialPositionMillis: Long,
        val startsPlaying: Boolean,
    ) : AndroidAudioMediaController {
        override var isPlaying: Boolean = startsPlaying
        override var currentMediaItemIndex: Int = 0
        override var currentMediaItemId: String? = null
        override var currentPosition: Long = initialPositionMillis
        override var duration: Long = 60_000
        override var bufferedPosition: Long = duration
        override var playbackState: Int = Player.STATE_READY
        private var observedPlaybackRate: Float = 1f
        override val playbackRate: Float
            get() = observedPlaybackRate

        var playCount: Int = 0
            private set
        var pauseCount: Int = 0
            private set
        val seekPositions = mutableListOf<Long>()
        private val listeners = mutableListOf<AndroidAudioMediaController.Listener>()

        override fun addListener(listener: AndroidAudioMediaController.Listener) {
            listeners += listener
        }

        override fun play() {
            playCount += 1
            emitTransportState(playing = true)
        }

        override fun pause() {
            pauseCount += 1
            emitTransportState(playing = false)
        }

        override fun stop() {
            isPlaying = false
        }

        override fun clearMediaItems() {
            currentMediaItemId = null
        }

        override fun setMediaItems(
            mediaItems: List<MediaItem>,
            startIndex: Int,
            startPositionMillis: Long,
        ) {
            currentMediaItemIndex = startIndex
            currentMediaItemId = mediaItems[startIndex].mediaId
            currentPosition = startPositionMillis
            playbackState = Player.STATE_READY
        }

        override fun setPlaybackRate(rate: Float) {
            observedPlaybackRate = rate
        }

        override fun prepare() {
            playbackState = Player.STATE_READY
        }

        override fun seekTo(positionMillis: Long) {
            seekPositions += positionMillis
        }

        override fun seekTo(mediaItemIndex: Int, positionMillis: Long) {
            currentMediaItemIndex = mediaItemIndex
            seekPositions += positionMillis
        }

        override fun hasPreviousMediaItem(): Boolean = currentMediaItemIndex > 0

        override fun hasNextMediaItem(): Boolean = false

        override fun release() = Unit

        fun emitPosition(positionMillis: Long) {
            listeners.forEach { listener ->
                listener.onPositionDiscontinuity(
                    AndroidAudioMediaController.Position(currentMediaItemIndex, positionMillis),
                    Player.DISCONTINUITY_REASON_SEEK,
                )
            }
        }

        fun emitSeekConfirmation(positionMillis: Long) {
            playbackState = Player.STATE_BUFFERING
            currentPosition = positionMillis
            emitPosition(positionMillis)
            playbackState = Player.STATE_READY
            listeners.forEach { listener -> listener.onPlaybackStateChanged(playbackState) }
        }

        fun emitTransportState(playing: Boolean) {
            isPlaying = playing
            listeners.forEach { listener -> listener.onIsPlayingChanged(playing) }
        }

    }
}
