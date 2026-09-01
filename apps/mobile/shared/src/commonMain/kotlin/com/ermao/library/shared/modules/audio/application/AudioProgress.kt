package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore

enum class AudioProgressSaveReason {
    Tick,
    Seek,
    Pause,
    ChapterChange,
    TrackChange,
    Stop,
    Background,
    Completed,
}

/** Applies the 15-second cadence while all durable writes still go through Reader v4 local-first storage. */
class AudioProgressWriter(
    private val store: ReaderProgressSyncingStore,
    private val resourceId: String,
    private val deviceId: String,
    private val nowEpochMillis: () -> Long,
) {
    private var lastTickSavedAtEpochMillis: Long? = null

    suspend fun save(
        assetId: String,
        chapterId: String?,
        positionMillis: Long,
        durationMillis: Long?,
        reason: AudioProgressSaveReason,
    ): Boolean {
        val now = nowEpochMillis()
        require(now >= 0 && positionMillis >= 0)
        if (reason == AudioProgressSaveReason.Tick &&
            lastTickSavedAtEpochMillis?.let { now - it < SAVE_INTERVAL_MILLIS } == true
        ) return false
        val percent = durationMillis?.takeIf { it > 0 }?.let { duration ->
            positionMillis.coerceAtMost(duration).toDouble() * 100.0 / duration.toDouble()
        }
        store.save(
            ReaderProgress(
                resourceId = resourceId,
                location = AudioReaderLocation(assetId, chapterId, positionMillis),
                updatedAtEpochMillis = now,
                deviceId = deviceId,
                percent = percent,
            ),
        )
        lastTickSavedAtEpochMillis = now
        return true
    }

    suspend fun restore(): AudioReaderLocation? =
        store.load(resourceId)?.location as? AudioReaderLocation
}

private const val SAVE_INTERVAL_MILLIS = 15_000L
