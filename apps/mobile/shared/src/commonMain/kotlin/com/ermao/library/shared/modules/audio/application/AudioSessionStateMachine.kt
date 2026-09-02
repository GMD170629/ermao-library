package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AUDIO_PLAYBACK_RATES
import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.domain.AudioLaunchIntent
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackError
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackSnapshot
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage
import com.ermao.library.shared.modules.audio.domain.AudioProgressSyncState
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioSeekStage
import com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode
import com.ermao.library.shared.modules.audio.domain.AudioSourcePreparationStage
import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

enum class AudioPlaybackEffectType {
    PrepareSource,
    CommitPreparedSource,
    CancelPreparedSource,
    Play,
    Pause,
    Seek,
    SetPlaybackRate,
    Stop,
    SaveProgress,
}

/** A platform instruction emitted by the shared state machine. */
data class AudioPlaybackEffect(
    val type: AudioPlaybackEffectType,
    val sourceId: Long,
    val asset: AudioAsset? = null,
    val namespaceKey: String? = null,
    val resourceId: String? = null,
    val chapterId: String? = null,
    val positionMillis: Long = 0,
    val durationMillis: Long? = null,
    val playbackRate: Double = 1.0,
    val autoplay: Boolean = false,
    val operationId: Long = 0,
    val progressReason: AudioProgressSaveReason? = null,
) {
    init {
        require(sourceId >= 0)
        require(positionMillis >= 0)
        require(durationMillis == null || durationMillis >= 0)
        require(playbackRate in AUDIO_PLAYBACK_RATES)
        require(operationId >= 0)
        require(chapterId == null || chapterId.isNotBlank())
        require(type != AudioPlaybackEffectType.PrepareSource || asset != null)
        require(type != AudioPlaybackEffectType.Seek || operationId > 0)
        require(type != AudioPlaybackEffectType.SaveProgress || resourceId?.isNotBlank() == true)
        require(type != AudioPlaybackEffectType.SaveProgress || asset != null)
        require(type != AudioPlaybackEffectType.SaveProgress || progressReason != null)
    }
}

data class AudioPlaybackTransition(
    val snapshot: AudioPlaybackSnapshot,
    val effects: List<AudioPlaybackEffect> = emptyList(),
)

data class AudioLaunchRequest(
    val token: Long,
    val transition: AudioPlaybackTransition,
)

private data class PendingLaunch(
    val token: Long,
    val namespace: ReaderSyncNamespace,
    val namespaceKey: String,
    val intent: AudioLaunchIntent,
    val previous: AudioPlaybackSnapshot,
)

private data class PendingPreparation(
    val sourceId: Long,
    val namespaceKey: String,
    val publication: AudioPublication,
    val assetIndex: Int,
    val positionMillis: Long,
    val autoplay: Boolean,
    val previous: AudioPlaybackSnapshot,
    val progressReasonAfterCommit: AudioProgressSaveReason? = null,
    val measuredDurationMillis: Long? = null,
)

private data class ScrubSession(
    val sourceId: Long,
    val resumeAfterSeek: Boolean,
)

private data class PendingSeek(
    val sourceId: Long,
    val operationId: Long,
    val targetPositionMillis: Long,
    val resumeAfterSeek: Boolean,
    val reason: AudioProgressSaveReason,
)

private data class PositionAcceptanceGuard(
    val sourceId: Long,
    val targetPositionMillis: Long,
)

private data class TransportExpectation(
    val sourceId: Long,
    val playing: Boolean,
)

private data class SleepBoundary(
    val assetId: String,
    val chapterId: String?,
    val endMillis: Long?,
)

/**
 * The sole mobile audio business state machine.
 *
 * Native runtimes submit user commands and media-engine facts. Every side effect is returned as a
 * typed instruction, including source preparation/commit and progress persistence. A replacement
 * source never becomes active until the engine reports it prepared and then confirms the commit.
 */
