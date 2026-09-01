package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode

data class AudioSleepTimerSnapshot(
    val mode: AudioSleepTimerMode,
    val deadlineMonotonicMillis: Long? = null,
    val initialChapterId: String? = null,
    val initialAssetId: String? = null,
)

/** Session-only timer. It intentionally has no serializer or persistence port. */
class AudioSleepTimer(
    private val monotonicMillis: () -> Long,
) {
    private var state = AudioSleepTimerSnapshot(AudioSleepTimerMode.Off)

    fun snapshot(): AudioSleepTimerSnapshot = state

    fun set(mode: AudioSleepTimerMode, currentChapterId: String?, currentAssetId: String?) {
        val now = monotonicMillis()
        require(now >= 0)
        state = AudioSleepTimerSnapshot(
            mode = mode,
            deadlineMonotonicMillis = mode.minutesOrNull()?.let { minutes ->
                now + minutes * 60_000L
            },
            initialChapterId = currentChapterId,
            initialAssetId = currentAssetId,
        )
    }

    fun shouldPause(
        currentChapterId: String?,
        currentAssetId: String?,
        currentTrackEnded: Boolean,
    ): Boolean {
        val current = state
        val pause = when (current.mode) {
            AudioSleepTimerMode.Off -> false
            AudioSleepTimerMode.Minutes15,
            AudioSleepTimerMode.Minutes30,
            AudioSleepTimerMode.Minutes45,
            AudioSleepTimerMode.Minutes60,
            -> requireNotNull(current.deadlineMonotonicMillis) <= monotonicMillis()
            AudioSleepTimerMode.EndOfTrack -> currentTrackEnded ||
                current.initialAssetId != null && currentAssetId != current.initialAssetId
            AudioSleepTimerMode.EndOfChapter -> if (current.initialChapterId == null) {
                currentTrackEnded || current.initialAssetId != null && currentAssetId != current.initialAssetId
            } else {
                currentChapterId != current.initialChapterId
            }
        }
        if (pause) state = AudioSleepTimerSnapshot(AudioSleepTimerMode.Off)
        return pause
    }

    fun clear() {
        state = AudioSleepTimerSnapshot(AudioSleepTimerMode.Off)
    }
}

private fun AudioSleepTimerMode.minutesOrNull(): Long? = when (this) {
    AudioSleepTimerMode.Minutes15 -> 15
    AudioSleepTimerMode.Minutes30 -> 30
    AudioSleepTimerMode.Minutes45 -> 45
    AudioSleepTimerMode.Minutes60 -> 60
    else -> null
}
