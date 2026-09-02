package com.ermao.library.features.audio.model

import androidx.compose.runtime.Immutable
import com.ermao.library.shared.modules.audio.AudioAsset as SharedAudioAsset
import com.ermao.library.shared.modules.audio.AudioLaunchIntent as SharedAudioLaunchIntent
import com.ermao.library.shared.modules.audio.AudioPublication
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/**
 * Media3/UI projection of the shared Audio capability.
 *
 * KMP owns AudioLaunchIntent, AudioPublication, AudioPlaybackSnapshot/StateMachine,
 * authentication, safety and progress policy. These types are deliberately limited to
 * Android engine metadata and Compose view state; they do not contain cookies, transport rules
 * or business decisions. Media3 types stay on this side of the boundary.
 */
@Immutable
data class AndroidAudioNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
) {
    init {
        require(serverIdentity.isNotBlank()) { "Audio server identity is blank" }
        require(userId.isNotBlank()) { "Audio user id is blank" }
        require(authorizationVersion >= 0) { "Audio authorization version is negative" }
    }

    val key: String
        get() = ReaderSyncNamespace(serverIdentity, userId, authorizationVersion).stableKey
}

@Immutable
data class AndroidAudioChapter(
    val id: String,
    val title: String,
    val startMillis: Long,
    val endMillis: Long? = null,
) {
    init {
        require(id.isNotBlank()) { "Audio chapter id is blank" }
        require(title.isNotBlank()) { "Audio chapter title is blank" }
        require(startMillis >= 0) { "Audio chapter start is negative" }
        require(endMillis == null || endMillis >= startMillis) {
            "Audio chapter end precedes its start"
        }
    }
}

@Immutable
data class AndroidAudioTrack(
    val assetId: String,
    val title: String,
    val sourceUri: String,
    val mimeType: String? = null,
    val durationMillis: Long? = null,
    val chapters: List<AndroidAudioChapter> = emptyList(),
) {
    init {
        require(assetId.isNotBlank()) { "Audio asset id is blank" }
        require(title.isNotBlank()) { "Audio track title is blank" }
        require(sourceUri.isNotBlank()) { "Audio source URI is blank" }
        require(durationMillis == null || durationMillis >= 0) {
            "Audio track duration is negative"
        }
        require(chapters.zipWithNext().all { (left, right) -> left.startMillis <= right.startMillis }) {
            "Audio chapters are not in canonical order"
        }
        require(chapters.map(AndroidAudioChapter::id).distinct().size == chapters.size) {
            "Audio chapter ids are not unique"
        }
    }
}

