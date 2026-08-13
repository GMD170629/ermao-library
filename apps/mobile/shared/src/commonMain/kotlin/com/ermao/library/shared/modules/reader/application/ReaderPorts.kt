package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.EngineLocator
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderSource
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.domain.exactLocatorEnvelope
import com.ermao.library.shared.modules.reader.domain.compareExactReadiumBlocks
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
) {
    init {
        require(title.isNotBlank()) { "Reader table-of-contents title is blank" }
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

    data class PdfPage(val pageNumber: Int) : ReaderRestoreCandidate

    data class ComicPage(val pageIndex: Int) : ReaderRestoreCandidate

    data class AudioPosition(val fileId: String, val chapterId: String?, val positionMillis: Long) :
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

/**
 * Chooses the newest fingerprint-compatible exact position. Equal timestamps
 * intentionally prefer the server, and semantically identical anchors never
 * produce a redundant alternative prompt.
 */
fun decideReaderResume(
    localProgress: ReaderProgress?,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): ReaderResumeDecision {
    val validLocal = localProgress?.takeIf {
        it.sourceId == openedSource.sourceId &&
            it.location.contentFingerprint == openedSource.contentFingerprint &&
            runCatching { it.exactLocatorEnvelope() }.isSuccess
    }
    val validRemote = remoteSnapshot?.takeIf {
        it.sourceId == openedSource.sourceId &&
            it.locator.publication.toContentFingerprint() == openedSource.contentFingerprint
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
    val sameAnchor = compareExactReadiumBlocks(
        validLocal.exactLocatorEnvelope(),
        validRemote.locator,
    ) == com.ermao.library.shared.modules.reader.domain.ExactBlockMatch.Exact
    val selected = if (localTarget.capturedAtEpochMillis > remoteTarget.capturedAtEpochMillis) {
        localTarget
    } else {
        remoteTarget
    }
    if (sameAnchor) return ReaderResumeDecision(selected, null)
    return ReaderResumeDecision(
        selected = selected,
        alternative = if (selected.source == ReaderResumeSource.Local) remoteTarget else localTarget,
    )
}

/**
 * Restores only exact locations. A durable local location wins because an
 * unresolved pending mutation/conflict must never be silently replaced by a
 * remote revision. A fresh device without local state may use the server's
 * exact Readium Locator after the three-part Publication fingerprint matches.
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
            listOf(ReaderRestoreCandidate.PublicEngineLocator(selected.remoteSnapshot.locator.asEngineLocator())),
            usesLocalExact = false,
        )
    } else {
        ReaderProgressRestorePlan(null, null, emptyList(), usesLocalExact = false)
    }
}

fun restoreCandidates(snapshot: ReaderProgressSnapshotV4): List<ReaderRestoreCandidate> =
    listOf(ReaderRestoreCandidate.PublicEngineLocator(snapshot.locator.asEngineLocator()))

fun restoreCandidates(
    savedLocation: ReaderLocation,
    openedSource: ReaderSource,
): List<ReaderRestoreCandidate> {
    val reflow = savedLocation as? com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
        ?: return emptyList()
    if (reflow.contentFingerprint != openedSource.contentFingerprint) return emptyList()
    if (com.ermao.library.shared.modules.reader.domain.ReadiumLocatorEnvelope.from(reflow) == null) return emptyList()
    return listOf(ReaderRestoreCandidate.ExactEngineLocation(reflow))
}
