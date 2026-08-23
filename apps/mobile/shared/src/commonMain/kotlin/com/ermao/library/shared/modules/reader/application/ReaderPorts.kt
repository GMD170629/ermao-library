package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.EngineLocator
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderSource
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.domain.exactLocatorEnvelope
import com.ermao.library.shared.modules.reader.domain.AudioPublicationLocation
import com.ermao.library.shared.modules.reader.domain.AudioReaderLocation
import com.ermao.library.shared.modules.reader.domain.ComicPublicationLocation
import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import com.ermao.library.shared.modules.reader.domain.ExactLocationMatch
import com.ermao.library.shared.modules.reader.domain.PdfPublicationLocation
import com.ermao.library.shared.modules.reader.domain.PdfReaderLocation
import com.ermao.library.shared.modules.reader.domain.PublicationLocation
import com.ermao.library.shared.modules.reader.domain.ReflowablePublicationLocation
import com.ermao.library.shared.modules.reader.domain.compareExactProgressLocations
import com.ermao.library.shared.modules.reader.domain.exactPublicationLocation
import kotlinx.coroutines.flow.StateFlow

interface ReaderProgressStore {
    suspend fun load(sourceId: String): ReaderProgress?

    suspend fun save(progress: ReaderProgress)

    suspend fun delete(sourceId: String)
}

fun interface ReaderClock {
    fun nowEpochMillis(): Long
}

fun interface ReaderDeviceIdentity {
    fun stableDeviceId(): String
}

data class ReaderOpenRequest(
    val source: ReaderSource,
    val initialLocation: ReaderLocation?,
    val initialPreferences: ReaderPreferences,
)

data class ReaderTocEntry(
    val title: String,
    val location: ReaderLocation,
    val children: List<ReaderTocEntry> = emptyList(),
    val id: String = title,
    val index: Int = 0,
    val target: ReaderNavigationTarget = ReaderNavigationTarget.from(location),
) {
    init {
        require(title.isNotBlank()) { "Reader table-of-contents title is blank" }
    }
}

sealed interface ReaderNavigationTarget {
    data class Reflowable(val href: String) : ReaderNavigationTarget
    data class Pdf(val pageIndex: Int) : ReaderNavigationTarget
    data class Comic(val pageIndex: Int, val resourceHref: String) : ReaderNavigationTarget
    data class Invalid(val reasonCode: String = "READER_NAVIGATION_TARGET_INVALID") : ReaderNavigationTarget

    companion object {
        fun from(location: ReaderLocation): ReaderNavigationTarget = when (location) {
            is ReflowReaderLocation -> location.resourceKey
                ?.let(ReaderNavigationTarget::Reflowable)
                ?: Invalid()
            is com.ermao.library.shared.modules.reader.domain.PdfReaderLocation -> Pdf(location.pageIndex)
            is ComicReaderLocation -> Comic(location.pageIndex, location.resourceHref)
            else -> Invalid()
        }
    }
}

sealed interface ReaderNavigationResult {
    data class Completed(val moved: Boolean) : ReaderNavigationResult
    data class Rejected(val reasonCode: String) : ReaderNavigationResult {
        init {
            require(reasonCode.isNotBlank())
        }
    }
}

sealed interface ReaderCommandResult {
    data object Completed : ReaderCommandResult

    data class Rejected(val reasonCode: String) : ReaderCommandResult {
        init {
            require(reasonCode.isNotBlank()) { "Reader rejection reason is blank" }
        }
    }
}

interface ReaderEnginePort {
    val currentLocation: StateFlow<ReaderLocation?>
    val preferences: StateFlow<ReaderPreferences>

    suspend fun open(request: ReaderOpenRequest): ReaderCommandResult

    suspend fun goPrevious(): ReaderCommandResult

    suspend fun goNext(): ReaderCommandResult

    suspend fun goTo(location: ReaderLocation): ReaderCommandResult

    suspend fun tableOfContents(): List<ReaderTocEntry>

    suspend fun updatePreferences(preferences: ReaderPreferences): ReaderCommandResult

    suspend fun close()
}

sealed interface ReaderRestoreCandidate {
    data class ExactLocalLocation(val location: ReaderLocation) : ReaderRestoreCandidate

    data class ExactEngineLocation(val location: ReaderLocation) : ReaderRestoreCandidate

