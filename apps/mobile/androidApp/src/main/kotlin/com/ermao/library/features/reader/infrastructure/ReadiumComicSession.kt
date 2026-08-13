package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderRestoreComicPage
import com.ermao.library.shared.modules.reader.ReaderRestoreExactLocalLocation
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.decideReaderResume
import com.ermao.library.shared.modules.reader.planReaderProgressRestore
import java.io.FileNotFoundException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.readium.r2.navigator.image.ImageNavigatorFragment
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication

internal class ReadiumComicSession(
    private val source: LocalReaderSource,
    private val canonicalPages: List<ReaderComicPage>,
    private val publicationStore: AndroidReaderPublicationStore,
    private val progressStore: ReaderProgressStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val remoteSnapshot: ReaderProgressSnapshotV4? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val persistPreferences: (ReaderPreferences) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
    private val presentationNamespaceKey: String? = null,
    private val publishProgressUpdate: (ReaderProgressPresentationUpdate) -> Unit = {},
) : AndroidReaderNavigatorSession {
    override val capabilities = ReaderCapabilities(
        canGoPrevious = true,
        canGoNext = true,
        hasTableOfContents = true,
        supportsBookmarks = false,
        supportsAnnotations = false,
        supportsTheme = true,
        supportsSystemTheme = true,
        supportsFontSize = false,
        supportsFontFamily = false,
        supportsFontWeight = false,
        supportsLineHeight = false,
        supportsPositiveLetterSpacing = false,
        supportsNegativeLetterSpacing = false,
        supportsPageMargins = false,
        supportsPageWidth = false,
        supportsReadingMode = false,
        supportsSpreadMode = false,
        supportsParagraphLayout = false,
        supportsIndependentPublisherStyles = false,
        supportsProgressStyles = true,
        supportsClock = true,
        supportsKeepAwake = true,
        supportsTapZones = true,
        supportsSwipeToggle = false,
        supportsPageTurnAnimation = false,
        supportsSmartOptimization = false,
        supportsKeyboardPageTurn = true,
        supportsVolumeKeyPageTurn = true,
    )
    private val _currentLocation = MutableStateFlow<ReaderLocation?>(null)
    override val currentLocation: StateFlow<ReaderLocation?> = _currentLocation.asStateFlow()
    private val _preferences = MutableStateFlow(initialPreferences)
    override val preferences: StateFlow<ReaderPreferences> = _preferences.asStateFlow()
    private val _restoreWarning = MutableStateFlow<ReaderError?>(null)
    override val restoreWarning: StateFlow<ReaderError?> = _restoreWarning.asStateFlow()
    override val resumeNotice: StateFlow<ReaderResumeNotice?> = MutableStateFlow(null)
    override val resumeActionFailed: StateFlow<Boolean> = MutableStateFlow(false)
    override val bookmarks: StateFlow<List<ReaderBookmark>> = MutableStateFlow(emptyList())
    override val bookmarkSyncPending: StateFlow<Boolean> = MutableStateFlow(false)
    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    private var publication: Publication? = null
    private var navigator: ImageNavigatorFragment? = null
    private var locationJob: Job? = null
    private var lastPersistedLocation: ComicReaderLocation? = null
    private var expectedRestore: ReaderComicPage? = null
    private var awaitingInitialObservation = true
    private var prepared = false
    private val saveMutex = Mutex()

    override suspend fun prepare(classLoader: ClassLoader): ImageNavigatorFragment {
        check(!prepared) { "Reader session is already prepared" }
        prepared = true
        val file = try {
            publicationStore.resolveVerified(source)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        }
        val opened = try {
            CbzReadiumPublicationFactory(readium.assetRetriever).open(file, source.displayTitle, canonicalPages)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile), cause = error)
        }
        publication = opened
        val localProgress = loadProgressSafely()
        val resumeDecision = decideReaderResume(localProgress, remoteSnapshot, source)
        val restorePlan = planReaderProgressRestore(
            resumeDecision.selected?.localProgress,
            resumeDecision.selected?.remoteSnapshot,
            source,
        )
        val restorePage = restorePlan.candidates.firstNotNullOfOrNull { candidate ->
            when (candidate) {
                is ReaderRestoreComicPage -> canonicalPage(candidate.resourceHref, candidate.pageIndex)
                is ReaderRestoreExactLocalLocation -> (candidate.location as? ComicReaderLocation)?.let {
                    canonicalPage(it.resourceHref, it.pageIndex)
                }
                else -> null
            }
        }
        val initialLocator = restorePage?.let { page -> locatorFor(page, opened) }
        expectedRestore = restorePage
        if ((restorePlan.localProgress != null || restorePlan.remoteSnapshot != null) && initialLocator == null) {
            _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        } else if (restorePlan.usesLocalExact) {
            val location = restorePlan.localProgress?.location as? ComicReaderLocation
            _currentLocation.value = location
            lastPersistedLocation = location
        }
        tableOfContents = canonicalPages.map { page ->
            ReaderTocEntry(
                title = page.resourceHref.substringAfterLast('/'),
                location = page.toLocation(),
            )
        }
        val factory = ImageNavigatorFragment.createFactory(opened, initialLocator)
        return (factory.instantiate(classLoader, ImageNavigatorFragment::class.java.name) as ImageNavigatorFragment)
            .also { navigator = it }
    }

    override fun bind(scope: CoroutineScope) {
        val currentNavigator = checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        locationJob = scope.launch {
            currentNavigator.currentLocator.collectLatest { locator ->
                val location = locator.toCanonicalLocation() ?: run {
                    _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
                    return@collectLatest
                }
                _currentLocation.value = location
                expectedRestore?.let { expected ->
                    expectedRestore = null
                    if (expected.resourceHref != location.resourceHref || expected.pageIndex != location.pageIndex) {
                        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
                        return@collectLatest
                    }
                }
                if (awaitingInitialObservation) {
                    awaitingInitialObservation = false
                    return@collectLatest
                }
                delay(LOCAL_SAVE_DEBOUNCE_MILLIS)
                persist(location)
            }
        }
    }

    override fun goPrevious(): Boolean = navigator?.goBackward(animated = true) ?: false

    override fun goNext(): Boolean = navigator?.goForward(animated = true) ?: false

    override fun goTo(location: ReaderLocation): Boolean {
        val comic = location as? ComicReaderLocation ?: return false
        if (comic.contentFingerprint != source.contentFingerprint) return false
        val page = canonicalPages.getOrNull(comic.pageIndex)
            ?.takeIf { it.resourceHref == comic.resourceHref }
            ?: return false
        val locator = publication?.let { locatorFor(page, it) } ?: return false
        expectedRestore = page
        return navigator?.go(locator, animated = true) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val index = ((canonicalPages.lastIndex * totalProgression).toInt()).coerceIn(canonicalPages.indices)
        return goTo(canonicalPages[index].toLocation())
    }

    override fun dismissResumeNotice() = Unit

    override fun returnToResumeNotice(): Boolean = false

    override fun updatePreferences(updated: ReaderPreferences) {
        if (_preferences.value == updated) return
        _preferences.value = updated
        persistPreferences(updated)
    }

    override fun toggleCurrentBookmark() = Unit

    override fun removeBookmark(id: String) = Unit

    override fun goToBookmark(id: String): Boolean = false

    override suspend fun flush() {
        (_currentLocation.value as? ComicReaderLocation)?.let { persist(it) }
    }

    override suspend fun close() {
        flush()
        release()
    }

    override fun release() {
        locationJob?.cancel()
        locationJob = null
        navigator = null
        publication?.close()
        publication = null
    }

    private fun canonicalPage(resourceHref: String, pageIndex: Int): ReaderComicPage? =
        canonicalPages.getOrNull(pageIndex)?.takeIf { it.resourceHref == resourceHref }

    private fun locatorFor(page: ReaderComicPage, opened: Publication): Locator? =
        opened.readingOrder.getOrNull(page.pageIndex)
            ?.takeIf { it.href.toString() == page.resourceHref }
            ?.let(opened::locatorFromLink)

    private fun Locator.toCanonicalLocation(): ComicReaderLocation? {
        val href = href.toString()
        val index = publication?.readingOrder?.indexOfFirst { it.href.toString() == href } ?: -1
        val page = canonicalPages.getOrNull(index)?.takeIf { it.resourceHref == href } ?: return null
        return page.toLocation()
    }

    private fun ReaderComicPage.toLocation() = ComicReaderLocation(
        resourceHref = resourceHref,
        pageIndex = pageIndex,
        contentFingerprint = source.contentFingerprint,
    )

    private suspend fun loadProgressSafely(): ReaderProgress? = try {
        progressStore.load(source.sourceId)
    } catch (_: IllegalArgumentException) {
        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        null
    }

    private suspend fun persist(location: ComicReaderLocation) = saveMutex.withLock {
        if (lastPersistedLocation == location) return@withLock
        val capturedAt = nowEpochMillis()
        val percent = ((location.pageIndex + 1).toDouble() / canonicalPages.size * 100.0).coerceIn(0.0, 100.0)
        progressStore.save(
            ReaderProgress(
                sourceId = source.sourceId,
                location = location,
                updatedAtEpochMillis = capturedAt,
                deviceId = deviceIdentity.stableDeviceId(),
                percent = percent,
            ),
        )
        lastPersistedLocation = location
        val namespace = presentationNamespaceKey ?: return@withLock
        val workId = source.workId ?: return@withLock
        publishProgressUpdate(
            ReaderProgressPresentationUpdate(
                namespaceKey = namespace,
                workId = workId,
                volumeId = source.volumeId ?: source.sourceId,
                percent = percent,
                currentHref = location.resourceHref,
                chapterTitle = location.resourceHref.substringAfterLast('/'),
                capturedAtEpochMillis = capturedAt,
            ),
        )
    }

    private companion object {
        const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L
    }
}