@Immutable
data class AndroidAudioLaunchIntent(
    val namespace: AndroidAudioNamespace,
    val bookId: String,
    val resourceId: String,
    val title: String,
    val author: String? = null,
    val artworkUri: String? = null,
    val tracks: List<AndroidAudioTrack>,
    val assetId: String? = null,
    val chapterId: String? = null,
    val positionMillis: Long = 0,
    val autoplay: Boolean,
) {
    init {
        require(bookId.isNotBlank()) { "Audio book id is blank" }
        require(resourceId.isNotBlank()) { "Audio resource id is blank" }
        require(title.isNotBlank()) { "Audio title is blank" }
        require(tracks.isNotEmpty()) { "Audio launch requires at least one track" }
        require(tracks.map(AndroidAudioTrack::assetId).distinct().size == tracks.size) {
            "Audio track ids are not unique"
        }
        require(assetId == null || tracks.any { it.assetId == assetId }) {
            "Audio launch asset does not belong to the queue"
        }
        require(positionMillis >= 0) { "Audio launch position is negative" }
        require(chapterId == null || tracks.any { track -> track.chapters.any { it.id == chapterId } }) {
            "Audio launch chapter does not belong to the queue"
        }
    }

    val selectedTrack: AndroidAudioTrack
        get() = tracks.firstOrNull { it.assetId == assetId } ?: tracks.first()

    companion object {
        /** Maps the shared bootstrap projection into Media3-neutral Android engine metadata. */
        fun fromPublication(
            publication: AudioPublication,
            intent: SharedAudioLaunchIntent,
            sourceUriForAsset: (SharedAudioAsset) -> String,
            artworkUri: String? = null,
        ): AndroidAudioLaunchIntent {
            val selectedChapter = intent.chapterId?.let { chapterId ->
                publication.chapters.firstOrNull { it.chapterId == chapterId }
            }
            val selectedAssetId = intent.assetId ?: selectedChapter?.assetId
            return AndroidAudioLaunchIntent(
                namespace = AndroidAudioNamespace(
                    serverIdentity = publication.namespace.serverIdentity,
                    userId = publication.namespace.userId,
                    authorizationVersion = publication.namespace.authorizationVersion,
                ),
                bookId = publication.bookId,
                resourceId = publication.resource.resourceId,
                title = publication.bookTitle,
                author = publication.author,
                artworkUri = artworkUri,
                tracks = publication.assets.map { asset ->
                    AndroidAudioTrack(
                        assetId = asset.assetId,
                        title = asset.title,
                        sourceUri = sourceUriForAsset(asset),
                        mimeType = asset.mimeType,
                        durationMillis = asset.durationMillis,
                        chapters = publication.chapters
                            .filter { chapter -> chapter.assetId == asset.assetId }
                            .map { chapter ->
                                AndroidAudioChapter(
                                    id = chapter.chapterId,
                                    title = chapter.title,
                                    startMillis = chapter.startMillis,
                                    endMillis = chapter.endMillis,
                                )
                            },
                    )
                },
                assetId = selectedAssetId,
                chapterId = intent.chapterId,
                positionMillis = intent.positionMillis ?: selectedChapter?.startMillis ?: 0,
                autoplay = intent.autoplay,
            )
        }
    }
}

enum class AndroidAudioPhase {
    Idle,
    Loading,
    Ready,
    Playing,
    Paused,
    Buffering,
    Ended,
    Error,
}

@Immutable
data class AndroidAudioError(
    val code: String,
    val recoverable: Boolean,
) {
    init {
        require(code.isNotBlank()) { "Audio error code is blank" }
    }
}

@Immutable
data class AndroidAudioPlaybackSnapshot(
    val phase: AndroidAudioPhase = AndroidAudioPhase.Idle,
    val namespace: AndroidAudioNamespace? = null,
    val bookId: String? = null,
    val resourceId: String? = null,
    val assetId: String? = null,
    val chapterId: String? = null,
    val title: String? = null,
    val author: String? = null,
    val artworkApiPath: String? = null,
    val chapterTitle: String? = null,
    val positionMillis: Long = 0,
    val durationMillis: Long = 0,
    val bufferedPositionMillis: Long = 0,
    val playbackRate: Float = DEFAULT_PLAYBACK_RATE,
    val error: AndroidAudioError? = null,
) {
    init {
        require(positionMillis >= 0) { "Audio snapshot position is negative" }
        require(durationMillis >= 0) { "Audio snapshot duration is negative" }
        require(bufferedPositionMillis >= 0) { "Audio buffered position is negative" }
        require(playbackRate in MIN_PLAYBACK_RATE..MAX_PLAYBACK_RATE) {
            "Audio snapshot playback rate is outside the supported range"
        }
    }

    val hasSession: Boolean
        get() = resourceId != null && namespace != null

    val progress: Float
        get() = if (durationMillis <= 0) 0f else {
            (positionMillis.toDouble() / durationMillis.toDouble()).toFloat().coerceIn(0f, 1f)
        }
}

const val DEFAULT_PLAYBACK_RATE: Float = 1f
const val MIN_PLAYBACK_RATE: Float = 0.75f
const val MAX_PLAYBACK_RATE: Float = 3f

val SUPPORTED_PLAYBACK_RATES: List<Float> = listOf(
    0.75f,
    1f,
    1.25f,
    1.5f,
    1.75f,
    2f,
    2.5f,
    3f,
)
