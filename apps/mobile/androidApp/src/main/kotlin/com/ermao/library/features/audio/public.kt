package com.ermao.library.features.audio

/** Android feature boundary: callers do not depend on Media3 or authenticated transport types. */
typealias AudioPlaybackRuntime =
    com.ermao.library.features.audio.application.AndroidAudioPlaybackRuntime
typealias AudioPlaybackSnapshot =
    com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot
typealias AudioPlaybackPhase =
    com.ermao.library.features.audio.model.AndroidAudioPhase
typealias AudioNamespace =
    com.ermao.library.features.audio.model.AndroidAudioNamespace
