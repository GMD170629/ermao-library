package com.ermao.library.shared.modules.audio.domain

import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

val AUDIO_PLAYBACK_RATES: List<Double> = listOf(0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)

enum class AudioPlaybackStage {
    Idle,
    Preparing,
    Ready,
    Playing,
    Paused,
    Buffering,
    Ended,
    Error,
}

enum class AudioSourcePreparationStage {
    None,
    Preparing,
    EngineReady,
}

enum class AudioSeekStage {
    None,
    Scrubbing,
    WaitingForEngine,
}

enum class AudioSleepTimerMode {
    Off,
    Minutes15,
    Minutes30,
    Minutes45,
    Minutes60,
    EndOfChapter,
    EndOfTrack,
}

enum class AudioProgressSyncState {
    Synced,
    Pending,
    Failed,
}

data class AudioPlaybackError(
    val code: String,
    val recoverable: Boolean,
    val requiresReauthentication: Boolean = false,
) {
    init {
        require(code.isNotBlank())
        require(!requiresReauthentication || recoverable)
    }
}

data class AudioLaunchIntent(
    val resourceId: String,
    val assetId: String? = null,
    val chapterId: String? = null,
    val positionMillis: Long? = null,
    val autoplay: Boolean,
) {
    init {
        require(resourceId.isNotBlank())
        require(assetId == null || assetId.isNotBlank())
        require(chapterId == null || chapterId.isNotBlank())
        require(positionMillis == null || positionMillis >= 0)
    }
}

data class AudioAsset(
    val assetId: String,
    val resourceId: String,
    val title: String,
    val apiPath: String,
    val mimeType: String,
    val sizeBytes: Long,
    val durationMillis: Long?,
    val discNumber: Int?,
    val trackNumber: Int?,
    val sortOrder: Int,
    val codec: String?,
) {
    init {
        require(assetId.isNotBlank() && resourceId.isNotBlank() && title.isNotBlank())
        require(apiPath.startsWith("/api/") && '#' !in apiPath && '?' !in apiPath)
        require(mimeType.isNotBlank() && sizeBytes > 0)
        require(durationMillis == null || durationMillis >= 0)
        require(discNumber == null || discNumber >= 0)
        require(trackNumber == null || trackNumber >= 0)
        require(codec == null || codec.isNotBlank())
    }
}

data class AudioChapter(
    val chapterId: String,
    val assetId: String,
    val index: Int,
    val title: String,
    val startMillis: Long,
    val endMillis: Long?,
) {
    init {
        require(chapterId.isNotBlank() && assetId.isNotBlank() && title.isNotBlank())
        require(index >= 0 && startMillis >= 0)
        require(endMillis == null || endMillis >= startMillis)
    }
}

data class AudioResource(
    val resourceId: String,
    val title: String,
    val sourceFormat: ReaderSourceFormat,
    val sortOrder: Int,
    val durationMillis: Long?,
    val trackCount: Int?,
    val chapterCount: Int?,
) {
    init {
        require(resourceId.isNotBlank() && title.isNotBlank())
        require(sourceFormat.readerFormat.wireValue == "audio")
        require(durationMillis == null || durationMillis >= 0)
        require(trackCount == null || trackCount >= 0)
        require(chapterCount == null || chapterCount >= 0)
    }
}

data class AudioPublication(
    val namespace: ReaderSyncNamespace,
    val bookId: String,
    val bookTitle: String,
    val author: String?,
    val coverApiPath: String?,
    val resource: AudioResource,
    val availableResources: List<AudioResource>,
    val assets: List<AudioAsset>,
    val chapters: List<AudioChapter>,
) {
    init {
        require(bookId.isNotBlank() && bookTitle.isNotBlank())
        require(author == null || author.isNotBlank())
        require(coverApiPath == null || coverApiPath.startsWith("/api/"))
        require(assets.isNotEmpty())
        require(assets == assets.sortedWith(compareBy(AudioAsset::sortOrder, AudioAsset::assetId)))
        require(assets.map(AudioAsset::assetId).distinct().size == assets.size)
        require(assets.all { it.resourceId == resource.resourceId })
        require(chapters == chapters.sortedBy(AudioChapter::index))
        require(chapters.map(AudioChapter::chapterId).distinct().size == chapters.size)
        require(chapters.map(AudioChapter::index).distinct().size == chapters.size)
        require(chapters.all { chapter -> assets.any { it.assetId == chapter.assetId } })
        require(availableResources.map(AudioResource::resourceId).distinct().size == availableResources.size)
    }
}

