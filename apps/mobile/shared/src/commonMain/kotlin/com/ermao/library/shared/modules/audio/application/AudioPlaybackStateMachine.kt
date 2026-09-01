package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AUDIO_PLAYBACK_RATES
import com.ermao.library.shared.modules.audio.domain.AudioLaunchIntent
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackError
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackSnapshot
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

fun interface AudioPlaybackSnapshotObserver {
    fun onSnapshot(snapshot: AudioPlaybackSnapshot)
}

fun interface AudioObservation {
    fun cancel()
}

data class AudioPendingLaunch(
    val token: Long,
    val namespace: ReaderSyncNamespace,
    val intent: AudioLaunchIntent,
)

/**
 * Single application-owned session state machine. Native engines only report facts tagged with
 * the committed session id, so callbacks from a cancelled load or retired namespace are ignored.
 */
class AudioPlaybackStateMachine(
    initialPlaybackRate: Double = 1.0,
) {
    private var generation = 0L
    private var pending: AudioPendingLaunch? = null
    private val state = MutableStateFlow(AudioPlaybackSnapshot.idle())
    val snapshots: StateFlow<AudioPlaybackSnapshot> = state.asStateFlow()

    init {
        require(initialPlaybackRate in AUDIO_PLAYBACK_RATES)
        state.value = state.value.copy(playbackRate = initialPlaybackRate)
    }

    fun snapshot(): AudioPlaybackSnapshot = state.value

    fun beginLaunch(namespace: ReaderSyncNamespace, intent: AudioLaunchIntent): AudioPendingLaunch {
        generation += 1
        return AudioPendingLaunch(generation, namespace, intent).also { launch ->
            pending = launch
            if (state.value.stage == AudioPlaybackStage.Idle) {
                state.value = AudioPlaybackSnapshot(
                    stage = AudioPlaybackStage.Loading,
                    sessionId = launch.token,
                    namespace = namespace,
                    playbackRate = state.value.playbackRate,
                )
            }
        }
    }

    fun commitLaunch(token: Long, publication: AudioPublication): Boolean {
        val launch = pending?.takeIf { it.token == token } ?: return false
        if (publication.namespace != launch.namespace || publication.resource.resourceId != launch.intent.resourceId) {
            return false
        }
        val previousRate = state.value.playbackRate
        val resume = publicationResume(publication, launch.intent)
        pending = null
        state.value = AudioPlaybackSnapshot(
            stage = if (launch.intent.autoplay) AudioPlaybackStage.Playing else AudioPlaybackStage.Ready,
            sessionId = token,
            namespace = publication.namespace,
            publication = publication,
            currentAssetId = resume.assetId,
            currentChapterId = resume.chapterId,
            positionMillis = resume.positionMillis,
            durationMillis = publication.assets.first { it.assetId == resume.assetId }.durationMillis,
            playbackRate = previousRate,
        )
        return true
    }

    fun failLaunch(token: Long, error: AudioPlaybackError): Boolean {
        if (pending?.token != token) return false
        pending = null
        if (state.value.stage == AudioPlaybackStage.Loading) {
            state.value = state.value.copy(stage = AudioPlaybackStage.Error, error = error)
        }
        return true
    }

    fun play(sessionId: Long): Boolean = updateSession(sessionId) {
        it.copy(stage = AudioPlaybackStage.Playing, error = null)
    }

    fun pause(sessionId: Long): Boolean = updateSession(sessionId) {
        it.copy(stage = AudioPlaybackStage.Paused, error = null)
    }

    fun buffering(sessionId: Long): Boolean = updateSession(sessionId) {
        it.copy(stage = AudioPlaybackStage.Buffering, error = null)
    }

    fun ready(sessionId: Long): Boolean = updateSession(sessionId) {
        it.copy(stage = AudioPlaybackStage.Ready, error = null)
    }

    fun ended(sessionId: Long): Boolean = updateSession(sessionId) {
        val duration = it.durationMillis
        it.copy(
            stage = AudioPlaybackStage.Ended,
            positionMillis = duration ?: it.positionMillis,
            error = null,
        )
    }

    fun engineError(sessionId: Long, error: AudioPlaybackError): Boolean = updateSession(sessionId) {
        it.copy(stage = AudioPlaybackStage.Error, error = error)
    }

    fun updatePosition(
        sessionId: Long,
        assetId: String,
        positionMillis: Long,
        durationMillis: Long?,
        chapterId: String? = null,
    ): Boolean = updateSession(sessionId) { current ->
        require(positionMillis >= 0 && (durationMillis == null || durationMillis >= 0))
        val publication = requireNotNull(current.publication)
        require(publication.assets.any { it.assetId == assetId })
        require(chapterId == null || publication.chapters.any {
            it.chapterId == chapterId && it.assetId == assetId
        })
        current.copy(
            currentAssetId = assetId,
            currentChapterId = chapterId ?: chapterAt(publication, assetId, positionMillis)?.chapterId,
            positionMillis = durationMillis?.let { positionMillis.coerceAtMost(it) } ?: positionMillis,
            durationMillis = durationMillis,
        )
    }

    fun seekBy(sessionId: Long, deltaMillis: Long): Boolean = updateSession(sessionId) { current ->
        val upperBound = current.durationMillis ?: Long.MAX_VALUE
        current.copy(positionMillis = (current.positionMillis + deltaMillis).coerceIn(0L, upperBound))
    }

    fun selectChapter(sessionId: Long, chapterId: String): Boolean = updateSession(sessionId) { current ->
        val chapter = requireNotNull(current.publication).chapters.first { it.chapterId == chapterId }
        current.copy(
            currentAssetId = chapter.assetId,
            currentChapterId = chapter.chapterId,
            positionMillis = chapter.startMillis,
            durationMillis = current.publication.assets.first { it.assetId == chapter.assetId }.durationMillis,
        )
    }

    fun selectAsset(sessionId: Long, assetId: String): Boolean = updateSession(sessionId) { current ->
        val publication = requireNotNull(current.publication)
        val asset = publication.assets.first { it.assetId == assetId }
        val chapter = publication.chapters.firstOrNull { it.assetId == assetId }
        current.copy(
            currentAssetId = assetId,
            currentChapterId = chapter?.chapterId,
            positionMillis = chapter?.startMillis ?: 0,
            durationMillis = asset.durationMillis,
        )
    }

    fun setPlaybackRate(rate: Double): Boolean {
        require(rate in AUDIO_PLAYBACK_RATES)
        if (state.value.playbackRate == rate) return false
        state.value = state.value.copy(playbackRate = rate)
        return true
    }

    fun setSleepTimer(mode: AudioSleepTimerMode): Boolean {
        if (state.value.sleepTimerMode == mode) return false
        state.value = state.value.copy(sleepTimerMode = mode)
        return true
    }

    fun setSyncPending(value: Boolean): Boolean {
        if (state.value.syncPending == value) return false
        state.value = state.value.copy(syncPending = value)
        return true
    }

    /** Namespace retirement is ordered before native engine release by the composition root. */
    fun retireSession(): Long {
        generation += 1
        pending = null
        state.value = AudioPlaybackSnapshot.idle(generation).copy(playbackRate = state.value.playbackRate)
        return generation
    }

    private fun updateSession(sessionId: Long, transform: (AudioPlaybackSnapshot) -> AudioPlaybackSnapshot): Boolean {
        val current = state.value
        if (current.stage == AudioPlaybackStage.Idle || current.sessionId != sessionId || pending?.token == sessionId) {
            return false
        }
        state.value = transform(current)
        return true
    }
}