class AudioPlaybackStateMachine(
    initialPlaybackRate: Double = 1.0,
    private val nowEpochMillis: () -> Long = { 0L },
    private val nowMonotonicMillis: () -> Long = nowEpochMillis,
) {
    private var generation = 0L
    private var seekGeneration = 0L
    private var state = AudioPlaybackSnapshot.idle().copy(playbackRate = initialPlaybackRate)
    private var pendingLaunch: PendingLaunch? = null
    private var pendingPreparation: PendingPreparation? = null
    private var scrubSession: ScrubSession? = null
    private var pendingSeek: PendingSeek? = null
    private var positionAcceptanceGuard: PositionAcceptanceGuard? = null
    private var transportExpectation: TransportExpectation? = null
    private var sleepBoundary: SleepBoundary? = null
    private var sleepDeadlineMonotonicMillis: Long? = null
    private var lastTickRequestedAtEpochMillis: Long? = null

    init {
        require(initialPlaybackRate in AUDIO_PLAYBACK_RATES)
    }

    fun snapshot(): AudioPlaybackSnapshot = state

    fun beginLaunch(
        namespace: ReaderSyncNamespace,
        namespaceKey: String,
        intent: AudioLaunchIntent,
    ): AudioLaunchRequest {
        require(namespaceKey.isNotBlank())
        generation += 1
        val save = if (state.hasSession) progressEffect(AudioProgressSaveReason.TrackChange) else null
        val pause = state.sourceId
            ?.takeIf { state.isPlaying }
            ?.let { simpleEffect(AudioPlaybackEffectType.Pause, it) }
        if (pause != null) transportExpectation = TransportExpectation(pause.sourceId, playing = false)
        val previous = if (state.hasSession) {
            state.withoutPendingPreparation().withoutPendingSeek()
        } else {
            pendingLaunch?.previous ?: pendingPreparation?.previous ?: state
        }
        val cancelled = pendingPreparation?.let(::cancelPreparationEffect)
        pendingPreparation = null
        scrubSession = null
        pendingSeek = null
        positionAcceptanceGuard = null
        pendingLaunch = PendingLaunch(generation, namespace, namespaceKey, intent, previous)
        state = previous.copy(
            stage = if (previous.hasSession) previous.stage else AudioPlaybackStage.Preparing,
            sessionId = generation,
            namespaceKey = previous.namespaceKey ?: namespaceKey,
            pendingResourceId = intent.resourceId,
            pendingSourceId = null,
            preparationStage = AudioSourcePreparationStage.None,
            syncState = if (save != null) AudioProgressSyncState.Pending else previous.syncState,
            error = null,
        )
        return AudioLaunchRequest(
            token = generation,
            transition = transition(save.asList() + pause.asList() + cancelled.asList()),
        )
    }

    /** Compatibility entry point used by the Android adapter while it migrates to effects. */
    fun beginLaunch(namespace: ReaderSyncNamespace, intent: AudioLaunchIntent): AudioLaunchRequest =
        beginLaunch(namespace, namespace.stableKey, intent)

    fun publicationLoaded(
        token: Long,
        publication: AudioPublication,
        restoredLocation: AudioReaderLocation?,
    ): AudioPlaybackTransition {
        val launch = pendingLaunch?.takeIf { it.token == token } ?: return transition()
        if (publication.namespace != launch.namespace || publication.resource.resourceId != launch.intent.resourceId) {
            return launchFailed(
                token,
                AudioPlaybackError("AUDIO_BOOTSTRAP_INVALID", recoverable = false),
            )
        }
        val target = resolveLaunchTarget(publication, launch.intent, restoredLocation)
        pendingLaunch = null
        val previous = if (state.hasSession) {
            state.withoutPendingPreparation().withoutPendingSeek()
        } else {
            launch.previous.withoutPendingSeek()
        }
        return beginPreparation(
            namespaceKey = launch.namespaceKey,
            publication = publication,
            assetIndex = target.first,
            positionMillis = target.second,
            autoplay = launch.intent.autoplay,
            previous = previous,
            precedingEffects = emptyList(),
        )
    }

    /** Compatibility bridge; native runtimes must use publicationLoaded + engine facts. */
    fun commitLaunch(token: Long, publication: AudioPublication): Boolean {
        val prepared = publicationLoaded(token, publication, restoredLocation = null)
        val sourceId = prepared.snapshot.pendingSourceId ?: return false
        enginePrepared(sourceId, prepared.snapshot.durationMillis)
        engineCommitted(sourceId)
        return state.sourceId == sourceId
    }

    fun launchFailed(token: Long, error: AudioPlaybackError): AudioPlaybackTransition {
        val launch = pendingLaunch?.takeIf { it.token == token } ?: return transition()
        pendingLaunch = null
        scrubSession = null
        pendingSeek = null
        positionAcceptanceGuard = null
        val shouldResumePrevious = launch.previous.hasSession && launch.previous.isPlaying
        state = if (state.hasSession) {
            state.copy(
                stage = AudioPlaybackStage.Paused,
                pendingResourceId = launch.intent.resourceId,
                pendingSourceId = null,
                preparationStage = AudioSourcePreparationStage.None,
                error = error,
            )
        } else if (launch.previous.hasSession) {
            launch.previous.copy(
                stage = AudioPlaybackStage.Paused,
                pendingResourceId = launch.intent.resourceId,
                error = error,
            )
        } else {
            AudioPlaybackSnapshot.idle(token, launch.namespaceKey).copy(
                stage = AudioPlaybackStage.Error,
                pendingResourceId = launch.intent.resourceId,
                error = error,
            )
        }
        val resume = state.sourceId
            ?.takeIf { shouldResumePrevious }
            ?.let { simpleEffect(AudioPlaybackEffectType.Play, it) }
        if (resume != null) transportExpectation = TransportExpectation(resume.sourceId, playing = true)
        return transition(resume.asList())
    }

    fun play(): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val sourceId = state.sourceId ?: return transition()
        transportExpectation = TransportExpectation(sourceId, playing = true)
        return transition(listOf(simpleEffect(AudioPlaybackEffectType.Play, sourceId)))
    }

    fun pause(): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val sourceId = state.sourceId ?: return transition()
        transportExpectation = TransportExpectation(sourceId, playing = false)
        return transition(listOf(simpleEffect(AudioPlaybackEffectType.Pause, sourceId)))
    }

    fun togglePlayback(): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        return if (state.isPlaying) pause() else play()
    }

    fun beginScrubbing(): AudioPlaybackTransition {
        if (pendingLaunch != null || pendingPreparation != null || pendingSeek != null) return transition()
        if (scrubSession != null) return transition()
        val sourceId = state.sourceId ?: return transition()
        val resumeAfterSeek = state.isPlaying
        scrubSession = ScrubSession(sourceId, resumeAfterSeek)
        state = state.copy(
            stage = AudioPlaybackStage.Paused,
            pendingResourceId = null,
            pendingSourceId = null,
            preparationStage = AudioSourcePreparationStage.None,
            seekStage = AudioSeekStage.Scrubbing,
            pendingSeekAbsolutePositionMillis = state.absolutePositionMillis,
            error = null,
        )
        val pause = sourceId
            .takeIf { resumeAfterSeek }
            ?.let { simpleEffect(AudioPlaybackEffectType.Pause, it) }
        transportExpectation = TransportExpectation(sourceId, playing = false)
        return transition(pause.asList())
    }

    fun updateScrubbingPosition(positionMillis: Long): AudioPlaybackTransition {
        if (scrubSession == null) return transition()
        val publication = state.publication ?: return transition()
        state = state.copy(
            pendingSeekAbsolutePositionMillis = positionMillis.coerceIn(0, totalDuration(publication)),
        )
        return transition()
    }

    fun finishScrubbing(positionMillis: Long): AudioPlaybackTransition {
        val scrub = scrubSession ?: return transition()
        if (state.sourceId != scrub.sourceId) return cancelScrubbing()
        val publication = state.publication ?: return cancelScrubbing()
        val absolutePosition = positionMillis.coerceIn(0, totalDuration(publication))
        scrubSession = null
        return seekToAbsolute(
            publication = publication,
            absolutePositionMillis = absolutePosition,
            resumeAfterSeek = scrub.resumeAfterSeek,
            reason = AudioProgressSaveReason.Seek,
            pauseBeforeSeek = false,
        )
    }

    fun cancelScrubbing(): AudioPlaybackTransition {
        val scrub = scrubSession ?: return transition()
        scrubSession = null
        state = state.withoutPendingSeek()
        val resume = scrub.sourceId
            .takeIf { scrub.resumeAfterSeek && state.sourceId == scrub.sourceId }
            ?.let { simpleEffect(AudioPlaybackEffectType.Play, it) }
        transportExpectation = TransportExpectation(scrub.sourceId, playing = resume != null)
        return transition(resume.asList())
    }

    fun seekAbsolute(positionMillis: Long): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val publication = state.publication ?: return transition()
        return seekToAbsolute(
            publication = publication,
            absolutePositionMillis = positionMillis,
            resumeAfterSeek = state.isPlaying,
            reason = AudioProgressSaveReason.Seek,
        )
    }

    fun seekBy(deltaMillis: Long): AudioPlaybackTransition =
        seekAbsolute(saturatedAdd(state.absolutePositionMillis, deltaMillis))

    fun skipBackward(): AudioPlaybackTransition = seekBy(-state.skipBackwardSeconds * 1_000L)

    fun skipForward(): AudioPlaybackTransition = seekBy(state.skipForwardSeconds * 1_000L)

    fun previousChapter(): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val publication = state.publication ?: return transition()
        val assetId = state.currentAssetId ?: return transition()
        val chapters = publication.chapters.filter { it.assetId == assetId }
        val current = chapterAt(publication, assetId, state.positionMillis)
        val chapterIndex = current?.let { chapter -> chapters.indexOfFirst { it.chapterId == chapter.chapterId } } ?: -1
        return when {
            chapterIndex > 0 -> selectChapter(chapters[chapterIndex - 1].chapterId)
            state.currentAssetIndex > 0 -> switchAsset(
                state.currentAssetIndex - 1,
                0,
                state.isPlaying,
                AudioProgressSaveReason.TrackChange,
            )
            else -> seekWithinActiveAsset(0, AudioProgressSaveReason.Seek)
        }
    }

    fun nextChapter(): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val publication = state.publication ?: return transition()
        val assetId = state.currentAssetId ?: return transition()
        val chapters = publication.chapters.filter { it.assetId == assetId }
        val current = chapterAt(publication, assetId, state.positionMillis)
        val chapterIndex = current?.let { chapter -> chapters.indexOfFirst { it.chapterId == chapter.chapterId } } ?: -1
        return when {
            chapterIndex >= 0 && chapterIndex + 1 < chapters.size ->
                selectChapter(chapters[chapterIndex + 1].chapterId)
            state.currentAssetIndex + 1 < publication.assets.size -> switchAsset(
                state.currentAssetIndex + 1,
                0,
                state.isPlaying,
                AudioProgressSaveReason.TrackChange,
            )
            else -> seekWithinActiveAsset(state.durationMillis ?: state.positionMillis, AudioProgressSaveReason.Seek)
        }
    }

    fun selectChapter(chapterId: String): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val publication = state.publication ?: return transition()
        val chapter = publication.chapters.firstOrNull { it.chapterId == chapterId } ?: return transition()
        val assetIndex = publication.assets.indexOfFirst { it.assetId == chapter.assetId }
        return if (assetIndex == state.currentAssetIndex) {
            seekWithinActiveAsset(chapter.startMillis, AudioProgressSaveReason.ChapterChange)
        } else {
            switchAsset(assetIndex, chapter.startMillis, state.isPlaying, AudioProgressSaveReason.ChapterChange)
        }
    }

    fun selectAsset(assetId: String): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val publication = state.publication ?: return transition()
        val index = publication.assets.indexOfFirst { it.assetId == assetId }
        if (index < 0) return transition()
        return if (index == state.currentAssetIndex) {
            seekWithinActiveAsset(0, AudioProgressSaveReason.TrackChange)
        } else {
            switchAsset(index, 0, state.isPlaying, AudioProgressSaveReason.TrackChange)
        }
    }

    fun setPlaybackRate(rate: Double): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        if (rate !in AUDIO_PLAYBACK_RATES || state.playbackRate == rate) return transition()
        state = state.copy(playbackRate = rate)
        val sourceId = state.sourceId ?: return transition()
        return transition(listOf(AudioPlaybackEffect(
            type = AudioPlaybackEffectType.SetPlaybackRate,
            sourceId = sourceId,
            playbackRate = rate,
        )))
    }

    fun setSleepTimer(mode: AudioSleepTimerMode): AudioPlaybackTransition {
        if (userCommandsLocked()) return transition()
        val now = nowEpochMillis().also { require(it >= 0) }
        val minutes = mode.minutesOrNull()
        val deadline = minutes?.let { saturatedAdd(now, it * 60_000L) }
        sleepDeadlineMonotonicMillis = minutes?.let {
            saturatedAdd(nowMonotonicMillis().also { value -> require(value >= 0) }, it * 60_000L)
        }
        state = state.copy(
            sleepTimerMode = mode,
            sleepTimerEndsAtEpochMillis = deadline,
        )
        sleepBoundary = boundaryForCurrent(mode)
        return transition()
    }

    fun sleepTimerElapsed(observedAtMonotonicMillis: Long): AudioPlaybackTransition {
        require(observedAtMonotonicMillis >= 0)
        val deadline = sleepDeadlineMonotonicMillis ?: return transition()
        if (observedAtMonotonicMillis < deadline) return transition()
        return pauseForSleepTimer()
    }

    fun saveProgress(reason: AudioProgressSaveReason): AudioPlaybackTransition {
        val effect = progressEffect(reason) ?: return transition()
        state = state.copy(syncState = AudioProgressSyncState.Pending)
        return transition(listOf(effect))
    }

    /** Rebuilds the current native engine after a platform media-services reset. */
    fun reloadCurrentSource(): AudioPlaybackTransition {
        val publication = state.publication ?: return transition()
        val index = state.currentAssetIndex
        if (index !in publication.assets.indices) return transition()
        val interruptedSeek = pendingSeek?.takeIf { it.sourceId == state.sourceId }
        pendingSeek = null
        scrubSession = null
        positionAcceptanceGuard = null
        val previous = if (interruptedSeek != null) state else state.withoutPendingSeek()
        return beginPreparation(
            namespaceKey = requireNotNull(state.namespaceKey),
            publication = publication,
            assetIndex = index,
            positionMillis = interruptedSeek?.targetPositionMillis ?: state.positionMillis,
            autoplay = interruptedSeek?.resumeAfterSeek ?: state.isPlaying,
            previous = previous,
            progressReasonAfterCommit = interruptedSeek?.reason,
            precedingEffects = emptyList(),
        )
    }

    fun enginePrepared(sourceId: Long, durationMillis: Long?): AudioPlaybackTransition {
        val pending = pendingPreparation?.takeIf { it.sourceId == sourceId } ?: return transition()
        if (state.pendingSourceId == sourceId &&
            state.preparationStage == AudioSourcePreparationStage.EngineReady
        ) return transition()
        pendingPreparation = pending.copy(measuredDurationMillis = durationMillis)
        state = state.copy(preparationStage = AudioSourcePreparationStage.EngineReady)
        return transition(listOf(AudioPlaybackEffect(
            type = AudioPlaybackEffectType.CommitPreparedSource,
            sourceId = sourceId,
            positionMillis = pending.positionMillis,
            durationMillis = durationMillis,
            playbackRate = state.playbackRate,
            autoplay = pending.autoplay,
        )))
    }

    fun engineCommitted(sourceId: Long): AudioPlaybackTransition {
        val pending = pendingPreparation?.takeIf { it.sourceId == sourceId } ?: return transition()
        if (state.pendingSourceId != sourceId ||
            state.preparationStage != AudioSourcePreparationStage.EngineReady
        ) return transition()
        pendingPreparation = null
        positionAcceptanceGuard = null
        val publication = pending.publication
        val asset = publication.assets[pending.assetIndex]
        val duration = pending.measuredDurationMillis ?: asset.durationMillis
        val position = clampPosition(pending.positionMillis, duration)
        val chapter = chapterAt(publication, asset.assetId, position)
        state = AudioPlaybackSnapshot(
            stage = AudioPlaybackStage.Ready,
            sessionId = sourceId,
            sourceId = sourceId,
            namespaceKey = pending.namespaceKey,
            namespace = publication.namespace,
            publication = publication,
            currentAssetIndex = pending.assetIndex,
            currentAssetId = asset.assetId,
            currentChapterId = chapter?.chapterId,
            positionMillis = position,
            durationMillis = duration,
            absolutePositionMillis = absolutePosition(publication, pending.assetIndex, position),
            totalDurationMillis = totalDuration(publication),
            playbackRate = state.playbackRate,
            skipBackwardSeconds = state.skipBackwardSeconds,
            skipForwardSeconds = state.skipForwardSeconds,
            sleepTimerMode = state.sleepTimerMode,
            sleepTimerEndsAtEpochMillis = state.sleepTimerEndsAtEpochMillis,
            syncState = state.syncState,
        )
        sleepBoundary = boundaryForCurrent(state.sleepTimerMode)
        lastTickRequestedAtEpochMillis = nowEpochMillis().takeIf { it >= 0 }
        transportExpectation = TransportExpectation(sourceId, playing = pending.autoplay)
        val save = pending.progressReasonAfterCommit?.let(::progressEffect)
        if (save != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        return transition(save.asList())
    }

    fun engineReady(sourceId: Long, durationMillis: Long?): AudioPlaybackTransition {
        if (activeSeekInteractionUses(sourceId)) return transition()
        return updateActiveSource(sourceId) {
            val duration = durationMillis ?: it.durationMillis
            it.copy(
                stage = if (it.stage == AudioPlaybackStage.Buffering) AudioPlaybackStage.Ready else it.stage,
                durationMillis = duration,
                positionMillis = clampPosition(it.positionMillis, duration),
            ).withDerivedPosition()
        }
    }

    fun enginePlaying(sourceId: Long): AudioPlaybackTransition {
        if (pendingLaunch != null || pendingPreparation != null) return transition()
        if (activeSeekInteractionUses(sourceId)) return transition()
        transportExpectation?.takeIf { it.sourceId == sourceId }?.let { expectation ->
            if (!expectation.playing) return transition()
            transportExpectation = null
        }
        return updateActiveSource(sourceId) {
            it.copy(
                stage = AudioPlaybackStage.Playing,
                pendingResourceId = null,
                pendingSourceId = null,
                preparationStage = AudioSourcePreparationStage.None,
                error = null,
            )
        }
    }

    fun enginePaused(sourceId: Long): AudioPlaybackTransition {
        if (state.sourceId != sourceId) return transition()
        if (activeSeekInteractionUses(sourceId)) return transition()
        transportExpectation?.takeIf { it.sourceId == sourceId }?.let { expectation ->
            if (expectation.playing) return transition()
            transportExpectation = null
        }
        state = state.copy(stage = AudioPlaybackStage.Paused)
        val effect = progressEffect(AudioProgressSaveReason.Pause)
        if (effect != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        return transition(effect.asList())
    }

    fun engineBuffering(sourceId: Long): AudioPlaybackTransition {
        if (activeSeekInteractionUses(sourceId)) return transition()
        if (transportExpectation?.let { it.sourceId == sourceId && !it.playing } == true) {
            return transition()
        }
        return updateActiveSource(sourceId) {
            it.copy(stage = AudioPlaybackStage.Buffering, error = null)
        }
    }

    fun engineSeekCompleted(
        sourceId: Long,
        operationId: Long,
        positionMillis: Long,
        durationMillis: Long?,
    ): AudioPlaybackTransition {
        val pending = pendingSeek?.takeIf {
            it.sourceId == sourceId && it.operationId == operationId
        } ?: return transition()
        if (positionMillis < 0 || durationMillis?.let { it < 0 } == true) return transition()
        pendingSeek = null
        val duration = durationMillis ?: state.durationMillis
        val acceptedPosition = clampPosition(positionMillis, duration)
        state = state.copy(
            stage = AudioPlaybackStage.Paused,
            positionMillis = acceptedPosition,
            durationMillis = duration,
            seekStage = AudioSeekStage.None,
            pendingSeekAbsolutePositionMillis = null,
            error = null,
        ).withDerivedPosition()
        positionAcceptanceGuard = PositionAcceptanceGuard(sourceId, acceptedPosition)
        sleepBoundary = boundaryForCurrent(state.sleepTimerMode)
        val save = progressEffect(pending.reason)
        if (save != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        val resume = sourceId
            .takeIf { pending.resumeAfterSeek }
            ?.let { simpleEffect(AudioPlaybackEffectType.Play, it) }
        transportExpectation = TransportExpectation(sourceId, playing = pending.resumeAfterSeek)
        return transition(save.asList() + resume.asList())
    }

    fun engineSeekFailed(
        sourceId: Long,
        operationId: Long,
        error: AudioPlaybackError,
    ): AudioPlaybackTransition {
        val pending = pendingSeek?.takeIf {
            it.sourceId == sourceId && it.operationId == operationId
        } ?: return transition()
        pendingSeek = null
        positionAcceptanceGuard = null
        state = state.withoutPendingSeek().copy(
            stage = AudioPlaybackStage.Paused,
            error = error,
        )
        val resume = sourceId
            .takeIf { pending.resumeAfterSeek }
            ?.let { simpleEffect(AudioPlaybackEffectType.Play, it) }
        transportExpectation = TransportExpectation(sourceId, playing = pending.resumeAfterSeek)
        return transition(resume.asList())
    }

    fun enginePosition(
        sourceId: Long,
        positionMillis: Long,
        durationMillis: Long?,
    ): AudioPlaybackTransition {
        if (state.sourceId != sourceId || positionMillis < 0 || durationMillis?.let { it < 0 } == true) {
            return transition()
        }
        if (state.seekStage != AudioSeekStage.None) return transition()
        positionAcceptanceGuard?.takeIf { it.sourceId == sourceId }?.let { guard ->
            if (absoluteDifference(positionMillis, guard.targetPositionMillis) > POSITION_ACCEPTANCE_MILLIS) {
                return transition()
            }
            positionAcceptanceGuard = null
        }
        val duration = durationMillis ?: state.durationMillis
        state = state.copy(
            positionMillis = clampPosition(positionMillis, duration),
            durationMillis = duration,
        ).withDerivedPosition()
        if (shouldPauseForSleepBoundary(sourceId)) return pauseForSleepTimer()
        val now = nowEpochMillis()
        val shouldSaveTick = state.isPlaying && now >= 0 &&
            lastTickRequestedAtEpochMillis?.let { now - it >= SAVE_INTERVAL_MILLIS } == true
        if (!shouldSaveTick) return transition()
        lastTickRequestedAtEpochMillis = now
        val effect = progressEffect(AudioProgressSaveReason.Tick)
        if (effect != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        return transition(effect.asList())
    }

    fun engineEnded(sourceId: Long): AudioPlaybackTransition {
        if (state.sourceId != sourceId) return transition()
        if (state.seekStage != AudioSeekStage.None) return transition()
        if (transportExpectation?.sourceId == sourceId) transportExpectation = null
        val publication = state.publication ?: return transition()
        val endedPosition = state.durationMillis ?: state.positionMillis
        state = state.copy(
            stage = AudioPlaybackStage.Ended,
            positionMillis = endedPosition,
        ).withDerivedPosition()
        if (pendingPreparation != null) {
            state = state.copy(stage = AudioPlaybackStage.Ended)
            return transition()
        }
        if (state.sleepTimerMode == AudioSleepTimerMode.EndOfTrack ||
            state.sleepTimerMode == AudioSleepTimerMode.EndOfChapter ||
            timerDeadlineReached()
        ) {
            return pauseForSleepTimer()
        }
        val nextIndex = state.currentAssetIndex + 1
        if (nextIndex < publication.assets.size) {
            val save = progressEffect(AudioProgressSaveReason.TrackChange)
            if (save != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
            return switchAsset(
                assetIndex = nextIndex,
                positionMillis = 0,
                autoplay = true,
                saveReason = null,
                precedingEffects = save.asList(),
            )
        }
        val save = progressEffect(AudioProgressSaveReason.Completed)
        if (save != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        return transition(save.asList())
    }

    fun engineFailed(sourceId: Long, error: AudioPlaybackError): AudioPlaybackTransition {
        val pending = pendingPreparation?.takeIf { it.sourceId == sourceId }
        if (pending != null) {
            pendingPreparation = null
            val shouldResumePrevious = pending.previous.hasSession &&
                (pending.previous.isPlaying ||
                    (pending.previous.seekStage != AudioSeekStage.None && pending.autoplay))
            state = if (state.hasSession && state.sourceId != sourceId) {
                state.withoutPendingSeek().copy(
                    stage = AudioPlaybackStage.Paused,
                    pendingResourceId = pending.publication.resource.resourceId,
                    pendingSourceId = null,
                    preparationStage = AudioSourcePreparationStage.None,
                    error = error,
                )
            } else if (pending.previous.hasSession) {
                pending.previous.withoutPendingSeek().copy(
                    stage = AudioPlaybackStage.Paused,
                    pendingResourceId = pending.publication.resource.resourceId,
                    error = error,
                )
            } else {
                AudioPlaybackSnapshot.idle(sourceId, pending.namespaceKey).copy(
                    stage = AudioPlaybackStage.Error,
                    pendingResourceId = pending.publication.resource.resourceId,
                    error = error,
                )
            }
            val resume = state.sourceId
                ?.takeIf { shouldResumePrevious }
                ?.let { simpleEffect(AudioPlaybackEffectType.Play, it) }
            if (resume != null) transportExpectation = TransportExpectation(resume.sourceId, playing = true)
            return transition(listOf(cancelPreparationEffect(pending)) + resume.asList())
        }
        if (state.sourceId != sourceId) return transition()
        scrubSession = null
        pendingSeek = null
        positionAcceptanceGuard = null
        transportExpectation = null
        state = state.withoutPendingSeek().copy(stage = AudioPlaybackStage.Error, error = error)
        val save = progressEffect(AudioProgressSaveReason.Pause)
        if (save != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        return transition(save.asList())
    }

    fun progressSaved(sourceId: Long, failed: Boolean): AudioPlaybackTransition {
        if (state.sourceId != sourceId) return transition()
        state = state.copy(
            syncState = if (failed) AudioProgressSyncState.Failed else AudioProgressSyncState.Synced,
        )
        return transition()
    }

    fun stop(): AudioPlaybackTransition {
        val activeSource = state.sourceId
        val stopSource = activeSource ?: pendingPreparation?.sourceId ?: pendingLaunch?.token
        val effects = buildList {
            pendingPreparation?.let { add(cancelPreparationEffect(it)) }
            activeSource?.let { add(simpleEffect(AudioPlaybackEffectType.Pause, it)) }
            progressEffect(AudioProgressSaveReason.Stop)?.let(::add)
            stopSource?.let { add(simpleEffect(AudioPlaybackEffectType.Stop, it)) }
        }
        generation += 1
        pendingLaunch = null
        pendingPreparation = null
        scrubSession = null
        pendingSeek = null
        positionAcceptanceGuard = null
        transportExpectation = null
        sleepBoundary = null
        sleepDeadlineMonotonicMillis = null
        lastTickRequestedAtEpochMillis = null
        state = AudioPlaybackSnapshot.idle(generation, state.namespaceKey).copy(playbackRate = state.playbackRate)
        return transition(effects)
    }

    /** Namespace retirement for adapters that own engine teardown separately. */
    fun retireSession(): Long {
        generation += 1
        pendingLaunch = null
        pendingPreparation = null
        scrubSession = null
        pendingSeek = null
        positionAcceptanceGuard = null
        transportExpectation = null
        sleepBoundary = null
        sleepDeadlineMonotonicMillis = null
        lastTickRequestedAtEpochMillis = null
        state = AudioPlaybackSnapshot.idle(generation).copy(playbackRate = state.playbackRate)
        return generation
    }

    private fun switchAsset(
        assetIndex: Int,
        positionMillis: Long,
        autoplay: Boolean,
        saveReason: AudioProgressSaveReason?,
        precedingEffects: List<AudioPlaybackEffect> = emptyList(),
    ): AudioPlaybackTransition {
        val publication = state.publication ?: return transition()
        if (assetIndex !in publication.assets.indices) return transition()
        val save = saveReason
            ?.takeIf { it == AudioProgressSaveReason.TrackChange }
            ?.let(::progressEffect)
        if (save != null) state = state.copy(syncState = AudioProgressSyncState.Pending)
        state = state.copy(
            seekStage = AudioSeekStage.WaitingForEngine,
            pendingSeekAbsolutePositionMillis = absolutePosition(publication, assetIndex, positionMillis),
        )
        return beginPreparation(
            namespaceKey = requireNotNull(state.namespaceKey),
            publication = publication,
            assetIndex = assetIndex,
            positionMillis = positionMillis,
            autoplay = autoplay,
            previous = state,
            progressReasonAfterCommit = saveReason,
            precedingEffects = precedingEffects + save.asList(),
        )
    }

    private fun beginPreparation(
        namespaceKey: String,
        publication: AudioPublication,
        assetIndex: Int,
        positionMillis: Long,
        autoplay: Boolean,
        previous: AudioPlaybackSnapshot,
        progressReasonAfterCommit: AudioProgressSaveReason? = null,
        precedingEffects: List<AudioPlaybackEffect>,
    ): AudioPlaybackTransition {
        require(assetIndex in publication.assets.indices)
        generation += 1
        val sourceId = generation
        val asset = publication.assets[assetIndex]
        val duration = asset.durationMillis
        val pending = PendingPreparation(
            sourceId = sourceId,
            namespaceKey = namespaceKey,
            publication = publication,
            assetIndex = assetIndex,
            positionMillis = clampPosition(positionMillis, duration),
            autoplay = autoplay,
            previous = previous,
            progressReasonAfterCommit = progressReasonAfterCommit,
        )
        val cancelled = pendingPreparation?.let(::cancelPreparationEffect)
        val pause = previous.sourceId
            ?.takeIf { previous.isPlaying }
            ?.let { simpleEffect(AudioPlaybackEffectType.Pause, it) }
        if (pause != null) transportExpectation = TransportExpectation(pause.sourceId, playing = false)
        pendingPreparation = pending
        state = previous.copy(
            stage = if (previous.hasSession) previous.stage else AudioPlaybackStage.Preparing,
            sessionId = sourceId,
            namespaceKey = namespaceKey,
            pendingResourceId = publication.resource.resourceId,
            pendingSourceId = sourceId,
            preparationStage = AudioSourcePreparationStage.Preparing,
            error = null,
        )
        val prepare = AudioPlaybackEffect(
            type = AudioPlaybackEffectType.PrepareSource,
            sourceId = sourceId,
            asset = asset,
            namespaceKey = namespaceKey,
            resourceId = publication.resource.resourceId,
        )
        return transition(precedingEffects + cancelled.asList() + pause.asList() + prepare)
    }

    private fun seekWithinActiveAsset(
        requestedPositionMillis: Long,
        reason: AudioProgressSaveReason,
    ): AudioPlaybackTransition = beginSeekWithinActiveAsset(
        requestedPositionMillis = requestedPositionMillis,
        absolutePositionMillis = state.publication?.let {
            absolutePosition(it, state.currentAssetIndex, requestedPositionMillis)
        } ?: requestedPositionMillis,
        resumeAfterSeek = state.isPlaying,
        reason = reason,
        pauseBeforeSeek = true,
    )

    private fun seekToAbsolute(
        publication: AudioPublication,
        absolutePositionMillis: Long,
        resumeAfterSeek: Boolean,
        reason: AudioProgressSaveReason,
        pauseBeforeSeek: Boolean = true,
    ): AudioPlaybackTransition {
        val clampedAbsolute = absolutePositionMillis.coerceIn(0, totalDuration(publication))
        val target = absoluteTarget(publication, clampedAbsolute)
        return if (target.first == state.currentAssetIndex) {
            beginSeekWithinActiveAsset(
                requestedPositionMillis = target.second,
                absolutePositionMillis = clampedAbsolute,
                resumeAfterSeek = resumeAfterSeek,
                reason = reason,
                pauseBeforeSeek = pauseBeforeSeek,
            )
        } else {
            switchAsset(target.first, target.second, resumeAfterSeek, reason)
        }
    }

    private fun beginSeekWithinActiveAsset(
        requestedPositionMillis: Long,
        absolutePositionMillis: Long,
        resumeAfterSeek: Boolean,
        reason: AudioProgressSaveReason,
        pauseBeforeSeek: Boolean,
    ): AudioPlaybackTransition {
        val sourceId = state.sourceId ?: return transition()
        val target = clampPosition(requestedPositionMillis, state.durationMillis)
        seekGeneration += 1
        pendingSeek = PendingSeek(
            sourceId = sourceId,
            operationId = seekGeneration,
            targetPositionMillis = target,
            resumeAfterSeek = resumeAfterSeek,
            reason = reason,
        )
        state = state.copy(
            stage = AudioPlaybackStage.Paused,
            pendingResourceId = null,
            pendingSourceId = null,
            preparationStage = AudioSourcePreparationStage.None,
            seekStage = AudioSeekStage.WaitingForEngine,
            pendingSeekAbsolutePositionMillis = absolutePositionMillis,
            error = null,
        )
        val pause = sourceId
            .takeIf { pauseBeforeSeek && resumeAfterSeek }
            ?.let { simpleEffect(AudioPlaybackEffectType.Pause, it) }
        return transition(
            pause.asList() + AudioPlaybackEffect(
                type = AudioPlaybackEffectType.Seek,
                sourceId = sourceId,
                positionMillis = target,
                operationId = seekGeneration,
            ),
        )
    }

    private fun updateActiveSource(
        sourceId: Long,
        transform: (AudioPlaybackSnapshot) -> AudioPlaybackSnapshot,
    ): AudioPlaybackTransition {
        if (state.sourceId != sourceId) return transition()
        state = transform(state)
        return transition()
    }

    private fun AudioPlaybackSnapshot.withDerivedPosition(): AudioPlaybackSnapshot {
        val publication = publication ?: return this
        val assetId = currentAssetId ?: return this
        val chapter = chapterAt(publication, assetId, positionMillis)
        return copy(
            currentChapterId = chapter?.chapterId,
            absolutePositionMillis = absolutePosition(publication, currentAssetIndex, positionMillis),
            totalDurationMillis = totalDuration(publication),
        )
    }

    private fun AudioPlaybackSnapshot.withoutPendingPreparation(): AudioPlaybackSnapshot = copy(
        pendingResourceId = null,
        pendingSourceId = null,
        preparationStage = AudioSourcePreparationStage.None,
    )

    private fun AudioPlaybackSnapshot.withoutPendingSeek(): AudioPlaybackSnapshot = copy(
        seekStage = AudioSeekStage.None,
        pendingSeekAbsolutePositionMillis = null,
    )

    private fun progressEffect(reason: AudioProgressSaveReason): AudioPlaybackEffect? {
        val publication = state.publication ?: return null
        val sourceId = state.sourceId ?: return null
        val asset = publication.assets.getOrNull(state.currentAssetIndex) ?: return null
        if (reason != AudioProgressSaveReason.Tick) {
            lastTickRequestedAtEpochMillis = nowEpochMillis().takeIf { it >= 0 }
        }
        return AudioPlaybackEffect(
            type = AudioPlaybackEffectType.SaveProgress,
            sourceId = sourceId,
            asset = asset,
            namespaceKey = state.namespaceKey,
            resourceId = publication.resource.resourceId,
            chapterId = state.currentChapterId,
            positionMillis = state.positionMillis,
            durationMillis = state.durationMillis,
            progressReason = reason,
        )
    }

    private fun boundaryForCurrent(mode: AudioSleepTimerMode): SleepBoundary? {
        val publication = state.publication ?: return null
        val assetId = state.currentAssetId ?: return null
        val chapter = chapterAt(publication, assetId, state.positionMillis)
        return when (mode) {
            AudioSleepTimerMode.EndOfChapter -> SleepBoundary(
                assetId = assetId,
                chapterId = chapter?.chapterId,
                endMillis = chapter?.endMillis ?: state.durationMillis,
            )
            AudioSleepTimerMode.EndOfTrack -> SleepBoundary(
                assetId = assetId,
                chapterId = null,
                endMillis = state.durationMillis,
            )
            else -> null
        }
    }

    private fun shouldPauseForSleepBoundary(sourceId: Long): Boolean {
        if (state.sourceId != sourceId) return false
        if (timerDeadlineReached()) return true
        val boundary = sleepBoundary ?: return false
        if (state.currentAssetId != boundary.assetId) return true
        return boundary.endMillis?.let { state.positionMillis >= it } == true
    }

    private fun timerDeadlineReached(): Boolean {
        val deadline = sleepDeadlineMonotonicMillis ?: return false
        val now = nowMonotonicMillis()
        return now >= 0 && now >= deadline
    }

    private fun pauseForSleepTimer(): AudioPlaybackTransition {
        val sourceId = state.sourceId ?: return transition()
        state = state.copy(
            sleepTimerMode = AudioSleepTimerMode.Off,
            sleepTimerEndsAtEpochMillis = null,
        )
        sleepBoundary = null
        sleepDeadlineMonotonicMillis = null
        transportExpectation = TransportExpectation(sourceId, playing = false)
        return transition(listOf(simpleEffect(AudioPlaybackEffectType.Pause, sourceId)))
    }

    private fun resolveLaunchTarget(
        publication: AudioPublication,
        intent: AudioLaunchIntent,
        restoredLocation: AudioReaderLocation?,
    ): Pair<Int, Long> {
        val chapter = intent.chapterId?.let { chapterId ->
            publication.chapters.firstOrNull { it.chapterId == chapterId }
        }
        val requestedAssetId = intent.assetId ?: chapter?.assetId ?: restoredLocation?.assetId
        val index = publication.assets.indexOfFirst { it.assetId == requestedAssetId }.takeIf { it >= 0 } ?: 0
        val asset = publication.assets[index]
        val restored = restoredLocation?.takeIf { it.assetId == asset.assetId }
        val position = intent.positionMillis ?: chapter?.startMillis ?: restored?.positionMillis ?: 0L
        return index to clampPosition(position, asset.durationMillis)
    }

    private fun absoluteTarget(publication: AudioPublication, requested: Long): Pair<Int, Long> {
        val total = totalDuration(publication)
        val target = requested.coerceIn(0, total)
        var offset = 0L
        publication.assets.forEachIndexed { index, asset ->
            val duration = asset.durationMillis ?: 0L
            val end = saturatedAdd(offset, duration)
            if (target < end || index == publication.assets.lastIndex) {
                return index to (target - offset).coerceIn(0, duration)
            }
            offset = end
        }
        return 0 to 0
    }

    private fun absolutePosition(publication: AudioPublication, assetIndex: Int, positionMillis: Long): Long {
        var result = 0L
        publication.assets.take(assetIndex.coerceAtLeast(0)).forEach { asset ->
            result = saturatedAdd(result, asset.durationMillis ?: 0L)
        }
        return saturatedAdd(result, positionMillis)
    }

    private fun totalDuration(publication: AudioPublication): Long {
        val assetTotal = publication.assets.fold(0L) { total, asset ->
            saturatedAdd(total, asset.durationMillis ?: 0L)
        }
        return maxOf(assetTotal, publication.resource.durationMillis ?: 0L)
    }

    private fun chapterAt(publication: AudioPublication, assetId: String, positionMillis: Long) =
        publication.chapters.lastOrNull { chapter ->
            chapter.assetId == assetId && chapter.startMillis <= positionMillis &&
                (chapter.endMillis == null || positionMillis < chapter.endMillis)
        } ?: publication.chapters.firstOrNull { it.assetId == assetId }

    private fun clampPosition(positionMillis: Long, durationMillis: Long?): Long =
        positionMillis.coerceAtLeast(0).let { position -> durationMillis?.let(position::coerceAtMost) ?: position }

    private fun cancelPreparationEffect(pending: PendingPreparation) = AudioPlaybackEffect(
        type = AudioPlaybackEffectType.CancelPreparedSource,
        sourceId = pending.sourceId,
    )

    private fun simpleEffect(type: AudioPlaybackEffectType, sourceId: Long) = AudioPlaybackEffect(
        type = type,
        sourceId = sourceId,
    )

    private fun activeSeekInteractionUses(sourceId: Long): Boolean =
        scrubSession?.sourceId == sourceId || pendingSeek?.sourceId == sourceId

    private fun userCommandsLocked(): Boolean =
        pendingLaunch != null || pendingPreparation != null || scrubSession != null || pendingSeek != null

    private fun transition(effects: List<AudioPlaybackEffect> = emptyList()) =
        AudioPlaybackTransition(state, effects)
}

private fun AudioSleepTimerMode.minutesOrNull(): Long? = when (this) {
    AudioSleepTimerMode.Minutes15 -> 15
    AudioSleepTimerMode.Minutes30 -> 30
    AudioSleepTimerMode.Minutes45 -> 45
    AudioSleepTimerMode.Minutes60 -> 60
    else -> null
}

private fun saturatedAdd(left: Long, right: Long): Long = when {
    right > 0 && left > Long.MAX_VALUE - right -> Long.MAX_VALUE
    right < 0 && left < Long.MIN_VALUE - right -> Long.MIN_VALUE
    else -> left + right
}

private fun absoluteDifference(left: Long, right: Long): Long =
    if (left >= right) left - right else right - left

private fun <T> T?.asList(): List<T> = if (this == null) emptyList() else listOf(this)

private const val SAVE_INTERVAL_MILLIS = 15_000L
private const val POSITION_ACCEPTANCE_MILLIS = 5_000L
