package com.ermao.library.shared.modules.audio

import kotlin.test.Test
import kotlin.test.assertEquals

class AudioMiniPlayerPresentationPolicyTest {
    @Test
    fun pausedOrReadySessionDismissedFromNowPlayingHidesChrome() {
        listOf(AudioPlaybackStage.Paused, AudioPlaybackStage.Ready).forEach { stage ->
            assertEquals(
                AudioChromeState.Hidden,
                reduceAudioChromeState(
                    currentState = AudioChromeState.NowPlaying,
                    event = AudioChromeEvent.DismissNowPlaying,
                    hasSession = true,
                    playbackStage = stage,
                ),
            )
        }
    }

    @Test
    fun continuingPlaybackDismissedFromNowPlayingCreatesMiniPlayer() {
        listOf(AudioPlaybackStage.Playing, AudioPlaybackStage.Buffering).forEach { stage ->
            assertEquals(
                AudioChromeState.Mini,
                reduceAudioChromeState(
                    currentState = AudioChromeState.NowPlaying,
                    event = AudioChromeEvent.DismissNowPlaying,
                    hasSession = true,
                    playbackStage = stage,
                ),
            )
        }
    }

    @Test
    fun pausingAnExistingMiniPlayerKeepsItsResumeEntry() {
        assertEquals(
            AudioChromeState.Mini,
            reduceAudioChromeState(
                currentState = AudioChromeState.Mini,
                event = AudioChromeEvent.PauseFromMini,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Paused,
            ),
        )
    }

    @Test
    fun requestingNowPlayingProducesOneExclusiveSurface() {
        assertEquals(
            AudioChromeState.NowPlaying,
            reduceAudioChromeState(
                currentState = AudioChromeState.Mini,
                event = AudioChromeEvent.RequestNowPlaying,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Playing,
            ),
        )
        assertEquals(
            AudioChromeState.NowPlaying,
            reduceAudioChromeState(
                currentState = AudioChromeState.Hidden,
                event = AudioChromeEvent.RequestNowPlaying,
                hasSession = false,
                playbackStage = AudioPlaybackStage.Idle,
            ),
            "A launch request must present loading before the session bootstrap commits",
        )
        assertEquals(
            AudioChromeState.NowPlaying,
            reduceAudioChromeState(
                currentState = AudioChromeState.NowPlaying,
                event = AudioChromeEvent.PlaybackChanged,
                hasSession = false,
                playbackStage = AudioPlaybackStage.Preparing,
            ),
        )
    }

    @Test
    fun playbackOutsideNowPlayingRevealsMiniPlayer() {
        assertEquals(
            AudioChromeState.Mini,
            reduceAudioChromeState(
                currentState = AudioChromeState.Hidden,
                event = AudioChromeEvent.PlaybackChanged,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Playing,
            ),
        )
    }

    @Test
    fun firstLoadingSessionDoesNotCreateMiniPlayer() {
        assertEquals(
            AudioChromeState.Hidden,
            reduceAudioChromeState(
                currentState = AudioChromeState.Hidden,
                event = AudioChromeEvent.PlaybackChanged,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Preparing,
            ),
        )
        assertEquals(
            AudioChromeState.Hidden,
            reduceAudioChromeState(
                currentState = AudioChromeState.NowPlaying,
                event = AudioChromeEvent.DismissNowPlaying,
                hasSession = false,
                playbackStage = AudioPlaybackStage.Preparing,
            ),
            "Dismissing loading must not be mistaken for a runtime progress update",
        )
    }

    @Test
    fun endedAndRecoverableErrorsKeepRecoveryEntry() {
        assertEquals(
            AudioChromeState.Mini,
            reduceAudioChromeState(
                currentState = AudioChromeState.Hidden,
                event = AudioChromeEvent.PlaybackChanged,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Ended,
            ),
        )
        assertEquals(
            AudioChromeState.Mini,
            reduceAudioChromeState(
                currentState = AudioChromeState.Hidden,
                event = AudioChromeEvent.PlaybackChanged,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Error,
                hasRecoverableError = true,
            ),
        )
    }

    @Test
    fun terminalErrorAndRetiredSessionHideChrome() {
        assertEquals(
            AudioChromeState.Hidden,
            reduceAudioChromeState(
                currentState = AudioChromeState.Mini,
                event = AudioChromeEvent.PlaybackChanged,
                hasSession = true,
                playbackStage = AudioPlaybackStage.Error,
                hasRecoverableError = false,
            ),
        )
        assertEquals(
            AudioChromeState.Hidden,
            reduceAudioChromeState(
                currentState = AudioChromeState.NowPlaying,
                event = AudioChromeEvent.SessionRetired,
                hasSession = false,
                playbackStage = AudioPlaybackStage.Idle,
            ),
        )
    }
}
