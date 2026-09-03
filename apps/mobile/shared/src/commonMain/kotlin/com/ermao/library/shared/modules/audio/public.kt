package com.ermao.library.shared.modules.audio

typealias AudioLaunchIntent = com.ermao.library.shared.modules.audio.domain.AudioLaunchIntent
typealias AudioAsset = com.ermao.library.shared.modules.audio.domain.AudioAsset
typealias AudioChapter = com.ermao.library.shared.modules.audio.domain.AudioChapter
typealias AudioResource = com.ermao.library.shared.modules.audio.domain.AudioResource
typealias AudioPublication = com.ermao.library.shared.modules.audio.domain.AudioPublication
typealias AudioPlaybackStage = com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage
typealias AudioSourcePreparationStage = com.ermao.library.shared.modules.audio.domain.AudioSourcePreparationStage
typealias AudioSeekStage = com.ermao.library.shared.modules.audio.domain.AudioSeekStage
typealias AudioSleepTimerMode = com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode
typealias AudioProgressSyncState = com.ermao.library.shared.modules.audio.domain.AudioProgressSyncState
typealias AudioPlaybackError = com.ermao.library.shared.modules.audio.domain.AudioPlaybackError
typealias AudioPlaybackSnapshot = com.ermao.library.shared.modules.audio.domain.AudioPlaybackSnapshot
typealias AudioBootstrapResult = com.ermao.library.shared.modules.audio.application.AudioBootstrapResult
typealias AudioBootstrapContent = com.ermao.library.shared.modules.audio.application.AudioBootstrapResult.Content
typealias AudioBootstrapFailure = com.ermao.library.shared.modules.audio.application.AudioBootstrapResult.Failure
typealias LoadAudioPublication = com.ermao.library.shared.modules.audio.application.LoadAudioPublication
typealias AudioProgressSaveReason = com.ermao.library.shared.modules.audio.application.AudioProgressSaveReason
typealias AudioProgressWriter = com.ermao.library.shared.modules.audio.application.AudioProgressWriter
typealias AudioProgressSession = com.ermao.library.shared.modules.audio.application.AudioProgressSession
typealias AudioPlaybackEffectType = com.ermao.library.shared.modules.audio.application.AudioPlaybackEffectType
typealias AudioPlaybackEffect = com.ermao.library.shared.modules.audio.application.AudioPlaybackEffect
typealias AudioPlaybackTransition = com.ermao.library.shared.modules.audio.application.AudioPlaybackTransition
typealias AudioChromeState = com.ermao.library.shared.modules.audio.application.AudioChromeState
typealias AudioChromeEvent = com.ermao.library.shared.modules.audio.application.AudioChromeEvent
typealias AudioLaunchRequest = com.ermao.library.shared.modules.audio.application.AudioLaunchRequest
typealias AudioPlaybackStateMachine = com.ermao.library.shared.modules.audio.application.AudioPlaybackStateMachine
typealias LocalAudioPublicationFactory =
    com.ermao.library.shared.modules.audio.application.LocalAudioPublicationFactory
typealias AudioMediaMetadata = com.ermao.library.shared.modules.audio.application.AudioMediaMetadata
typealias AudioMediaFailure = com.ermao.library.shared.modules.audio.application.AudioMediaFailure
typealias AudioMediaProbeResult = com.ermao.library.shared.modules.audio.application.AudioMediaProbeResult
typealias AudioMediaAvailable = com.ermao.library.shared.modules.audio.application.AudioMediaProbeResult.Available
typealias AudioMediaProbeFailure = com.ermao.library.shared.modules.audio.application.AudioMediaProbeResult.Failure
typealias AudioMediaStream = com.ermao.library.shared.modules.audio.application.AudioMediaStream
typealias AudioMediaOpenResult = com.ermao.library.shared.modules.audio.application.AudioMediaOpenResult
typealias AudioMediaContent = com.ermao.library.shared.modules.audio.application.AudioMediaOpenResult.Content
typealias AudioMediaOpenFailure = com.ermao.library.shared.modules.audio.application.AudioMediaOpenResult.Failure
typealias AudioMediaTransport = com.ermao.library.shared.modules.audio.application.AudioMediaTransport

fun reduceAudioChromeState(
    currentState: AudioChromeState,
    event: AudioChromeEvent,
    hasSession: Boolean,
    playbackStage: AudioPlaybackStage,
    hasRecoverableError: Boolean = false,
): AudioChromeState = com.ermao.library.shared.modules.audio.application.reduceAudioChromeState(
    currentState = currentState,
    event = event,
    hasSession = hasSession,
    playbackStage = playbackStage,
    hasRecoverableError = hasRecoverableError,
)
