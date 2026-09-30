package com.ermao.library.shared.modules.tts

typealias TtsSession = com.ermao.library.shared.modules.tts.domain.TtsSession
typealias TtsState = com.ermao.library.shared.modules.tts.domain.TtsState
typealias TtsPlaybackState = com.ermao.library.shared.modules.tts.domain.TtsPlaybackState
typealias TtsFailure = com.ermao.library.shared.modules.tts.domain.TtsFailure
typealias TtsSessionController = com.ermao.library.shared.modules.tts.application.TtsSessionController
typealias TtsPlaybackToken = com.ermao.library.shared.modules.tts.application.TtsPlaybackToken
typealias TtsTransition = com.ermao.library.shared.modules.tts.application.TtsTransition
typealias TtsEffect = com.ermao.library.shared.modules.tts.application.TtsEffect
typealias TtsStart = com.ermao.library.shared.modules.tts.application.TtsEffect.Start
typealias TtsResume = com.ermao.library.shared.modules.tts.application.TtsEffect.Resume
typealias TtsPause = com.ermao.library.shared.modules.tts.application.TtsEffect.Pause
typealias TtsStop = com.ermao.library.shared.modules.tts.application.TtsEffect.Stop
