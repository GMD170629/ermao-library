package com.ermao.library.features.reader.infrastructure

import com.ermao.library.archive.infrastructure.ArchiveCoreException
import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.RemoteComicReaderSource
import com.ermao.library.shared.modules.reader.ReaderSource
import com.ermao.library.shared.modules.reader.ComicPageServerPort
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
import com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.ComicPublicationLocation
import com.ermao.library.shared.modules.reader.ReaderRestoreComicPage
import com.ermao.library.shared.modules.reader.ReaderRestoreExactLocalLocation
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.decideReaderResume
import com.ermao.library.shared.modules.reader.planReaderProgressRestore
import com.ermao.library.shared.modules.reader.readerErrorCodeForFailure
import java.io.FileNotFoundException
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CancellationException
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
    private val source: ReaderSource,
    private val canonicalPages: List<ReaderComicPage>,
    private val publicationStore: AndroidReaderPublicationStore,
    private val localPageSetDirectory: File? = null,
    private val progressStore: ReaderProgressStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val comicPageServer: ComicPageServerPort? = null,
    private val remoteSnapshot: ReaderProgressSnapshotV4? = null,
    private val initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null,
    private val progressCoordinator: ReaderProgressSyncCoordinator? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val persistPreferences: (ReaderPreferences) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
    private val presentationNamespaceKey: String? = null,
    private val publishProgressUpdate: (ReaderProgressPresentationUpdate) -> Unit = {},
) : AndroidReaderNavigatorSession {
    override val morphology = ReaderMorphology.Comic
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
    private val _resumeNotice = MutableStateFlow<ReaderResumeNotice?>(null)
    override val resumeNotice: StateFlow<ReaderResumeNotice?> = _resumeNotice.asStateFlow()
    private val _resumeActionFailed = MutableStateFlow(false)
    override val resumeActionFailed: StateFlow<Boolean> = _resumeActionFailed.asStateFlow()
    override val bookmarks: StateFlow<List<ReaderBookmark>> = MutableStateFlow(emptyList())
    override val bookmarkSyncPending: StateFlow<Boolean> = MutableStateFlow(false)
    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    private var publication: Publication? = null
    private var navigator: ImageNavigatorFragment? = null
    private var locationJob: Job? = null
    private var lastPersistedLocation: ComicReaderLocation? = null
    private var expectedRestore: ReaderComicPage? = null
    private var remoteTarget: ReaderProgressSnapshotV4? = null
    private var awaitingInitialObservation = true
    private var prepared = false
    private val saveMutex = Mutex()

    override suspend fun prepare(classLoader: ClassLoader): ImageNavigatorFragment {
        check(!prepared) { "Reader session is already prepared" }
        prepared = true
        val opened = try {
            when (source) {
                is LocalReaderSource -> {
                    if (source.sourceFormat == com.ermao.library.shared.modules.reader.ReaderSourceFormat.ImageDir) {
                        ImageDirectoryReadiumPublicationFactory().open(
                            requireNotNull(localPageSetDirectory) { "IMAGE_DIR bundle is missing" },
                            source.resourceId,
                            source.displayTitle,
                        )
                    } else {
                        if (source.sourceFormat !in setOf(
                            com.ermao.library.shared.modules.reader.ReaderSourceFormat.Cbz,
                            com.ermao.library.shared.modules.reader.ReaderSourceFormat.Zip,
                            com.ermao.library.shared.modules.reader.ReaderSourceFormat.Cbr,
                            com.ermao.library.shared.modules.reader.ReaderSourceFormat.Rar,
                            )
                        ) {
                            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ComicArchiveFormatUnsupported))
                        }
                        val file = publicationStore.resolve(source)
                        CbzReadiumPublicationFactory().open(file, source.displayTitle, canonicalPages)
                    }
                }
                is RemoteComicReaderSource -> RemoteComicReadiumPublicationFactory(
                    requireNotNull(comicPageServer) { "Comic page server is missing" },
                ).open(source, _preferences.value.comic.imageVariant)
                else -> throw IllegalArgumentException("Comic source is unsupported")
            }
        } catch (error: ReaderOpenFailure) {
            throw error
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: ArchiveCoreException) {
            throw ReaderOpenFailure(
                ReaderError(readerErrorCodeForFailure(error.stableCode, recoverable = false)),
                cause = error,
            )
        } catch (error: IllegalArgumentException) {
            val code = if (source is LocalReaderSource) {
                ReaderErrorCode.ComicArchiveCorrupt
            } else {
                ReaderErrorCode.ReaderEngineError
            }
            throw ReaderOpenFailure(ReaderError(code), cause = error)
        }
        publication = opened
        val localProgress = if (initialTarget == null) loadProgressSafely() else null
        val resumeDecision = decideReaderResume(localProgress, remoteSnapshot.takeIf { initialTarget == null }, source)
        val restorePlan = planReaderProgressRestore(
            resumeDecision.selected?.localProgress,
            resumeDecision.selected?.remoteSnapshot,
            source,
        )
        val explicitPage = initialTarget?.let { target ->
            val comic = target as? com.ermao.library.shared.modules.reader.ReaderNavigationTargetComic
            canonicalPages.firstOrNull { it.pageIndex == comic?.pageIndex && it.resourceHref == comic.resourceHref }
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
        }
        val restorePage = explicitPage ?: restorePlan.candidates.firstNotNullOfOrNull { candidate ->
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
                title = page.title ?: (page.pageIndex + 1).toString(),
                location = page.toLocation(),
                id = page.resourceHref,
                index = page.pageIndex,
            )
        }
        val factory = ImageNavigatorFragment.createFactory(opened, initialLocator)
        return (factory.instantiate(classLoader, ImageNavigatorFragment::class.java.name) as ImageNavigatorFragment)
            .also { navigator = it }
    }

    override fun bind(scope: CoroutineScope) {
        val currentNavigator = checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        progressCoordinator?.let { coordinator ->
            scope.launch {
                coordinator.remoteProgressNotices.collectLatest { notice ->
                    val snapshot = notice?.snapshot
                    val location = snapshot?.locator as? ComicPublicationLocation
                    remoteTarget = snapshot?.takeIf {
                        location != null && canonicalPage(location.resourceHref, location.pageIndex) != null
                    }
                    _resumeNotice.value = remoteTarget?.let {
                        ReaderResumeNotice(
                            it.effectiveCapturedAtEpochMillis,
                            it.displayPercent,
                            null,
                            location!!.pageIndex + 1,
                        )
                    }
                }
            }
        }
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
                val target = remoteTarget
                val targetLocation = target?.locator as? ComicPublicationLocation
                if (targetLocation?.pageIndex == location.pageIndex && targetLocation.resourceHref == location.resourceHref) {
                    progressCoordinator?.acceptVerifiedRemoteProgress(
                        ReaderProgress(source.resourceId, location, nowEpochMillis(), deviceIdentity.stableDeviceId()),
                        target,
                    )
                    remoteTarget = null
                    _resumeNotice.value = null
                    lastPersistedLocation = location
                    return@collectLatest
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

    override fun goPrevious(): Boolean = navigator?.goBackward(animated = navigationAnimationsEnabled()) ?: false

    override fun goNext(): Boolean = navigator?.goForward(animated = navigationAnimationsEnabled()) ?: false

    override fun goTo(location: ReaderLocation): Boolean {
        val comic = location as? ComicReaderLocation ?: return false
        val page = canonicalPages.getOrNull(comic.pageIndex)
            ?.takeIf { it.resourceHref == comic.resourceHref }
            ?: return false
        val locator = publication?.let { locatorFor(page, it) } ?: return false
        expectedRestore = page
        return navigator?.go(locator, animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val index = ((canonicalPages.lastIndex * totalProgression).toInt()).coerceIn(canonicalPages.indices)
        return goTo(canonicalPages[index].toLocation())
    }

    private fun navigationAnimationsEnabled(): Boolean =
        shouldAnimateAndroidReaderNavigation(_preferences.value, morphology)

    override fun dismissResumeNotice() {
        remoteTarget = null
        _resumeNotice.value = null
        _resumeActionFailed.value = false
        progressCoordinator?.dismissRemoteProgressNotice()
    }

    override fun returnToResumeNotice(): Boolean {
        val target = remoteTarget?.locator as? ComicPublicationLocation ?: return false
        val page = canonicalPage(target.resourceHref, target.pageIndex) ?: return false
        val moved = goTo(page.toLocation())
        if (!moved) _resumeActionFailed.value = true
        return moved
    }

    override fun updatePreferences(updated: ReaderPreferences) {
        if (_preferences.value == updated) return
        _preferences.value = updated
        persistPreferences(updated)
    }

    override fun toggleCurrentBookmark(): ReaderBookmarkChange? = null

    override fun removeBookmark(id: String) = Unit

    override fun goToBookmark(id: String): Boolean = false

    override suspend fun flush() {
        (_currentLocation.value as? ComicReaderLocation)?.let { persist(it) }
    }

    override suspend fun close() {
        try {
            flush()
        } finally {
            release()
        }
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
    )

    private suspend fun loadProgressSafely(): ReaderProgress? = try {
        progressStore.load(source.resourceId)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        null
    }

    private suspend fun persist(location: ComicReaderLocation) = saveMutex.withLock {
        if (lastPersistedLocation == location) return@withLock
        val capturedAt = nowEpochMillis()
        val percent = if (canonicalPages.size <= 1) {
            100.0
        } else {
            location.pageIndex.toDouble() / canonicalPages.lastIndex * 100.0
        }
        val progress = ReaderProgress(
            resourceId = source.resourceId,
            location = location,
            updatedAtEpochMillis = capturedAt,
            deviceId = deviceIdentity.stableDeviceId(),
            percent = percent,
        )
        try {
            progressStore.save(progress)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return@withLock
        }
        lastPersistedLocation = location
        val namespace = presentationNamespaceKey ?: return@withLock
        val bookId = source.bookId ?: return@withLock
        publishProgressUpdate(
            createReaderProgressPresentationUpdate(
                namespaceKey = namespace,
                bookId = bookId,
                resourceId = source.resourceId,
                percent = percent,
                progress = progress,
                chapterTitle = location.resourceHref.substringAfterLast('/'),
            ),
        )
    }

    private companion object {
        const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L
    }
}
