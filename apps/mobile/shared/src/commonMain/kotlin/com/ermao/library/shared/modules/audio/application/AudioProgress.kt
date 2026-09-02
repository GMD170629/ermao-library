package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.AudioPublicationLocation
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderProgressSyncRuntime
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore
import com.ermao.library.shared.modules.reader.decidePendingVsServerStartup
import com.ermao.library.shared.modules.reader.decideReaderResume
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.reader.application.PendingVsServerDecision
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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

/** Persists captures selected by the shared state machine through Reader v4 local-first storage. */
class AudioProgressWriter(
    private val store: ReaderProgressSyncingStore,
    private val resourceId: String,
    private val deviceId: String,
    private val nowEpochMillis: () -> Long,
) {
    suspend fun save(
        assetId: String,
        chapterId: String?,
        positionMillis: Long,
        durationMillis: Long?,
        reason: AudioProgressSaveReason,
    ) {
        val now = nowEpochMillis()
        require(now >= 0 && positionMillis >= 0)
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
    }

    suspend fun restore(): AudioReaderLocation? =
        store.load(resourceId)?.location as? AudioReaderLocation

    suspend fun restoreProgress(): ReaderProgress? = store.load(resourceId)
}

/**
 * One session-scoped use case for audio progress restore and persistence.
 *
 * It reuses Reader v4's newest-exact-location decision and serializes local-first writes inside
 * KMP. Native runtimes do not throttle, merge, or arbitrate progress values.
 */
class AudioProgressSession(
    private val writer: AudioProgressWriter,
    private val syncRuntime: ReaderProgressSyncRuntime? = null,
    private val syncTarget: ReaderProgressSyncTarget? = null,
) {
    private val mutex = Mutex()

    init {
        require((syncRuntime == null) == (syncTarget == null))
    }

    suspend fun restore(
        publication: AudioPublication,
        remoteSnapshot: ReaderProgressSnapshotV4?,
    ): AudioReaderLocation? = mutex.withLock {
        val local = writer.restoreProgress()?.takeIf { progress ->
            (progress.location as? AudioReaderLocation)?.isValidFor(publication) == true
        }
        val remote = remoteSnapshot?.takeIf { snapshot ->
            (snapshot.locator as? AudioPublicationLocation)?.isValidFor(publication) == true
        }
        val source = LocalReaderSource(
            resourceId = publication.resource.resourceId,
            displayTitle = publication.resource.title,
            format = ReaderFormat.Audio,
            bookId = publication.bookId,
            sourceFormat = publication.resource.sourceFormat,
        )
        val startupDecision = if (syncRuntime != null && syncTarget != null) {
            try {
                decidePendingVsServerStartup(
                    localProgress = local,
                    durableState = syncRuntime.store.syncState(),
                    remoteSnapshot = remote,
                    openedSource = source,
                ).also { decision ->
                    syncRuntime.coordinator.applyStartupDecision(syncTarget, decision)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null
            }
        } else {
            null
        }
        val selected = when (startupDecision) {
            is PendingVsServerDecision.UseLocalPending ->
                decideReaderResume(startupDecision.progress, null, source).selected
            is PendingVsServerDecision.UseServer ->
                decideReaderResume(local, startupDecision.snapshot, source).selected
            null -> decideReaderResume(local, remote, source).selected
        }
        val location = when {
            selected?.localProgress != null -> selected.localProgress.location as? AudioReaderLocation
            selected?.remoteSnapshot?.locator is AudioPublicationLocation -> {
                val remote = selected.remoteSnapshot.locator
                AudioReaderLocation(remote.assetId, remote.chapterId, remote.positionMillis)
            }
            else -> null
        }
        location
    }

    suspend fun save(
        assetId: String,
        chapterId: String?,
        positionMillis: Long,
        durationMillis: Long?,
        reason: AudioProgressSaveReason,
    ) = mutex.withLock {
        writer.save(assetId, chapterId, positionMillis, durationMillis, reason)
    }
}

private fun AudioReaderLocation.isValidFor(publication: AudioPublication): Boolean =
    publication.assets.any { it.assetId == assetId } &&
        (chapterId == null || publication.chapters.any {
            it.chapterId == chapterId && it.assetId == assetId
        })

private fun AudioPublicationLocation.isValidFor(publication: AudioPublication): Boolean =
    publication.assets.any { it.assetId == assetId } &&
        (chapterId == null || publication.chapters.any {
            it.chapterId == chapterId && it.assetId == assetId
        })
