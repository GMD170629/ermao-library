package com.ermao.library.shared.modules.tts.domain

import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/**
 * A TTS attachment to an already open Reader Publication, never a second content source.
 * [readerSessionId] identifies that Publication's lifetime, including a reopen of the same resource.
 * The native adapter must resolve it to the existing Reader session in this exact namespace.
 */
data class TtsSession(
    val readerSessionId: String,
    val namespace: ReaderSyncNamespace,
    val bookId: String,
    val resourceId: String,
) {
    init {
        require(readerSessionId.isNotBlank()) { "TTS Reader session id is blank" }
        require(bookId.isNotBlank()) { "TTS book id is blank" }
        require(resourceId.isNotBlank()) { "TTS resource id is blank" }
    }
}

enum class TtsPlaybackState {
    Idle,
    Ready,
    Starting,
    Playing,
    Paused,
    Stopped,
    Completed,
    Failed,
    Disposed,
}

/** A stable adapter error code, never synthesized speech, a Locator payload or a localized message. */
data class TtsFailure(val code: String) {
    init {
        require(code.isNotBlank()) { "TTS failure code is blank" }
    }
}

/**
 * Transient TTS facts only. Reader remains the owner of durable position and reading status.
 * [locator] is the unchanged Reader start Locator or the latest real, accepted engine Locator.
 * Completed means the engine reached the end of its playback; it does not mark the book as read.
 */
data class TtsState(
    val playbackState: TtsPlaybackState = TtsPlaybackState.Idle,
    val session: TtsSession? = null,
    val locator: ReaderOpaqueLocator? = null,
    val failure: TtsFailure? = null,
) {
    init {
        val detached = playbackState == TtsPlaybackState.Idle || playbackState == TtsPlaybackState.Disposed
        require(detached == (session == null)) { "Only detached TTS states have no session" }
        require(detached == (locator == null)) { "Attached TTS states require a Reader Locator" }
        require((playbackState == TtsPlaybackState.Failed) == (failure != null)) {
            "Only failed TTS state carries a failure"
        }
    }
}
