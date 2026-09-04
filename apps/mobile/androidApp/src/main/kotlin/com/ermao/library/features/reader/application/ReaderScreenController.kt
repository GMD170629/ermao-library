package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderNavigationResult
import com.ermao.library.shared.modules.reader.ReaderNavigationTarget
import com.ermao.library.shared.modules.reader.ReaderCommandResult
import com.ermao.library.shared.modules.reader.ReaderCommandCompleted
import com.ermao.library.shared.modules.reader.ReaderCommandRejected
import com.ermao.library.shared.modules.reader.ReaderNavigationCompleted
import com.ermao.library.shared.modules.reader.ReaderNavigationRejected
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetComic
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetInvalid
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetPdf
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReaderBookmark
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull

internal data class ReaderResumeNotice(
    val capturedAtEpochMillis: Long,
    val percent: Double,
    val chapterLabel: String?,
    val pageNumber: Int? = null,
)

internal data class ReaderBookmarkChange(
    val bookmarkId: String,
    val added: Boolean,
)

internal data class ReaderAdjacentChapters(
    val previous: ReaderTocEntry? = null,
    val next: ReaderTocEntry? = null,
)

internal data class ReaderTocNode(
    val entry: ReaderTocEntry,
    val depth: Int,
)

internal class ReaderPreferenceSaveFailure(cause: Throwable? = null) : RuntimeException("Reader preference persistence failed", cause)

internal interface ReaderScreenController {
    val requestedNavigationTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? get() = null
    val morphology: ReaderMorphology
    val capabilities: ReaderCapabilities
    val currentLocation: StateFlow<ReaderLocation?>
    /** Renderer-owned display progress when it cannot be inferred from the exact locator. */
    val presentationProgress: StateFlow<Double?>? get() = null
    val preferences: StateFlow<ReaderPreferences>
    val contentError: StateFlow<ReaderError?>? get() = null
    val resumeNotice: StateFlow<ReaderResumeNotice?>
    val resumeActionFailed: StateFlow<Boolean>
    val bookmarks: StateFlow<List<ReaderBookmark>>
    val bookmarkSyncPending: StateFlow<Boolean>
    val tableOfContents: List<ReaderTocEntry>

    suspend fun loadTableOfContents(): List<ReaderTocEntry> = tableOfContents

    fun unavailableControls(preferences: ReaderPreferences): Set<com.ermao.library.shared.modules.reader.ReaderControl> = emptySet()

    fun goPrevious(): Boolean

    fun goNext(): Boolean

    fun goTo(location: ReaderLocation): Boolean

    suspend fun navigateTo(entry: ReaderTocEntry): ReaderNavigationResult {
        val target = entry.target
        if (target is ReaderNavigationTargetInvalid) {
            return ReaderNavigationRejected(target.reasonCode)
        }
        if (currentLocation.value?.matches(target) == true) {
            return ReaderNavigationCompleted(moved = false)
        }
        if (!goTo(entry.location)) {
            return ReaderNavigationRejected("READER_NAVIGATION_REJECTED")
        }
        val verified = withTimeoutOrNull(NAVIGATION_VERIFICATION_TIMEOUT_MILLIS) {
            currentLocation.filterNotNull().first { location -> location.matches(target) }
        }
        return if (verified != null) ReaderNavigationCompleted(moved = true)
        else ReaderNavigationRejected("READER_NAVIGATION_VERIFICATION_FAILED")
    }

    fun goToTotalProgression(totalProgression: Double): Boolean

    fun dismissResumeNotice()

    fun returnToResumeNotice(): Boolean

    fun updatePreferences(updated: ReaderPreferences)

    suspend fun applyPreferences(updated: ReaderPreferences): ReaderCommandResult {
        if (!canApplyPreferences(updated)) return ReaderCommandRejected("READER_CONTROL_UNAVAILABLE")
        return try {
            updatePreferences(updated)
            ReaderCommandCompleted
        } catch (error: RuntimeException) {
            ReaderCommandRejected(if (error is ReaderPreferenceSaveFailure) "READER_PREFERENCES_SAVE_FAILED" else "READER_PREFERENCES_ENGINE_FAILED", error)
        }
    }

    fun canApplyPreferences(updated: ReaderPreferences): Boolean {
        if (updated == com.ermao.library.shared.modules.reader.resetReaderPreferences()) return true
        return com.ermao.library.shared.modules.reader.changedReaderControls(preferences.value, updated).all { control ->
            com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.resolveReaderControl(
                control, morphology, capabilities, preferences.value, true, unavailableControls(preferences.value),
            ) == com.ermao.library.shared.modules.reader.ReaderControlAvailability.Available
        }
    }

    fun toggleCurrentBookmark(): ReaderBookmarkChange?

    fun undoBookmarkChange(change: ReaderBookmarkChange): Boolean = false

    fun removeBookmark(id: String)

    fun undoBookmarkRemoval(id: String): Boolean = false

    fun goToBookmark(id: String): Boolean

    suspend fun flush()

    suspend fun close()
}

private const val NAVIGATION_VERIFICATION_TIMEOUT_MILLIS = 3_000L

internal fun resolveAdjacentChapters(
    entries: List<ReaderTocEntry>,
    currentLocation: ReaderLocation?,
): ReaderAdjacentChapters {
    if (currentLocation == null) return ReaderAdjacentChapters()
    val ordered = flattenTableOfContents(entries)
    val currentIndex = ordered.indexOfLast { currentLocation.matches(it.entry.target) }
        .takeIf { it >= 0 }
        ?: resolveChapterIndexByProgression(ordered, currentLocation)
        ?: return ReaderAdjacentChapters()
    return ReaderAdjacentChapters(
        previous = ordered.getOrNull(currentIndex - 1)?.entry,
        next = ordered.getOrNull(currentIndex + 1)?.entry,
    )
}

internal fun flattenTableOfContents(entries: List<ReaderTocEntry>, depth: Int = 0): List<ReaderTocNode> = buildList {
    entries.forEach { entry ->
        add(ReaderTocNode(entry, depth))
        addAll(flattenTableOfContents(entry.children, depth + 1))
    }
}

private fun resolveChapterIndexByProgression(
    entries: List<ReaderTocNode>,
    currentLocation: ReaderLocation,
): Int? {
    val current = (currentLocation as? com.ermao.library.shared.modules.reader.ReflowReaderLocation)
        ?.totalProgression ?: return null
    return entries.indexOfLast { node ->
        val start = (node.entry.location as? com.ermao.library.shared.modules.reader.ReflowReaderLocation)
            ?.totalProgression
        start != null && start <= current
    }.takeIf { it >= 0 }
}

private fun ReaderLocation.matches(target: ReaderNavigationTarget): Boolean {
    return when (target) {
    is ReaderNavigationTargetReflowable -> {
        val reflow = this as? com.ermao.library.shared.modules.reader.ReflowReaderLocation ?: return false
        val current = reflow.resourceKey ?: return false
        com.ermao.library.shared.modules.reader.matchesReaderNavigationHref(
            current,
            target.href,
            fragments = emptySet(),
            cssSelector = null,
        )
    }
    is ReaderNavigationTargetPdf ->
        (this as? com.ermao.library.shared.modules.reader.PdfReaderLocation)?.pageIndex == target.pageIndex
    is ReaderNavigationTargetComic -> (this as? ComicReaderLocation)?.let { location ->
        location.pageIndex == target.pageIndex && location.resourceHref == target.resourceHref
    } == true
    is ReaderNavigationTargetInvalid -> false
    }
}
