package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage

/** The single visible audio surface owned by the application shell. */
enum class AudioChromeState {
    Hidden,
    Mini,
    NowPlaying,
}

/** User and runtime events that are allowed to change the shell audio surface. */
enum class AudioChromeEvent {
    RequestNowPlaying,
    DismissNowPlaying,
    PlaybackChanged,
    PauseFromMini,
    SessionRetired,
}

/**
 * Reduces shell presentation from explicit events instead of coordinating independent booleans.
 *
 * A paused session behaves differently depending on the event that produced it: dismissing
 * Now Playing hides the accessory, while pausing an already visible mini player keeps its resume
 * entry. This history cannot be derived from the playback snapshot alone.
 */
fun reduceAudioChromeState(
    currentState: AudioChromeState,
    event: AudioChromeEvent,
    hasSession: Boolean,
    playbackStage: AudioPlaybackStage,
    hasRecoverableError: Boolean = false,
): AudioChromeState {
    if (event == AudioChromeEvent.SessionRetired) {
        return AudioChromeState.Hidden
    }
    if (event == AudioChromeEvent.RequestNowPlaying) return AudioChromeState.NowPlaying
    if (
        event == AudioChromeEvent.PlaybackChanged &&
        currentState == AudioChromeState.NowPlaying &&
        playbackStage == AudioPlaybackStage.Preparing
    ) {
        return AudioChromeState.NowPlaying
    }
    if (!hasSession || playbackStage == AudioPlaybackStage.Idle) return AudioChromeState.Hidden

    return when (event) {
        AudioChromeEvent.RequestNowPlaying -> AudioChromeState.NowPlaying
        AudioChromeEvent.DismissNowPlaying -> collapsedState(
            playbackStage = playbackStage,
            hasRecoverableError = hasRecoverableError,
        )
        AudioChromeEvent.PauseFromMini -> if (currentState == AudioChromeState.Mini) {
            AudioChromeState.Mini
        } else {
            reducePlaybackChange(
                currentState = currentState,
                playbackStage = playbackStage,
                hasRecoverableError = hasRecoverableError,
            )
        }
        AudioChromeEvent.PlaybackChanged -> reducePlaybackChange(
            currentState = currentState,
            playbackStage = playbackStage,
            hasRecoverableError = hasRecoverableError,
        )
        AudioChromeEvent.SessionRetired -> AudioChromeState.Hidden
    }
}

private fun collapsedState(
    playbackStage: AudioPlaybackStage,
    hasRecoverableError: Boolean,
): AudioChromeState = when (playbackStage) {
    AudioPlaybackStage.Playing,
    AudioPlaybackStage.Buffering,
    AudioPlaybackStage.Ended,
    -> AudioChromeState.Mini
    AudioPlaybackStage.Error -> if (hasRecoverableError) AudioChromeState.Mini else AudioChromeState.Hidden
    AudioPlaybackStage.Idle,
    AudioPlaybackStage.Preparing,
    AudioPlaybackStage.Ready,
    AudioPlaybackStage.Paused,
    -> AudioChromeState.Hidden
}

private fun reducePlaybackChange(
    currentState: AudioChromeState,
    playbackStage: AudioPlaybackStage,
    hasRecoverableError: Boolean,
): AudioChromeState {
    if (currentState == AudioChromeState.NowPlaying) return AudioChromeState.NowPlaying
    if (playbackStage == AudioPlaybackStage.Error && !hasRecoverableError) return AudioChromeState.Hidden
    if (currentState == AudioChromeState.Mini) return AudioChromeState.Mini
    return collapsedState(
        playbackStage = playbackStage,
        hasRecoverableError = hasRecoverableError,
    )
}