    data class PublicEngineLocator(val locator: EngineLocator) : ReaderRestoreCandidate

    data class ResourceProgression(val resourceKey: String, val progression: Double?) : ReaderRestoreCandidate

    data class QuotedText(val exact: String, val prefix: String?, val suffix: String?) : ReaderRestoreCandidate

    data class Position(val position: Int) : ReaderRestoreCandidate

    data class PdfPage(val pageIndex: Int, val pageProgression: Double) : ReaderRestoreCandidate

    data class ComicPage(val resourceHref: String, val pageIndex: Int) : ReaderRestoreCandidate

    data class AudioPosition(val assetId: String, val chapterId: String?, val positionMillis: Long) :
        ReaderRestoreCandidate

    data class TotalProgression(val progression: Double) : ReaderRestoreCandidate
}

data class ReaderProgressRestorePlan(
    val localProgress: ReaderProgress?,
    val remoteSnapshot: ReaderProgressSnapshotV4?,
    val candidates: List<ReaderRestoreCandidate>,
    val usesLocalExact: Boolean,
) {
    init {
        require(localProgress == null || remoteSnapshot == null) { "Reader restore plan has two owners" }
        require((localProgress != null || remoteSnapshot != null) || candidates.isEmpty())
    }

}

enum class ReaderResumeSource { Local, Server }

data class ReaderResumeTarget(
    val source: ReaderResumeSource,
    val capturedAtEpochMillis: Long,
    val displayPercent: Double,
    val localProgress: ReaderProgress? = null,
    val remoteSnapshot: ReaderProgressSnapshotV4? = null,
) {
    init {
        require(capturedAtEpochMillis >= 0)
        require(displayPercent.isFinite() && displayPercent in 0.0..100.0)
        require((localProgress != null) != (remoteSnapshot != null))
    }
}

data class ReaderResumeDecision(
    val selected: ReaderResumeTarget?,
    val alternative: ReaderResumeTarget?,
) {
    init {
        require(selected != null || alternative == null)
        require(alternative == null || selected?.source != alternative.source)
    }
}

/** Selects the newest valid position. Server wins ties; neither candidate can block opening. */
fun decideReaderResume(
    localProgress: ReaderProgress?,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): ReaderResumeDecision {
    val validLocal = localProgress?.takeIf {
        it.resourceId == openedSource.resourceId &&
            runCatching { it.exactPublicationLocation() }.isSuccess
    }
    val validRemote = remoteSnapshot?.takeIf {
        it.resourceId == openedSource.resourceId
    }
    val localTarget = validLocal?.let {
        ReaderResumeTarget(
            source = ReaderResumeSource.Local,
            capturedAtEpochMillis = it.updatedAtEpochMillis,
            displayPercent = it.percent
                ?: (it.location as? ReflowReaderLocation)?.totalProgression?.times(100)
                ?: 0.0,
            localProgress = it,
        )
    }
    val remoteTarget = validRemote?.let {
        ReaderResumeTarget(
            source = ReaderResumeSource.Server,
            capturedAtEpochMillis = it.effectiveCapturedAtEpochMillis,
            displayPercent = it.displayPercent,
            remoteSnapshot = it,
        )
    }
    if (localTarget == null) return ReaderResumeDecision(remoteTarget, null)
    if (remoteTarget == null) return ReaderResumeDecision(localTarget, null)
    val sameLocation = runCatching {
        compareExactProgressLocations(
            requireNotNull(localTarget.localProgress).exactPublicationLocation(),
            requireNotNull(remoteTarget.remoteSnapshot).locator,
        ) == ExactLocationMatch.Exact
    }.getOrDefault(false)
    val selected = if (remoteTarget.capturedAtEpochMillis >= localTarget.capturedAtEpochMillis) {
        remoteTarget
    } else {
        localTarget
    }
    val alternative = if (sameLocation) null else if (selected === remoteTarget) localTarget else remoteTarget
    return ReaderResumeDecision(selected, alternative)
}

sealed interface PendingVsServerDecision {
    data class UseServer(
        val snapshot: ReaderProgressSnapshotV4?,
        val discardPending: Boolean = false,
    ) : PendingVsServerDecision

