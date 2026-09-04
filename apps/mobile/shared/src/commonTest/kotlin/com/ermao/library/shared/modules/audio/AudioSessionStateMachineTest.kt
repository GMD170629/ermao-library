package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.modules.audio.application.AudioPlaybackEffectType
import com.ermao.library.shared.modules.audio.application.AudioPlaybackStateMachine
import com.ermao.library.shared.modules.audio.application.AudioProgressSaveReason
import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.domain.AudioChapter
import com.ermao.library.shared.modules.audio.domain.AudioLaunchIntent
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackError
import com.ermao.library.shared.modules.audio.domain.AudioPlaybackStage
import com.ermao.library.shared.modules.audio.domain.AudioProgressSyncState
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioResource
import com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode
import com.ermao.library.shared.modules.audio.domain.AudioSourcePreparationStage
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AudioSessionStateMachineTest {
    @Test
    fun sourceIsCommittedOnlyAfterPreparedAndCommitFacts() {
        val state = AudioPlaybackStateMachine()
        val launch = state.beginLaunch(namespace(), "native", AudioLaunchIntent("resource-1", autoplay = true))
        val preparation = state.publicationLoaded(launch.token, publication("resource-1"), null)
        val sourceId = requireNotNull(preparation.snapshot.pendingSourceId)

        assertEquals(AudioPlaybackStage.Preparing, preparation.snapshot.stage)
        assertEquals(AudioSourcePreparationStage.Preparing, preparation.snapshot.preparationStage)
        assertNull(preparation.snapshot.publication)
        assertEquals(AudioPlaybackEffectType.PrepareSource, preparation.effects.single().type)

        val prematureCommit = state.engineCommitted(sourceId)
        assertNull(prematureCommit.snapshot.publication)
        assertTrue(prematureCommit.effects.isEmpty())

        val engineReady = state.enginePrepared(sourceId, 60_000)
        assertEquals(AudioPlaybackStage.Preparing, engineReady.snapshot.stage)
        assertEquals(AudioSourcePreparationStage.EngineReady, engineReady.snapshot.preparationStage)
        assertEquals(AudioPlaybackEffectType.CommitPreparedSource, engineReady.effects.single().type)
        assertNull(engineReady.snapshot.publication)
        assertTrue(state.enginePrepared(sourceId, 60_000).effects.isEmpty())

        val committed = state.engineCommitted(sourceId)
        assertEquals(AudioPlaybackStage.Ready, committed.snapshot.stage)
        assertEquals("resource-1", committed.snapshot.publication?.resource?.resourceId)
        assertEquals("asset-1", committed.snapshot.currentAssetId)
        assertEquals(sourceId, committed.snapshot.sourceId)
        assertEquals(AudioPlaybackStage.Playing, state.enginePlaying(sourceId).snapshot.stage)
    }

    @Test
    fun failedReplacementPreservesCommittedSessionAndRejectsStaleFacts() {
        val state = AudioPlaybackStateMachine()
        val firstSource = commit(state, publication("resource-1"), autoplay = true)

        val launch = state.beginLaunch(namespace(), "native", AudioLaunchIntent("resource-2", autoplay = true))
        val preparing = state.publicationLoaded(launch.token, publication("resource-2"), null)
        val candidate = requireNotNull(preparing.snapshot.pendingSourceId)
        assertTrue(preparing.snapshot.isPreparing)
        assertEquals("resource-1", preparing.snapshot.publication?.resource?.resourceId)
        assertNotEquals(firstSource, candidate)
        assertEquals(AudioPlaybackStage.Playing, preparing.snapshot.stage)

        state.enginePosition(firstSource, 12_000, 60_000)
        assertEquals(
            AudioPlaybackEffectType.CommitPreparedSource,
            state.enginePrepared(candidate, 60_000).effects.single().type,
        )

        val failed = state.engineFailed(candidate, AudioPlaybackError("AUDIO_NETWORK_FAILURE", true))
        assertEquals("resource-1", failed.snapshot.publication?.resource?.resourceId)
        assertEquals(firstSource, failed.snapshot.sourceId)
        assertEquals(12_000, failed.snapshot.positionMillis)
        assertTrue(!failed.snapshot.isPreparing)
        assertEquals(
            listOf(AudioPlaybackEffectType.CancelPreparedSource, AudioPlaybackEffectType.Play),
            failed.effects.map { it.type },
        )

        state.enginePosition(candidate, 55_000, 60_000)
        assertEquals(12_000, state.snapshot().positionMillis)
    }

    @Test
    fun rapidReplacementFailureRollsBackToTheLastCommittedStage() {
        val state = AudioPlaybackStateMachine()
        val firstSource = commit(state, publication("resource-1"), autoplay = true)

        state.beginLaunch(namespace(), "native", AudioLaunchIntent("resource-2", autoplay = true))
        val latest = state.beginLaunch(
            namespace(),
            "native",
            AudioLaunchIntent("resource-3", autoplay = true),
        )
        val preparing = state.publicationLoaded(latest.token, publication("resource-3"), null)
        val candidate = requireNotNull(preparing.snapshot.pendingSourceId)

        val failed = state.engineFailed(candidate, AudioPlaybackError("AUDIO_NETWORK_FAILURE", true))

        assertEquals(firstSource, failed.snapshot.sourceId)
        assertEquals("resource-1", failed.snapshot.publication?.resource?.resourceId)
        assertEquals(AudioPlaybackStage.Paused, failed.snapshot.stage)
        assertEquals(AudioPlaybackEffectType.Play, failed.effects.last().type)
    }

    @Test
    fun replacementBootstrapFailureKeepsLatestCommittedFactsAndSavesOldProgress() {
        val state = AudioPlaybackStateMachine()
        val firstSource = commit(state, publication("resource-1"), autoplay = true)

        val launch = state.beginLaunch(
            namespace(),
            "native",
            AudioLaunchIntent("resource-2", autoplay = true),
        )
        assertEquals(
            AudioProgressSaveReason.TrackChange,
            launch.transition.effects.first { it.type == AudioPlaybackEffectType.SaveProgress }.progressReason,
        )
        assertTrue(launch.transition.effects.any { it.type == AudioPlaybackEffectType.Pause })
        state.enginePosition(firstSource, 18_000, 60_000)

        val failed = state.launchFailed(
            launch.token,
            AudioPlaybackError("AUDIO_NETWORK_FAILURE", true),
        )

        assertEquals(firstSource, failed.snapshot.sourceId)
        assertEquals("resource-1", failed.snapshot.publication?.resource?.resourceId)
        assertEquals(18_000, failed.snapshot.positionMillis)
        assertEquals(AudioPlaybackStage.Paused, failed.snapshot.stage)
        assertEquals(AudioPlaybackEffectType.Play, failed.effects.single().type)
        assertEquals(AudioPlaybackStage.Playing, state.enginePlaying(firstSource).snapshot.stage)
    }

    @Test
    fun latePlayingFactCannotDiscardAReplacementThatIsStillPreparing() {
        val state = AudioPlaybackStateMachine()
        val firstSource = commit(state, publication("resource-1"), autoplay = true)
        val preparing = state.beginLaunch(
            namespace(),
            "native",
            AudioLaunchIntent("resource-2", autoplay = true),
        )
        val candidateTransition = state.publicationLoaded(
            preparing.token,
            publication("resource-2"),
            null,
        )
        val candidate = requireNotNull(candidateTransition.snapshot.pendingSourceId)

        val latePlaying = state.enginePlaying(firstSource)

        assertTrue(latePlaying.effects.isEmpty())
        assertEquals(candidate, latePlaying.snapshot.pendingSourceId)
        assertTrue(latePlaying.snapshot.isPreparing)
        assertEquals(
            AudioPlaybackEffectType.CommitPreparedSource,
            state.enginePrepared(candidate, 60_000).effects.single().type,
        )
    }

    @Test
    fun stopDuringInitialCommitWindowStillRequestsNativeTeardown() {
        val state = AudioPlaybackStateMachine()
        val launch = state.beginLaunch(namespace(), "native", AudioLaunchIntent("resource-1", autoplay = true))
        val preparing = state.publicationLoaded(launch.token, publication("resource-1"), null)
        val source = requireNotNull(preparing.snapshot.pendingSourceId)
        state.enginePrepared(source, 60_000)

        val stopped = state.stop()

        assertEquals(AudioPlaybackStage.Idle, stopped.snapshot.stage)
        assertTrue(stopped.effects.any { it.type == AudioPlaybackEffectType.CancelPreparedSource })
        assertTrue(stopped.effects.any { it.type == AudioPlaybackEffectType.Stop })
    }

    @Test
    fun replacementStopCancelsAndPausesBeforeSavingAndTeardown() {
        val state = AudioPlaybackStateMachine()
        val publication = publication("resource-1", twoTracks = true)
        commit(state, publication, autoplay = true)
        state.selectAsset("asset-2")

        val stopped = state.stop()

        assertEquals(
            listOf(
                AudioPlaybackEffectType.CancelPreparedSource,
                AudioPlaybackEffectType.Pause,
                AudioPlaybackEffectType.SaveProgress,
                AudioPlaybackEffectType.Stop,
            ),
            stopped.effects.map { it.type },
        )
    }

    @Test
    fun userPlaybackCommandsAreLockedWhileAReplacementIsPreparing() {
        val state = AudioPlaybackStateMachine()
        val publication = publication("resource-1", twoTracks = true)
        commit(state, publication, autoplay = true)
        val preparing = state.selectAsset("asset-2")
        val candidate = requireNotNull(preparing.snapshot.pendingSourceId)

        assertTrue(preparing.snapshot.isPreparing)
        assertTrue(preparing.effects.any { it.type == AudioPlaybackEffectType.Pause })
        assertTrue(state.play().effects.isEmpty())
        assertTrue(state.pause().effects.isEmpty())
        assertTrue(state.seekAbsolute(10_000).effects.isEmpty())
        assertTrue(state.nextChapter().effects.isEmpty())
        assertTrue(state.selectChapter("chapter-3").effects.isEmpty())
        assertTrue(state.setPlaybackRate(2.0).effects.isEmpty())
        assertTrue(state.setSleepTimer(AudioSleepTimerMode.Minutes15).effects.isEmpty())
        assertEquals(candidate, state.snapshot().pendingSourceId)

        state.enginePrepared(candidate, 60_000)
        state.engineCommitted(candidate)
        assertTrue(!state.snapshot().isPreparing)
        assertEquals(AudioPlaybackEffectType.Play, state.play().effects.single().type)
    }

    @Test
    fun stopWhileBootstrapIsPendingStillRequestsNativeTeardown() {
        val state = AudioPlaybackStateMachine()
        state.beginLaunch(namespace(), "native", AudioLaunchIntent("resource-1", autoplay = true))

        val stopped = state.stop()

        assertEquals(AudioPlaybackStage.Idle, stopped.snapshot.stage)
        assertEquals(AudioPlaybackEffectType.Stop, stopped.effects.single().type)
    }

    @Test
    fun chapterNavigationAbsoluteSeekAndAutoNextUseTheSameRules() {
        val state = AudioPlaybackStateMachine()
        val publication = publication("resource-1", twoTracks = true)
        val firstSource = commit(state, publication, autoplay = true)

        val chapter = state.selectChapter("chapter-2")
        val chapterSeek = chapter.effects.first { it.type == AudioPlaybackEffectType.Seek }
        assertEquals(0, chapter.snapshot.positionMillis)
        assertEquals(30_000, chapter.snapshot.displayedAbsolutePositionMillis)
        assertEquals("chapter-1", chapter.snapshot.currentChapterId)
        assertTrue(chapter.effects.any { it.type == AudioPlaybackEffectType.Pause })
        val chapterCompleted = state.engineSeekCompleted(
            firstSource,
            chapterSeek.operationId,
            30_000,
            60_000,
        )
        assertEquals(30_000, chapterCompleted.snapshot.positionMillis)
        assertEquals("chapter-2", chapterCompleted.snapshot.currentChapterId)
        assertEquals(
            AudioProgressSaveReason.ChapterChange,
            chapterCompleted.effects.first { it.type == AudioPlaybackEffectType.SaveProgress }.progressReason,
        )
        assertTrue(chapterCompleted.effects.any { it.type == AudioPlaybackEffectType.Play })
        state.enginePlaying(firstSource)

        val crossTrack = state.seekAbsolute(75_000)
        val secondSource = requireNotNull(crossTrack.snapshot.pendingSourceId)
        assertNotEquals(firstSource, secondSource)
        assertEquals("asset-1", crossTrack.snapshot.currentAssetId)
        assertEquals(AudioPlaybackEffectType.PrepareSource, crossTrack.effects.last().type)
        state.enginePrepared(secondSource, 60_000)
        state.engineCommitted(secondSource)
        assertEquals("asset-2", state.snapshot().currentAssetId)
        assertEquals(15_000, state.snapshot().positionMillis)

        state.enginePlaying(secondSource)
        val ended = state.engineEnded(secondSource)
        assertEquals(AudioPlaybackStage.Ended, ended.snapshot.stage)
        assertEquals(AudioProgressSaveReason.Completed, ended.effects.single().progressReason)
    }

    @Test
    fun remoteReaderLocationSelectsTrackAndPlaybackPositionInOneTransition() {
        val state = AudioPlaybackStateMachine()
        val publication = publication("resource-1", twoTracks = true)
        commit(state, publication, autoplay = false)

        val navigation = state.goToReaderLocation(AudioReaderLocation("asset-2", null, 12_000))

        assertEquals(AudioPlaybackEffectType.PrepareSource, navigation.effects.last().type)
        val candidate = requireNotNull(navigation.snapshot.pendingSourceId)
        state.enginePrepared(candidate, 60_000)
        state.engineCommitted(candidate)
        assertEquals("asset-2", state.snapshot().currentAssetId)
        assertEquals(12_000, state.snapshot().positionMillis)
    }

    @Test
    fun scrubbingPausesFreezesOldFactsAndResumesOnlyAfterMatchingSeekCompletion() {
        val state = AudioPlaybackStateMachine()
        val source = commit(state, publication("resource-1"), autoplay = true)
        state.enginePosition(source, 10_000, 60_000)

        val began = state.beginScrubbing()
        assertEquals(AudioPlaybackStage.Paused, began.snapshot.stage)
        assertEquals(AudioPlaybackEffectType.Pause, began.effects.single().type)
        state.updateScrubbingPosition(42_000)
        assertEquals(10_000, state.snapshot().absolutePositionMillis)
        assertEquals(42_000, state.snapshot().displayedAbsolutePositionMillis)

        state.enginePosition(source, 11_000, 60_000)
        assertEquals(10_000, state.snapshot().positionMillis)
        val submitted = state.finishScrubbing(42_000)
        val seek = submitted.effects.single { it.type == AudioPlaybackEffectType.Seek }
        assertTrue(submitted.snapshot.isSeeking)
        state.enginePosition(source, 12_000, 60_000)
        assertEquals(10_000, state.snapshot().positionMillis)

        assertTrue(state.engineSeekCompleted(source, seek.operationId + 1, 42_000, 60_000).effects.isEmpty())
        assertEquals(10_000, state.snapshot().positionMillis)
        val completed = state.engineSeekCompleted(source, seek.operationId, 42_000, 60_000)
        assertEquals(42_000, completed.snapshot.positionMillis)
        assertEquals(42_000, completed.snapshot.absolutePositionMillis)
        assertTrue(!completed.snapshot.isSeeking)
        assertEquals(
            listOf(AudioPlaybackEffectType.SaveProgress, AudioPlaybackEffectType.Play),
            completed.effects.map { it.type },
        )
        assertEquals(AudioProgressSaveReason.Seek, completed.effects.first().progressReason)
        assertEquals(AudioProgressSyncState.Pending, completed.snapshot.syncState)
        assertEquals(
            AudioProgressSyncState.Synced,
            state.progressSaved(source, failed = false).snapshot.syncState,
        )
        assertTrue(state.engineSeekCompleted(source, seek.operationId, 42_000, 60_000).effects.isEmpty())
    }

    @Test
    fun failedSeekDropsTheUnconfirmedTargetAndRestoresOnlyPriorPlaybackIntent() {
        val playing = AudioPlaybackStateMachine()
        val playingSource = commit(playing, publication("resource-playing"), autoplay = true)
        playing.enginePosition(playingSource, 9_000, 60_000)
        playing.beginScrubbing()
        playing.updateScrubbingPosition(40_000)
        val playingSeek = playing.finishScrubbing(40_000).effects.single {
            it.type == AudioPlaybackEffectType.Seek
        }

        val failedPlaying = playing.engineSeekFailed(
            playingSource,
            playingSeek.operationId,
            AudioPlaybackError("AUDIO_SEEK_TIMEOUT", recoverable = true),
        )

        assertEquals(9_000, failedPlaying.snapshot.displayedAbsolutePositionMillis)
        assertTrue(!failedPlaying.snapshot.isSeeking)
        assertEquals(AudioPlaybackEffectType.Play, failedPlaying.effects.single().type)

        val paused = AudioPlaybackStateMachine()
        val pausedSource = commit(paused, publication("resource-paused"), autoplay = false)
        paused.enginePosition(pausedSource, 7_000, 60_000)
        paused.beginScrubbing()
        val pausedSeek = paused.finishScrubbing(30_000).effects.single {
            it.type == AudioPlaybackEffectType.Seek
        }
        val failedPaused = paused.engineSeekFailed(
            pausedSource,
            pausedSeek.operationId,
            AudioPlaybackError("AUDIO_SEEK_TIMEOUT", recoverable = true),
        )

        assertEquals(7_000, failedPaused.snapshot.displayedAbsolutePositionMillis)
        assertTrue(failedPaused.effects.isEmpty())
    }

    @Test
    fun delayedTransportFactsCannotUndoThePlaybackIntentChosenForACompletedSeek() {
        val playing = AudioPlaybackStateMachine()
        val playingSource = commit(playing, publication("resource-playing"), autoplay = true)
        playing.beginScrubbing()
        val playingSeek = playing.finishScrubbing(25_000).effects.single {
            it.type == AudioPlaybackEffectType.Seek
        }
        playing.engineSeekCompleted(playingSource, playingSeek.operationId, 25_000, 60_000)

        assertTrue(playing.enginePaused(playingSource).effects.isEmpty())
        assertEquals(AudioPlaybackStage.Paused, playing.snapshot().stage)
        assertEquals(AudioPlaybackStage.Playing, playing.enginePlaying(playingSource).snapshot.stage)

        val paused = AudioPlaybackStateMachine()
        val pausedSource = commit(paused, publication("resource-paused"), autoplay = false)
        paused.beginScrubbing()
        val pausedSeek = paused.finishScrubbing(30_000).effects.single {
            it.type == AudioPlaybackEffectType.Seek
        }
        paused.engineSeekCompleted(pausedSource, pausedSeek.operationId, 30_000, 60_000)

        assertEquals(AudioPlaybackStage.Paused, paused.enginePlaying(pausedSource).snapshot.stage)
        assertEquals(AudioPlaybackStage.Paused, paused.engineBuffering(pausedSource).snapshot.stage)
        assertEquals(AudioPlaybackEffectType.Play, paused.play().effects.single().type)
        assertEquals(AudioPlaybackStage.Playing, paused.enginePlaying(pausedSource).snapshot.stage)
    }

    @Test
    fun mediaEngineReloadDuringSeekCommitsTheTargetAndDoesNotLeaveCommandsLocked() {
        val state = AudioPlaybackStateMachine()
        val oldSource = commit(state, publication("resource-reload"), autoplay = true)
        state.enginePosition(oldSource, 8_000, 60_000)
        state.beginScrubbing()
        state.updateScrubbingPosition(36_000)
        val oldSeek = state.finishScrubbing(36_000).effects.single {
            it.type == AudioPlaybackEffectType.Seek
        }

        val reloading = state.reloadCurrentSource()
        val candidate = requireNotNull(reloading.snapshot.pendingSourceId)

        assertEquals(36_000, reloading.snapshot.displayedAbsolutePositionMillis)
        assertEquals(AudioPlaybackEffectType.PrepareSource, reloading.effects.last().type)
        assertTrue(state.engineSeekCompleted(oldSource, oldSeek.operationId, 36_000, 60_000).effects.isEmpty())
        val commit = state.enginePrepared(candidate, 60_000).effects.single()
        assertEquals(AudioPlaybackEffectType.CommitPreparedSource, commit.type)
        assertEquals(36_000, commit.positionMillis)
        assertTrue(commit.autoplay)

        val committed = state.engineCommitted(candidate)

        assertEquals(36_000, committed.snapshot.positionMillis)
        assertTrue(!committed.snapshot.hasPendingSeekInteraction)
        assertEquals(AudioProgressSaveReason.Seek, committed.effects.single().progressReason)
        assertEquals(AudioPlaybackEffectType.Pause, state.pause().effects.single().type)
    }

    @Test
    fun pausedScrubbingDoesNotAutoplayAndCrossTrackScrubbingKeepsTheTargetVisible() {
        val paused = AudioPlaybackStateMachine()
        val pausedSource = commit(paused, publication("resource-1"), autoplay = false)
        assertTrue(paused.beginScrubbing().effects.isEmpty())
        paused.updateScrubbingPosition(20_000)
        val pausedSeek = paused.finishScrubbing(20_000).effects.single {
            it.type == AudioPlaybackEffectType.Seek
        }
        val pausedCompleted = paused.engineSeekCompleted(
            pausedSource,
            pausedSeek.operationId,
            20_000,
            60_000,
        )
        assertTrue(pausedCompleted.effects.none { it.type == AudioPlaybackEffectType.Play })

        val playing = AudioPlaybackStateMachine()
        commit(playing, publication("resource-2", twoTracks = true), autoplay = true)
        playing.beginScrubbing()
        playing.updateScrubbingPosition(75_000)
        val preparing = playing.finishScrubbing(75_000)
        val candidate = requireNotNull(preparing.snapshot.pendingSourceId)
        assertEquals(75_000, preparing.snapshot.displayedAbsolutePositionMillis)
        assertEquals("asset-1", preparing.snapshot.currentAssetId)
        val ready = playing.enginePrepared(candidate, 60_000)
        assertTrue(ready.effects.single().autoplay)
        val committed = playing.engineCommitted(candidate)
        assertEquals("asset-2", committed.snapshot.currentAssetId)
        assertEquals(15_000, committed.snapshot.positionMillis)
        assertEquals(75_000, committed.snapshot.absolutePositionMillis)
        val saved = committed.effects.single { it.type == AudioPlaybackEffectType.SaveProgress }
        assertEquals(AudioProgressSaveReason.Seek, saved.progressReason)
        assertEquals(15_000, saved.positionMillis)
    }

    @Test
    fun engineEndPreparesAndCommitsTheNextTrackExactlyOnce() {
        val state = AudioPlaybackStateMachine()
        val publication = publication("resource-1", twoTracks = true)
        val firstSource = commit(state, publication, autoplay = true)

        val ended = state.engineEnded(firstSource)
        val candidate = requireNotNull(ended.snapshot.pendingSourceId)
        assertEquals(AudioPlaybackStage.Ended, ended.snapshot.stage)
        assertEquals("asset-1", ended.snapshot.currentAssetId)
        assertEquals(AudioProgressSaveReason.TrackChange, ended.effects.first().progressReason)
        assertEquals(AudioPlaybackEffectType.PrepareSource, ended.effects.last().type)
        assertTrue(state.engineEnded(firstSource).effects.isEmpty())

        state.enginePrepared(candidate, 60_000)
        state.engineCommitted(candidate)
        state.enginePlaying(candidate)
        assertEquals("asset-2", state.snapshot().currentAssetId)
        assertEquals(AudioPlaybackStage.Playing, state.snapshot().stage)
    }

    @Test
    fun endOfChapterSleepPausesOnceAndPreventsAutoNext() {
        var now = 1_000L
        val state = AudioPlaybackStateMachine(nowEpochMillis = { now })
        val source = commit(state, publication("resource-1", twoTracks = true), autoplay = true)
        state.setSleepTimer(AudioSleepTimerMode.EndOfChapter)

        val beforeBoundary = state.enginePosition(source, 29_999, 60_000)
        assertTrue(beforeBoundary.effects.none { it.type == AudioPlaybackEffectType.Pause })
        val boundary = state.enginePosition(source, 30_000, 60_000)
        assertEquals(AudioPlaybackEffectType.Pause, boundary.effects.single().type)
        assertEquals(AudioSleepTimerMode.Off, boundary.snapshot.sleepTimerMode)

        now += 60_000
        val duplicate = state.enginePosition(source, 30_500, 60_000)
        assertTrue(duplicate.effects.none { it.type == AudioPlaybackEffectType.Pause })
    }

    @Test
    fun minuteTimerAndProgressCadenceAreDrivenByInjectedClock() {
        var now = 10_000L
        val state = AudioPlaybackStateMachine(nowEpochMillis = { now })
        val source = commit(state, publication("resource-1"), autoplay = true)
        state.setSleepTimer(AudioSleepTimerMode.Minutes15)

        now += 14_999
        assertTrue(state.enginePosition(source, 1_000, 60_000).effects.isEmpty())
        now += 1
        val tick = state.enginePosition(source, 2_000, 60_000)
        assertEquals(AudioProgressSaveReason.Tick, tick.effects.single().progressReason)

        now = 10_000L + 15 * 60_000L
        val timer = state.sleepTimerElapsed(now)
        assertEquals(AudioPlaybackEffectType.Pause, timer.effects.single().type)
        assertEquals(AudioSleepTimerMode.Off, timer.snapshot.sleepTimerMode)
    }

    @Test
    fun minuteTimerUsesMonotonicTimeWhenWallClockChanges() {
        var wallClock = 10_000L
        var monotonicClock = 1_000L
        val state = AudioPlaybackStateMachine(
            nowEpochMillis = { wallClock },
            nowMonotonicMillis = { monotonicClock },
        )
        val source = commit(state, publication("resource-1"), autoplay = true)
        state.setSleepTimer(AudioSleepTimerMode.Minutes15)

        wallClock += 24 * 60 * 60_000L
        monotonicClock += 14 * 60_000L
        val early = state.enginePosition(source, 10_000, 60_000)
        assertTrue(early.effects.none { it.type == AudioPlaybackEffectType.Pause })

        monotonicClock += 60_000L
        val elapsed = state.enginePosition(source, 11_000, 60_000)
        assertEquals(AudioPlaybackEffectType.Pause, elapsed.effects.single().type)
    }

    private fun commit(
        state: AudioPlaybackStateMachine,
        publication: AudioPublication,
        autoplay: Boolean,
    ): Long {
        val launch = state.beginLaunch(
            publication.namespace,
            "native",
            AudioLaunchIntent(publication.resource.resourceId, autoplay = autoplay),
        )
        val preparation = state.publicationLoaded(launch.token, publication, null)
        val sourceId = requireNotNull(preparation.snapshot.pendingSourceId)
        state.enginePrepared(sourceId, publication.assets.first().durationMillis)
        state.engineCommitted(sourceId)
        if (autoplay) state.enginePlaying(sourceId) else state.enginePaused(sourceId)
        return sourceId
    }

    private fun publication(resourceId: String, twoTracks: Boolean = false): AudioPublication {
        val assets = buildList {
            add(asset(resourceId, "asset-1", 0))
            if (twoTracks) add(asset(resourceId, "asset-2", 1))
        }
        val chapters = buildList {
            add(AudioChapter("chapter-1", "asset-1", 0, "One", 0, 30_000))
            add(AudioChapter("chapter-2", "asset-1", 1, "Two", 30_000, 60_000))
            if (twoTracks) add(AudioChapter("chapter-3", "asset-2", 2, "Three", 0, 60_000))
        }
        return AudioPublication(
            namespace = namespace(),
            bookId = "book-1",
            bookTitle = "Book",
            author = "Author",
            coverApiPath = "/api/books/book-1/cover",
            resource = AudioResource(
                resourceId,
                "Volume",
                ReaderSourceFormat.M4b,
                0,
                assets.size * 60_000L,
                assets.size,
                chapters.size,
            ),
            availableResources = emptyList(),
            assets = assets,
            chapters = chapters,
        )
    }

    private fun asset(resourceId: String, assetId: String, order: Int) = AudioAsset(
        assetId = assetId,
        resourceId = resourceId,
        title = "Track ${order + 1}",
        apiPath = "/api/assets/$assetId",
        mimeType = "audio/mp4",
        sizeBytes = 1_000,
        durationMillis = 60_000,
        discNumber = 1,
        trackNumber = order + 1,
        sortOrder = order,
        codec = "aac",
    )

    private fun namespace() = ReaderSyncNamespace("server-1", "user-1", 2)
}
