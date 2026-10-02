package com.ermao.library.features.reader.infrastructure

import android.app.Application
import com.ermao.library.shared.modules.tts.application.TtsEffect
import com.ermao.library.shared.modules.tts.application.TtsPlaybackToken
import com.ermao.library.shared.modules.tts.application.TtsSessionController
import com.ermao.library.shared.modules.tts.application.TtsTransition
import com.ermao.library.shared.modules.tts.domain.TtsFailure
import com.ermao.library.shared.modules.tts.domain.TtsPlaybackState
import com.ermao.library.shared.modules.tts.domain.TtsSession
import java.util.logging.Level
import java.util.logging.Logger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.readium.navigator.media.tts.TtsNavigator
import org.readium.navigator.media.tts.TtsNavigatorFactory
import org.readium.navigator.media.tts.android.AndroidTtsEngine
import org.readium.navigator.media.tts.android.AndroidTtsPreferences
import org.readium.navigator.media.tts.android.AndroidTtsSettings
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.util.getOrElse

/** Foreground-only owner. Borrows Reader's Publication; never navigates or writes Reader progress. */
@OptIn(ExperimentalReadiumApi::class)
internal class AndroidReaderTts(
    private val application: Application,
    private val publication: Publication,
    private val session: TtsSession,
) {
    private val core = TtsSessionController()
    private val mapper = ReadiumLocatorMapper()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val mutableState = MutableStateFlow(core.snapshot())
    val state = mutableState.asStateFlow()
    private var token: TtsPlaybackToken? = null
    private var navigator: TtsNavigator<AndroidTtsSettings, AndroidTtsPreferences, AndroidTtsEngine.Error, AndroidTtsEngine.Voice>? = null
    private var setup: Job? = null
    private var engineIdentity: Any? = null
    private var playbackObservation: Job? = null
    private var locatorObservation: Job? = null

    fun play(currentLocator: Locator) {
        if (state.value.playbackState == TtsPlaybackState.Disposed) return
        if (state.value.playbackState !in setOf(TtsPlaybackState.Paused, TtsPlaybackState.Starting, TtsPlaybackState.Playing)) {
            apply(core.open(session, mapper.opaqueLocator(currentLocator)))
        }
        apply(core.play())
    }

    fun pause() = apply(core.pause())

    fun stop() = apply(core.stop())

    fun dispose() {
        apply(core.dispose())
        scope.cancel()
    }

    private fun apply(transition: TtsTransition) {
        mutableState.value = transition.state
        transition.effects.forEach { effect ->
            when (effect) {
                is TtsEffect.Start -> start(effect)
                is TtsEffect.Resume -> {
                    token = effect.token
                    observe(effect.token)
                    navigator?.play()
                }
                is TtsEffect.Pause -> {
                    stopObserving()
                    try {
                        navigator?.pause()
                    } catch (error: Exception) {
                        LOGGER.log(Level.WARNING, "reader_tts_pause_failed", error)
                        apply(core.pauseFailed(effect.token, TtsFailure("TTS_ENGINE_FAILED")))
                    }
                }
                is TtsEffect.Stop -> releaseEngine()
            }
        }
    }

    private fun start(effect: TtsEffect.Start) {
        token = effect.token
        val identity = Any()
        engineIdentity = identity
        setup = scope.launch(start = CoroutineStart.UNDISPATCHED) {
            // Let SDK initialization return an owned navigator even if Stop invalidates the token.
            // The late result is closed before it can play; no automatic resume on lifecycle return.
            withContext(NonCancellable) {
                try {
                    val factory = TtsNavigatorFactory(application, publication)
                    if (factory == null) {
                        fail(effect.token, "TTS_CONTENT_UNAVAILABLE")
                        return@withContext
                    }
                    val initialLocator = Locator.fromJSON(JSONObject(effect.locator.canonicalJson))
                    val created = factory.createNavigator(
                        listener = object : TtsNavigator.Listener {
                            override fun onStopRequested() {
                                if (engineIdentity === identity) stop()
                            }
                        },
                        initialLocator = initialLocator,
                    ).getOrElse { error ->
                        LOGGER.warning("reader_tts_setup_failed kind=${error.javaClass.simpleName}")
                        fail(effect.token, if (error is TtsNavigatorFactory.Error.UnsupportedPublication) {
                            "TTS_CONTENT_UNAVAILABLE"
                        } else "TTS_ENGINE_UNAVAILABLE")
                        return@withContext
                    }
                    if (token !== effect.token) {
                        created.close()
                        return@withContext
                    }
                    navigator = created
                    observe(effect.token)
                    created.play()
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Exception) {
                    LOGGER.log(Level.WARNING, "reader_tts_setup_failed", error)
                    fail(effect.token, "TTS_ENGINE_FAILED")
                }
            }
        }
    }

    private fun observe(expected: TtsPlaybackToken) {
        stopObserving()
        val engine = navigator ?: return
        playbackObservation = scope.launch {
            engine.playback.collect { playback ->
                if (token !== expected) return@collect
                when (val nativeState = playback.state) {
                    is TtsNavigator.State.Failure -> {
                        LOGGER.warning("reader_tts_playback_failed kind=${nativeState.error.javaClass.simpleName}")
                        fail(expected, "TTS_ENGINE_FAILED")
                    }
                    TtsNavigator.State.Ended -> apply(core.engineCompleted(expected))
                    TtsNavigator.State.Ready -> {
                        if (playback.playWhenReady) apply(core.engineStarted(expected))
                        else if (state.value.playbackState == TtsPlaybackState.Playing) pause()
                    }
                    else -> Unit // MediaNavigator also permits a buffering state.
                }
            }
        }
        locatorObservation = scope.launch {
            engine.currentLocator.collect { locator ->
                if (token === expected) apply(core.enginePositionChanged(expected, mapper.opaqueLocator(locator)))
            }
        }
    }

    private fun fail(expected: TtsPlaybackToken, code: String) =
        apply(core.engineFailed(expected, TtsFailure(code)))

    private fun stopObserving() {
        playbackObservation?.cancel()
        locatorObservation?.cancel()
        playbackObservation = null
        locatorObservation = null
    }

    private fun releaseEngine() {
        token = null
        engineIdentity = null
        setup?.cancel()
        setup = null
        stopObserving()
        val engine = navigator
        navigator = null
        try {
            engine?.close()
        } catch (error: Exception) {
            LOGGER.log(Level.SEVERE, "reader_tts_release_failed", error)
        }
    }

    private companion object {
        val LOGGER: Logger = Logger.getLogger("MobileReader")
    }
}