/**
 * Immutable presentation state owned by the shared audio application.
 *
 * Native clients render this value and bind the referenced source to their media SDK. They must
 * not recalculate chapter, track, timer, completion, or absolute-position rules.
 */
data class AudioPlaybackSnapshot(
    val stage: AudioPlaybackStage,
    val sessionId: Long,
    val sourceId: Long? = null,
    val namespaceKey: String? = null,
    val namespace: ReaderSyncNamespace? = null,
    val publication: AudioPublication? = null,
    val currentAssetIndex: Int = -1,
    val currentAssetId: String? = null,
    val currentChapterId: String? = null,
    val positionMillis: Long = 0,
    val durationMillis: Long? = null,
    val absolutePositionMillis: Long = 0,
    val totalDurationMillis: Long = 0,
    val playbackRate: Double = 1.0,
    val supportedPlaybackRates: List<Double> = AUDIO_PLAYBACK_RATES,
    val skipBackwardSeconds: Int = 15,
    val skipForwardSeconds: Int = 30,
    val sleepTimerMode: AudioSleepTimerMode = AudioSleepTimerMode.Off,
    val sleepTimerEndsAtEpochMillis: Long? = null,
    val syncState: AudioProgressSyncState = AudioProgressSyncState.Synced,
    val pendingResourceId: String? = null,
    val pendingSourceId: Long? = null,
    val preparationStage: AudioSourcePreparationStage = AudioSourcePreparationStage.None,
    val seekStage: AudioSeekStage = AudioSeekStage.None,
    val pendingSeekAbsolutePositionMillis: Long? = null,
    val error: AudioPlaybackError? = null,
) {
    init {
        require(sessionId >= 0)
        require(sourceId == null || sourceId >= 0)
        require(positionMillis >= 0 && absolutePositionMillis >= 0 && totalDurationMillis >= 0)
        require(durationMillis == null || durationMillis >= 0)
        require(playbackRate in AUDIO_PLAYBACK_RATES)
        require(supportedPlaybackRates == AUDIO_PLAYBACK_RATES)
        require(skipBackwardSeconds > 0 && skipForwardSeconds > 0)
        require(sleepTimerEndsAtEpochMillis == null || sleepTimerEndsAtEpochMillis >= 0)
        require(pendingSourceId == null || pendingSourceId >= 0)
        require(pendingSeekAbsolutePositionMillis == null || pendingSeekAbsolutePositionMillis >= 0)
        require(stage != AudioPlaybackStage.Idle || publication == null)
        require(publication == null || namespace == publication.namespace)
        require(publication != null || currentAssetId == null)
        require(publication == null || currentAssetIndex in publication.assets.indices)
        require(publication == null || publication.assets[currentAssetIndex].assetId == currentAssetId)
        require(currentChapterId == null || publication?.chapters?.any {
            it.chapterId == currentChapterId && it.assetId == currentAssetId
        } == true)
        require(stage != AudioPlaybackStage.Error || error != null)
        require((preparationStage == AudioSourcePreparationStage.None) == (pendingSourceId == null))
        require((seekStage == AudioSeekStage.None) == (pendingSeekAbsolutePositionMillis == null))
    }

    val hasSession: Boolean
        get() = publication != null && sourceId != null

    val isPlaying: Boolean
        get() = stage == AudioPlaybackStage.Playing || stage == AudioPlaybackStage.Buffering

    /** Native presentations use this shared fact to render and lock the loading state. */
    val isPreparing: Boolean
        get() = pendingResourceId != null && error == null

    val isSeeking: Boolean
        get() = seekStage == AudioSeekStage.WaitingForEngine && error == null

    val hasPendingSeekInteraction: Boolean
        get() = seekStage != AudioSeekStage.None

    val displayedAbsolutePositionMillis: Long
        get() = pendingSeekAbsolutePositionMillis ?: absolutePositionMillis

    companion object {
        fun idle(sessionId: Long = 0, namespaceKey: String? = null): AudioPlaybackSnapshot =
            AudioPlaybackSnapshot(
                stage = AudioPlaybackStage.Idle,
                sessionId = sessionId,
                namespaceKey = namespaceKey,
            )
    }
}
