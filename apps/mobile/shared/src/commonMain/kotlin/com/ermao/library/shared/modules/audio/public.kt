package com.ermao.library.shared.modules.audio

typealias AudioPlaybackStage = com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage
typealias AudioSleepTimerMode = com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode
typealias AudioLaunchIntent = com.ermao.library.shared.modules.audio.domain.AudioLaunchIntent
typealias AudioAsset = com.ermao.library.shared.modules.audio.domain.AudioAsset
typealias AudioChapter = com.ermao.library.shared.modules.audio.domain.AudioChapter
typealias AudioResource = com.ermao.library.shared.modules.audio.domain.AudioResource
typealias AudioPublication = com.ermao.library.shared.modules.audio.domain.AudioPublication
typealias AudioPlaybackError = com.ermao.library.shared.modules.audio.domain.AudioPlaybackError
typealias AudioPlaybackSnapshot = com.ermao.library.shared.modules.audio.domain.AudioPlaybackSnapshot
typealias AudioLocalArtifactIdentity = com.ermao.library.shared.modules.audio.domain.AudioLocalArtifactIdentity
typealias AudioLocalArtifact = com.ermao.library.shared.modules.audio.domain.AudioLocalArtifact
typealias AudioLocalFallbackPolicy = com.ermao.library.shared.modules.audio.domain.AudioLocalFallbackPolicy
typealias AudioBootstrapResult = com.ermao.library.shared.modules.audio.application.AudioBootstrapResult
typealias AudioBootstrapContent = com.ermao.library.shared.modules.audio.application.AudioBootstrapResult.Content
typealias AudioBootstrapFailure = com.ermao.library.shared.modules.audio.application.AudioBootstrapResult.Failure
typealias LoadAudioPublication = com.ermao.library.shared.modules.audio.application.LoadAudioPublication
typealias AudioPendingLaunch = com.ermao.library.shared.modules.audio.application.AudioPendingLaunch
typealias AudioPlaybackStateMachine = com.ermao.library.shared.modules.audio.application.AudioPlaybackStateMachine
typealias AudioPlaybackRuntime = com.ermao.library.shared.modules.audio.application.AudioPlaybackRuntime
typealias AudioPlaybackSnapshotObserver =
    com.ermao.library.shared.modules.audio.application.AudioPlaybackSnapshotObserver
typealias AudioObservation = com.ermao.library.shared.modules.audio.application.AudioObservation
typealias AudioProgressSaveReason = com.ermao.library.shared.modules.audio.application.AudioProgressSaveReason
typealias AudioProgressWriter = com.ermao.library.shared.modules.audio.application.AudioProgressWriter
typealias AudioSleepTimerSnapshot = com.ermao.library.shared.modules.audio.application.AudioSleepTimerSnapshot
typealias AudioSleepTimer = com.ermao.library.shared.modules.audio.application.AudioSleepTimer
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

fun audioPlaybackRates(): List<Double> = com.ermao.library.shared.modules.audio.domain.AUDIO_PLAYBACK_RATES

fun createAudioLaunchIntent(
    resourceId: String,
    assetId: String?,
    chapterId: String?,
    positionMillis: Long?,
    autoplay: Boolean,
): AudioLaunchIntent = AudioLaunchIntent(resourceId, assetId, chapterId, positionMillis, autoplay)

fun createAudioPlaybackRuntime(initialPlaybackRate: Double = 1.0): AudioPlaybackRuntime =
    AudioPlaybackRuntime(initialPlaybackRate)
