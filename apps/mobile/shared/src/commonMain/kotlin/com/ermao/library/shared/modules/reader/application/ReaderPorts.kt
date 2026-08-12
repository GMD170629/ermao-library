package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.EngineLocator
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderProgress
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.domain.ReaderSource
import com.ermao.library.shared.modules.reader.domain.projectedPercent
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

/**
 * Chooses ownership only by the client event timestamp. A local tie wins so
 * the same client keeps its exact engine location. A newer server snapshot is
 * restored only through public candidates and is never persisted as fake exact
 * local progress.
 */
fun planReaderProgressRestore(
    localProgress: ReaderProgress?,
    remoteSnapshot: ReaderProgressSnapshotV4?,
    openedSource: ReaderSource,
): ReaderProgressRestorePlan {
    val validLocal = localProgress?.takeIf { it.sourceId == openedSource.sourceId }
    val validRemote = remoteSnapshot?.takeIf { it.sourceId == openedSource.sourceId }
    return if (validLocal != null && (validRemote == null || validLocal.updatedAtEpochMillis >= validRemote.updatedAtEpochMillis)) {
        val exactFingerprint =
            validLocal.location.contentFingerprint.originalFileHash == openedSource.contentFingerprint.originalFileHash
        ReaderProgressRestorePlan(
            localProgress = validLocal,
            remoteSnapshot = null,
            candidates = if (exactFingerprint) {
                if (validLocal.location is com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation) {
                    restoreCandidates(validLocal.location, openedSource)
                } else {
                    listOf(ReaderRestoreCandidate.ExactLocalLocation(validLocal.location))
                }
            } else {
                listOf(ReaderRestoreCandidate.TotalProgression(validLocal.projectedPercent() / 100.0))
            },
            usesLocalExact = exactFingerprint,
        )
    } else if (validRemote != null) {
        val fingerprintMatches = validRemote.anchor?.contentFingerprint?.originalFileHash
            ?.let { it == openedSource.contentFingerprint.originalFileHash }
            ?: true
        ReaderProgressRestorePlan(
            null,
            validRemote,
            if (fingerprintMatches) restoreCandidates(validRemote) else {
                listOf(ReaderRestoreCandidate.TotalProgression(validRemote.percent / 100.0))
            },
            usesLocalExact = false,
        )
    } else {
        ReaderProgressRestorePlan(null, null, emptyList(), usesLocalExact = false)
    }
}

fun restoreCandidates(snapshot: ReaderProgressSnapshotV4): List<ReaderRestoreCandidate> = buildList {
    snapshot.anchor?.let { anchor ->
        when (anchor.format) {
            com.ermao.library.shared.modules.reader.domain.ReaderFormat.Pdf ->
                run {
                    anchor.engineLocator?.let { add(ReaderRestoreCandidate.PublicEngineLocator(it)) }
                    add(ReaderRestoreCandidate.PdfPage(checkNotNull(anchor.pageNumber)))
                }
            com.ermao.library.shared.modules.reader.domain.ReaderFormat.Comic ->
                run {
                    anchor.engineLocator?.let { add(ReaderRestoreCandidate.PublicEngineLocator(it)) }
                    add(ReaderRestoreCandidate.ComicPage(checkNotNull(anchor.pageNumber)))
                }
            com.ermao.library.shared.modules.reader.domain.ReaderFormat.Audio ->
                run {
                    anchor.engineLocator?.let { add(ReaderRestoreCandidate.PublicEngineLocator(it)) }
                    add(ReaderRestoreCandidate.AudioPosition(
                        checkNotNull(anchor.fileId),
                        anchor.chapterId,
                        checkNotNull(anchor.positionMillis),
                    ))
                }
            else -> {
                anchor.engineLocator?.let { add(ReaderRestoreCandidate.PublicEngineLocator(it)) }
                anchor.resourceKey?.let {
                    add(ReaderRestoreCandidate.ResourceProgression(it, anchor.progression))
                }
                anchor.textQuote?.let { quote ->
                    add(ReaderRestoreCandidate.QuotedText(quote.exact, quote.prefix, quote.suffix))
                }
                anchor.position?.let { add(ReaderRestoreCandidate.Position(it)) }
            }
        }
    }
    add(ReaderRestoreCandidate.TotalProgression((snapshot.percent / 100.0).coerceIn(0.0, 1.0)))
}

fun restoreCandidates(
    savedLocation: ReaderLocation,
    openedSource: ReaderSource,
): List<ReaderRestoreCandidate> {
    val reflow = savedLocation as? com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
        ?: return emptyList()
    return buildList {
        if (reflow.contentFingerprint == openedSource.contentFingerprint && reflow.engineLocator != null) {
            add(ReaderRestoreCandidate.ExactEngineLocation(reflow))
        }
        if (reflow.resourceKey != null) {
            add(ReaderRestoreCandidate.ResourceProgression(reflow.resourceKey, reflow.progression))
        }
        reflow.textQuote?.let { quote ->
            add(ReaderRestoreCandidate.QuotedText(quote.exact, quote.prefix, quote.suffix))
        }
        reflow.position?.let { add(ReaderRestoreCandidate.Position(it)) }
        reflow.totalProgression?.let { add(ReaderRestoreCandidate.TotalProgression(it)) }
    }
}