/** Swift-friendly observation/lifetime wrapper over the pure state machine. */
class AudioPlaybackRuntime(
    initialPlaybackRate: Double = 1.0,
    private val scope: CoroutineScope = MainScope(),
) {
    val stateMachine = AudioPlaybackStateMachine(initialPlaybackRate)

    fun snapshot(): AudioPlaybackSnapshot = stateMachine.snapshot()

    fun observe(observer: AudioPlaybackSnapshotObserver): AudioObservation {
        val job = scope.launch { stateMachine.snapshots.collect(observer::onSnapshot) }
        return AudioObservation { job.cancel() }
    }

    fun close() {
        stateMachine.retireSession()
        scope.cancel()
    }
}

private data class AudioResume(val assetId: String, val chapterId: String?, val positionMillis: Long)

private fun publicationResume(publication: AudioPublication, intent: AudioLaunchIntent): AudioResume {
    val chapter = intent.chapterId?.let { chapterId ->
        publication.chapters.firstOrNull { it.chapterId == chapterId }
    }
    val asset = publication.assets.firstOrNull { it.assetId == (intent.assetId ?: chapter?.assetId) }
        ?: publication.assets.first()
    val requestedPosition = intent.positionMillis ?: chapter?.startMillis ?: 0L
    val position = asset.durationMillis?.let { requestedPosition.coerceAtMost(it) } ?: requestedPosition
    return AudioResume(asset.assetId, chapter?.takeIf { it.assetId == asset.assetId }?.chapterId, position)
}

private fun chapterAt(publication: AudioPublication, assetId: String, positionMillis: Long) =
    publication.chapters.lastOrNull { chapter ->
        chapter.assetId == assetId && chapter.startMillis <= positionMillis &&
            (chapter.endMillis == null || positionMillis < chapter.endMillis)
    }
