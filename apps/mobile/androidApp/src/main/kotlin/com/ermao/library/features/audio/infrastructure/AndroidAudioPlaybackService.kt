package com.ermao.library.features.audio.infrastructure

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.ermao.library.MainActivity
import com.ermao.library.R
import com.ermao.library.ErmaoLibraryApplication

/**
 * The sole process-wide Media3 player owner. UI surfaces only connect through MediaController.
 * Media3 owns audio focus, noisy-route handling, notification lifecycle and system transport
 * controls; KMP owns the application playback contract and progress synchronization.
 */
class AndroidAudioPlaybackService : MediaSessionService() {
    private var player: ExoPlayer? = null
    private var mediaSession: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        val app = applicationContext as ErmaoLibraryApplication
        val dataSourceFactory = LocalOrAuthenticatedAudioDataSourceFactory(
            context = this,
            provider = app.audioTransportProvider,
        )
        val audioAttributes = AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
            .build()
        val exoPlayer = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSourceFactory))
            .setHandleAudioBecomingNoisy(true)
            .build()
            .also {
                // Media3's public audio-focus implementation handles transient loss and route
                // changes without a second app-owned focus state machine.
                it.setAudioAttributes(audioAttributes, true)
                it.repeatMode = Player.REPEAT_MODE_OFF
            }
        player = exoPlayer
        mediaSession = MediaSession.Builder(this, exoPlayer)
            .setSessionActivity(mainActivityPendingIntent())
            .build()
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider.Builder(this)
                .setChannelName(R.string.audio_notification_channel_name)
                .build(),
        )
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

    override fun onTaskRemoved(rootIntent: Intent?) {
        // A service-backed player is intentionally retained while playing. The system media
        // controls remain authoritative; app-owned Stop is the only action that clears a queue.
        if (player?.isPlaying != true) stopSelf()
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        mediaSession?.release()
        mediaSession = null
        player?.release()
        player = null
        super.onDestroy()
    }

    private fun mainActivityPendingIntent(): PendingIntent = PendingIntent.getActivity(
        this,
        NOTIFICATION_REQUEST_CODE,
        Intent(this, MainActivity::class.java).apply {
            action = MainActivity.ACTION_OPEN_AUDIO_PLAYER
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        },
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    private companion object {
        const val NOTIFICATION_REQUEST_CODE = 70_415
    }
}
