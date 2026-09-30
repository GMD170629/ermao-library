package com.ermao.library.shared.modules.tts.application

import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.tts.domain.TtsFailure
import com.ermao.library.shared.modules.tts.domain.TtsPlaybackState
import com.ermao.library.shared.modules.tts.domain.TtsSession
import com.ermao.library.shared.modules.tts.domain.TtsState

/**
 * In-memory callback identity. Retain this exact object with the engine operation; do not reconstruct
 * it from a resource id or look up the current token when a delayed callback is delivered.
 */
class TtsPlaybackToken internal constructor(val session: TtsSession)

/** Native instructions, executed in order on the same serialized owner as the controller. */
sealed interface TtsEffect {
    val token: TtsPlaybackToken

    /** Borrow the existing Publication and start system TTS at the engine-owned Locator. */
    data class Start(
        override val token: TtsPlaybackToken,
        val locator: ReaderOpaqueLocator,
    ) : TtsEffect

    /** Continue the paused native engine, binding subsequent events to the new [token]. */
    data class Resume(
        override val token: TtsPlaybackToken,
        val pausedToken: TtsPlaybackToken,
    ) : TtsEffect

    data class Pause(override val token: TtsPlaybackToken) : TtsEffect

    /**
     * Cancel pending setup/speech and release TTS resources; never close the borrowed Publication.
     * This is a request, not proof of physical cleanup. The adapter must retain actual stop/release
     * failure diagnostics and must not present the core's Stopped/Disposed state as cleanup success.
     */
    data class Stop(override val token: TtsPlaybackToken) : TtsEffect
}

data class TtsTransition(
    val state: TtsState,
    val effects: List<TtsEffect> = emptyList(),
)

/**
 * The shared, synchronous TTS session owner. Platform adapters serialize commands and engine facts
 * (for example on their main actor/thread), and execute returned effects before the next command.
 * They must cancel pending setup on Stop, including releasing an engine whose setup finishes late.
 * This controller owns no coroutine, SDK, text cache, audio-file state or progress writer.
 */
class TtsSessionController {
    private var state = TtsState()
    private var activeToken: TtsPlaybackToken? = null
    private var pausedToken: TtsPlaybackToken? = null

    fun snapshot(): TtsState = state

    /** Attaching/restoring/switching Reader sessions never starts speech, including the same book. */
    fun open(session: TtsSession, locator: ReaderOpaqueLocator): TtsTransition {
        if (isDisposed()) return transition()
        val stops = releasePlayback()
        state = TtsState(TtsPlaybackState.Ready, session, locator)
        return transition(stops)
    }

    /** Only an explicit user play/resume/retry command may call this method. */
    fun play(): TtsTransition {
        if (isDisposed() || activeToken != null) return transition()
        val session = state.session ?: return transition()
        val locator = state.locator ?: return transition()
        val previous = pausedToken
        val token = TtsPlaybackToken(session)
        activeToken = token
        pausedToken = null
        state = state.copy(playbackState = TtsPlaybackState.Starting, failure = null)
        val effect = if (previous == null) TtsEffect.Start(token, locator) else TtsEffect.Resume(token, previous)
        return transition(listOf(effect))
    }

    fun pause(): TtsTransition {
        val token = activeToken ?: return transition()
        activeToken = null
        // A not-yet-started engine cannot be resumed. Cancel setup and require a fresh explicit play.
        val effect = if (state.playbackState == TtsPlaybackState.Starting) {
            TtsEffect.Stop(token)
        } else {
            pausedToken = token
            TtsEffect.Pause(token)
        }
        state = state.copy(playbackState = TtsPlaybackState.Paused)
        return transition(listOf(effect))
    }

    /** Also cancels a pending start. Its callbacks are invalid before the native Stop is executed. */
    fun stop(): TtsTransition {
        if (isDisposed() || state.session == null) return transition()
        val stops = releasePlayback()
        state = state.copy(playbackState = TtsPlaybackState.Stopped, failure = null)
        return transition(stops)
    }

    /** Terminal owner teardown; late callbacks and later commands cannot recreate the session. */
    fun dispose(): TtsTransition {
        if (isDisposed()) return transition()
        val stops = releasePlayback()
        state = TtsState(playbackState = TtsPlaybackState.Disposed)
        return transition(stops)
    }

    fun engineStarted(token: TtsPlaybackToken): TtsTransition {
        if (!accepts(token) || state.playbackState != TtsPlaybackState.Starting) return transition()
        state = state.copy(playbackState = TtsPlaybackState.Playing)
        return transition()
    }

    /** Carries the full opaque Locator unchanged. Persisting or following it belongs to Reader. */
    fun enginePositionChanged(token: TtsPlaybackToken, locator: ReaderOpaqueLocator): TtsTransition {
        if (!accepts(token) || state.playbackState != TtsPlaybackState.Playing) return transition()
        state = state.copy(locator = locator)
        return transition()
    }

    /** Only natural whole-playback completion, never utterance end, cancellation or failure. */
    fun engineCompleted(token: TtsPlaybackToken): TtsTransition {
        if (!accepts(token) || state.playbackState != TtsPlaybackState.Playing) return transition()
        val stops = releasePlayback()
        state = state.copy(playbackState = TtsPlaybackState.Completed)
        return transition(stops)
    }

    fun engineFailed(token: TtsPlaybackToken, failure: TtsFailure): TtsTransition {
        if (!accepts(token)) return transition()
        val stops = releasePlayback()
        state = state.copy(playbackState = TtsPlaybackState.Failed, failure = failure)
        return transition(stops)
    }

    /**
     * Failure to execute the matching Pause effect, not a delayed engine failure callback. A failed
     * pause may leave speech running, so fail the session and request Stop for that retained engine.
     * Ordinary asynchronous engine failures still use engineFailed and cannot revive a paused run.
     */
    fun pauseFailed(token: TtsPlaybackToken, failure: TtsFailure): TtsTransition {
        if (pausedToken !== token || state.playbackState != TtsPlaybackState.Paused) return transition()
        val stops = releasePlayback()
        state = state.copy(playbackState = TtsPlaybackState.Failed, failure = failure)
        return transition(stops)
    }

    private fun accepts(token: TtsPlaybackToken): Boolean = activeToken === token

    private fun isDisposed(): Boolean = state.playbackState == TtsPlaybackState.Disposed

    private fun releasePlayback(): List<TtsEffect> {
        val token = activeToken ?: pausedToken
        activeToken = null
        pausedToken = null
        return token?.let { listOf(TtsEffect.Stop(it)) } ?: emptyList()
    }

    private fun transition(effects: List<TtsEffect> = emptyList()): TtsTransition = TtsTransition(state, effects)
}