    data class UseLocalPending(
        val progress: ReaderProgress,
        val mutation: com.ermao.library.shared.modules.reader.domain.ReaderProgressMutation,
    ) : PendingVsServerDecision

}

/** Startup decision used after a fresh bootstrap. Confirmed local history is intentionally ignored. */
fun decidePendingVsServerStartup(
    localProgress: ReaderProgress?,
    durableState: ReaderProgressDurableState,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): PendingVsServerDecision {
    val pending = durableState.pending ?: return PendingVsServerDecision.UseServer(remoteSnapshot)
    val validLocal = localProgress?.takeIf {
        it.resourceId == openedSource.resourceId &&
            runCatching { it.exactPublicationLocation() }.isSuccess &&
            runCatching {
                compareExactProgressLocations(it.exactPublicationLocation(), pending.locator) == ExactLocationMatch.Exact
            }.getOrDefault(false)
    }
    if (validLocal == null) {
        return PendingVsServerDecision.UseServer(remoteSnapshot, discardPending = true)
    }
    if (remoteSnapshot == null || pending.baseRevision == remoteSnapshot.revision) {
        return PendingVsServerDecision.UseLocalPending(validLocal, pending)
    }
    return if (
        remoteSnapshot.revision > pending.baseRevision &&
        remoteSnapshot.effectiveCapturedAtEpochMillis >= validLocal.updatedAtEpochMillis
    ) {
        PendingVsServerDecision.UseServer(remoteSnapshot, discardPending = true)
    } else {
        PendingVsServerDecision.UseLocalPending(validLocal, pending)
    }
}

/**
 * Restores only exact locations. Online startup uses the bootstrap snapshot;
 * callers handle a durable pending mutation with [decidePendingVsServerStartup].
 */
fun planReaderProgressRestore(
    localProgress: ReaderProgress?,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): ReaderProgressRestorePlan {
    val selected = decideReaderResume(localProgress, remoteSnapshot, openedSource).selected
    return if (selected?.localProgress != null) {
        ReaderProgressRestorePlan(
            localProgress = selected.localProgress,
            remoteSnapshot = null,
            candidates = listOf(ReaderRestoreCandidate.ExactLocalLocation(selected.localProgress.location)),
            usesLocalExact = true,
        )
    } else if (selected?.remoteSnapshot != null) {
        ReaderProgressRestorePlan(
            null,
            selected.remoteSnapshot,
            restoreCandidates(selected.remoteSnapshot),
            usesLocalExact = false,
        )
    } else {
        ReaderProgressRestorePlan(null, null, emptyList(), usesLocalExact = false)
    }
}

fun restoreCandidates(snapshot: ReaderProgressSnapshotV4): List<ReaderRestoreCandidate> =
    when (val location = snapshot.locator) {
        is ReflowablePublicationLocation -> listOf(ReaderRestoreCandidate.PublicEngineLocator(location.engineLocator))
        is PdfPublicationLocation -> listOf(ReaderRestoreCandidate.PdfPage(location.pageIndex, location.pageProgression))
        is ComicPublicationLocation -> listOf(ReaderRestoreCandidate.ComicPage(location.resourceHref, location.pageIndex))
        is AudioPublicationLocation -> listOf(
            ReaderRestoreCandidate.AudioPosition(location.assetId, location.chapterId, location.positionMillis),
        )
    }

fun restoreCandidates(
    savedLocation: ReaderLocation,
    openedSource: ReaderSource,
): List<ReaderRestoreCandidate> {
    return when (savedLocation) {
        is ReflowReaderLocation -> if (
            com.ermao.library.shared.modules.reader.domain.ReadiumLocatorEnvelope.from(savedLocation) != null
        ) listOf(ReaderRestoreCandidate.ExactEngineLocation(savedLocation)) else emptyList()
        is PdfReaderLocation -> listOf(ReaderRestoreCandidate.PdfPage(savedLocation.pageIndex, savedLocation.pageProgression))
        is ComicReaderLocation -> listOf(ReaderRestoreCandidate.ComicPage(savedLocation.resourceHref, savedLocation.pageIndex))
        is AudioReaderLocation -> listOf(
            ReaderRestoreCandidate.AudioPosition(
                savedLocation.assetId,
                savedLocation.chapterId,
                savedLocation.positionMillis,
            ),
        )
    }
}
