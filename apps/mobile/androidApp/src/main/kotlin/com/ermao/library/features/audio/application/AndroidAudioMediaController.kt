package com.ermao.library.features.audio.application

import androidx.annotation.OptIn as AndroidXOptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController

/**
 * The small Media3 surface the audio runtime actually needs.
 *
 * Keeping this port next to the runtime makes the state-machine tests exercise the real runtime
 * transaction without constructing an Android service or a MediaController connection. Media3
 * remains an infrastructure detail of [Media3AudioMediaController].
 */
internal interface AndroidAudioMediaController {
    val isPlaying: Boolean
    val currentMediaItemIndex: Int
    val currentMediaItemId: String?
    val currentPosition: Long
    val duration: Long
    val bufferedPosition: Long
    val playbackState: Int
    val playbackRate: Float

    fun addListener(listener: Listener)

    fun play()

    fun pause()

    fun stop()

    fun clearMediaItems()

    fun setMediaItems(mediaItems: List<MediaItem>, startIndex: Int, startPositionMillis: Long)

    fun setPlaybackRate(rate: Float)

    fun prepare()

    fun seekTo(positionMillis: Long)

    fun seekTo(mediaItemIndex: Int, positionMillis: Long)

    fun hasPreviousMediaItem(): Boolean

    fun hasNextMediaItem(): Boolean

    fun release()

    interface Listener {
        fun onPlaybackStateChanged(playbackState: Int)

        fun onIsPlayingChanged(isPlaying: Boolean)

        fun onMediaItemTransition(mediaItemId: String?, reason: Int)

        fun onPositionDiscontinuity(newPosition: Position, reason: Int)

        fun onPlaybackRateChanged(rate: Float)

        fun onPlayerError(code: String)
    }

    data class Position(
        val mediaItemIndex: Int,
        val positionMillis: Long,
    )
}

/** Media3 adapter; no business or seek-transaction behavior belongs here. */
@AndroidXOptIn(markerClass = [UnstableApi::class])
internal class Media3AudioMediaController(
    private val delegate: MediaController,
) : AndroidAudioMediaController {
    override val isPlaying: Boolean
        get() = delegate.isPlaying

    override val currentMediaItemIndex: Int
        get() = delegate.currentMediaItemIndex

    override val currentMediaItemId: String?
        get() = delegate.currentMediaItem?.mediaId

    override val currentPosition: Long
        get() = delegate.currentPosition

    override val duration: Long
        get() = delegate.duration

    override val bufferedPosition: Long
        get() = delegate.bufferedPosition

    override val playbackState: Int
        get() = delegate.playbackState

    override val playbackRate: Float
        get() = delegate.playbackParameters.speed

    override fun addListener(listener: AndroidAudioMediaController.Listener) {
        delegate.addListener(
            object : Player.Listener {
                override fun onPlaybackStateChanged(playbackState: Int) {
                    listener.onPlaybackStateChanged(playbackState)
                }

                override fun onIsPlayingChanged(isPlaying: Boolean) {
                    listener.onIsPlayingChanged(isPlaying)
                }

                override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                    listener.onMediaItemTransition(mediaItem?.mediaId, reason)
                }

                override fun onPositionDiscontinuity(
                    oldPosition: Player.PositionInfo,
                    newPosition: Player.PositionInfo,
                    reason: Int,
                ) {
                    listener.onPositionDiscontinuity(
                        AndroidAudioMediaController.Position(
                            mediaItemIndex = newPosition.mediaItemIndex,
                            positionMillis = newPosition.positionMs,
                        ),
                        reason,
                    )
                }

                override fun onPlaybackParametersChanged(playbackParameters: PlaybackParameters) {
                    listener.onPlaybackRateChanged(playbackParameters.speed)
                }

                override fun onPlayerError(error: PlaybackException) {
                    listener.onPlayerError(stableErrorCode(error))
                }
            },
        )
    }

    override fun play() {
        delegate.play()
    }

    override fun pause() {
        delegate.pause()
    }

    override fun stop() {
        delegate.stop()
    }

    override fun clearMediaItems() {
        delegate.clearMediaItems()
    }

    override fun setMediaItems(
        mediaItems: List<MediaItem>,
        startIndex: Int,
        startPositionMillis: Long,
    ) {
        delegate.setMediaItems(mediaItems, startIndex, startPositionMillis)
    }

    override fun setPlaybackRate(rate: Float) {
        delegate.setPlaybackParameters(PlaybackParameters(rate))
    }

    override fun prepare() {
        delegate.prepare()
    }

    override fun seekTo(positionMillis: Long) {
        delegate.seekTo(positionMillis)
    }

    override fun seekTo(mediaItemIndex: Int, positionMillis: Long) {
        delegate.seekTo(mediaItemIndex, positionMillis)
    }

    override fun hasPreviousMediaItem(): Boolean = delegate.hasPreviousMediaItem()

    override fun hasNextMediaItem(): Boolean = delegate.hasNextMediaItem()

    override fun release() {
        delegate.release()
    }
}
