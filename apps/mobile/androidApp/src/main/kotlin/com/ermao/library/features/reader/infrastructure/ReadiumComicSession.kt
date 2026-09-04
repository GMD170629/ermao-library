package com.ermao.library.features.reader.infrastructure

import com.ermao.library.archive.infrastructure.ArchiveCoreException
import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.features.reader.application.ReaderStartupPositionSource
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
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderPositionSyncCoordinator
import com.ermao.library.shared.modules.reader.ReaderPositionSyncingStore
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReaderComicCapabilities
import com.ermao.library.shared.modules.reader.ReaderControl
import com.ermao.library.shared.modules.reader.changedReaderControls
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.readerErrorCodeForFailure
import com.ermao.library.shared.modules.reader.readerSafetyComicArchiveDetectorFailure
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
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.Locator

internal class ReadiumComicSession(
    private val source: ReaderSource,
    private val canonicalPages: List<ReaderComicPage>,
    private val publicationStore: AndroidReaderPublicationStore,
    private val localPageSetDirectory: File? = null,
    private val progressStore: ReaderPositionSyncingStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val comicPageServer: ComicPageServerPort? = null,
    private val remoteSnapshot: ReaderProgressSnapshotV5? = null,
    private val initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null,
    private val startupPositionSource: ReaderStartupPositionSource = ReaderStartupPositionSource.Start,
    private val progressCoordinator: ReaderPositionSyncCoordinator? = null,
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
        supportsPageWidth = true,
        supportsReadingMode = true,
        supportsSpreadMode = true,
        supportsParagraphLayout = false,
        supportsProgressStyles = true,
        supportsClock = true,
        supportsKeepAwake = true,
        supportsTapZones = true,
        supportsSwipeToggle = true,
        supportsPageTurnAnimation = true,
        supportsSmartOptimization = false,
        supportsKeyboardPageTurn = true,
        supportsVolumeKeyPageTurn = true,
        comic = ReaderComicCapabilities(
            supportsFlow = true,
            supportsSpread = true,
            supportsDirection = true,
            supportsCoverSingle = true,
            supportsPageGap = true,
            supportsZoom = true,
            supportsFit = true,
            supportsQuality = source is RemoteComicReaderSource,
            supportsAnimation = true,
            supportsPageWidth = true,
        ),
    )
    private val _contentError = MutableStateFlow<ReaderError?>(null)
    override val contentError: StateFlow<ReaderError?> = _contentError.asStateFlow()

    private val _currentLocation = MutableStateFlow<ReaderLocation?>(null)
    override val currentLocation: StateFlow<ReaderLocation?> = _currentLocation.asStateFlow()
    private val _presentationProgress = MutableStateFlow<Double?>(null)
    override val presentationProgress: StateFlow<Double?> = _presentationProgress.asStateFlow()
    private val _preferences = MutableStateFlow(initialPreferences)
    override val preferences: StateFlow<ReaderPreferences> = _preferences.asStateFlow()
    private val _resumeNotice = MutableStateFlow<ReaderResumeNotice?>(null)
    override val resumeNotice: StateFlow<ReaderResumeNotice?> = _resumeNotice.asStateFlow()
    private val _resumeActionFailed = MutableStateFlow(false)
    override val resumeActionFailed: StateFlow<Boolean> = _resumeActionFailed.asStateFlow()
    override val bookmarks: StateFlow<List<ReaderBookmark>> = MutableStateFlow(emptyList())
    override val bookmarkSyncPending: StateFlow<Boolean> = MutableStateFlow(false)
    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    private var publication: Publication? = null
    private var navigator: ComicNavigatorFragment? = null
    private var locationJob: Job? = null
    private var presentationJob: Job? = null
    private var sessionScope: CoroutineScope? = null
    private var lastPersistedLocation: ComicReaderLocation? = null
    private var lastPersistedPercent: Double? = null
    private var lastObservedLocator: Locator? = null
    private var remoteTarget: ReaderProgressSnapshotV5? = null
    private var prepared = false
    private val saveMutex = Mutex()


    override suspend fun prepare(@Suppress("UNUSED_PARAMETER") classLoader: ClassLoader): androidx.fragment.app.Fragment {
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
                    onFailure = { _contentError.value = it },
                ).open(source, _preferences.value.comic.imageVariant)
                else -> throw IllegalArgumentException("Comic source is unsupported")
            }
        } catch (error: ReaderOpenFailure) {
            throw error
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: ArchiveCoreException) {
            val safetyFailure = readerSafetyComicArchiveDetectorFailure(error.stableCode)
            throw ReaderOpenFailure(
                ReaderError(
                    code = safetyFailure?.let { failure ->
                        readerErrorCodeForFailure(failure.errorCode, recoverable = false)
                    } ?: readerErrorCodeForFailure(error.stableCode, recoverable = false),
                    safeContext = safetyFailure?.let { failure ->
                        mapOf("ruleId" to failure.ruleId, "errorCode" to failure.errorCode)
                    }.orEmpty(),
                ),
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
        val explicitPage = initialTarget?.let { target ->
            val comic = target as? com.ermao.library.shared.modules.reader.ReaderNavigationTargetComic
            canonicalPages.firstOrNull { it.pageIndex == comic?.pageIndex && it.resourceHref == comic.resourceHref }
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
        }
        val localPosition = if (
            initialTarget == null &&
            startupPositionSource in setOf(
                ReaderStartupPositionSource.LocalPending,
                ReaderStartupPositionSource.LocalOnly,
            )
        ) {
            loadPositionSafely()
        } else {
            null
        }
        val restorePage = when {
            explicitPage != null -> explicitPage
            localPosition != null -> pageForPosition(localPosition.position)
            startupPositionSource == ReaderStartupPositionSource.ServerSnapshot && remoteSnapshot != null ->
                pageForPosition(remoteSnapshot.position)
            else -> null
        }
        if (localPosition != null && restorePage != null) {
            val location = restorePage.toLocation()
            _currentLocation.value = location
            lastPersistedLocation = location
            lastPersistedPercent = localPosition.position.presentation.displayPercent
        }
        tableOfContents = canonicalPages.map { page ->
            ReaderTocEntry(
                title = page.title ?: (page.pageIndex + 1).toString(),
                location = page.toLocation(),
                id = page.resourceHref,
                index = page.pageIndex,
            )
        }
        return ComicNavigatorFragment().also {
            it.configure(
                publication = opened,
                pages = canonicalPages,
                preferences = _preferences.value,
                initialPageIndex = restorePage?.pageIndex ?: 0,
                onError = { error -> _contentError.value = error },
            )
            navigator = it
        }
    }

    override fun bind(scope: CoroutineScope) {
        val currentNavigator = checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        check(presentationJob == null) { "Reader presentation is already bound" }
        sessionScope = scope
        presentationJob = scope.launch {
            currentNavigator.presentation.collectLatest { current ->
                _presentationProgress.value = current?.plan?.progress
            }
        }
        progressCoordinator?.let { coordinator ->
            scope.launch {
                coordinator.remotePositionNotices.collectLatest { notice ->
                    remoteTarget = notice?.snapshot
                    _resumeActionFailed.value = false
                    _resumeNotice.value = notice?.snapshot?.let(::resumeNotice)
                }
            }
        }
        locationJob = scope.launch {
            currentNavigator.currentLocation.collectLatest { locationValue ->
                val location = locationValue as? ComicReaderLocation ?: return@collectLatest
                val locator = locatorForPage(location.pageIndex) ?: return@collectLatest
                lastObservedLocator = locator
                _currentLocation.value = location
                val presentationProgress = currentNavigator.currentProgress
                delay(LOCAL_SAVE_DEBOUNCE_MILLIS)
                persist(locator, location, presentationProgress)
            }
        }
    }

    override fun goPrevious(): Boolean {
        dismissResumeNotice()
        return navigator?.goBackward(animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goNext(): Boolean {
        dismissResumeNotice()
        return navigator?.goForward(animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goTo(location: ReaderLocation): Boolean {
        val comic = location as? ComicReaderLocation ?: return false
        val page = canonicalPages.getOrNull(comic.pageIndex)
            ?.takeIf { it.resourceHref == comic.resourceHref }
        ?: return false
        dismissResumeNotice()
        return navigator?.goTo(page.pageIndex, animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        dismissResumeNotice()
        return navigator?.goToProgress(totalProgression, animated = navigationAnimationsEnabled()) ?: false
    }

    private fun navigationAnimationsEnabled(): Boolean =
        shouldAnimateAndroidReaderNavigation(_preferences.value, morphology)

    override fun dismissResumeNotice() {
        remoteTarget = null
        _resumeNotice.value = null
        _resumeActionFailed.value = false
        progressCoordinator?.dismissRemotePositionNotice()
    }

    override fun returnToResumeNotice(): Boolean {
        val snapshot = remoteTarget ?: return false
        val page = pageForPosition(snapshot.position) ?: run {
            _resumeActionFailed.value = true
            return false
        }
        val moved = runCatching {
            navigator?.goTo(page.pageIndex, animated = navigationAnimationsEnabled()) == true
        }.getOrDefault(false)
        if (!moved) {
            _resumeActionFailed.value = true
            return false
        }
        sessionScope?.launch {
            runCatching {
                progressCoordinator?.acceptRemotePosition(
                    ReaderPositionLocalState(
                        resourceId = source.resourceId,
                        clientId = deviceIdentity.stableDeviceId(),
                        capturedAtEpochMillis = snapshot.capturedAtEpochMillis,
                        position = snapshot.position,
                    ),
                    snapshot,
                )
            }
        }
        lastPersistedLocation = page.toLocation()
        lastPersistedPercent = snapshot.position.presentation.displayPercent
        remoteTarget = null
        _resumeNotice.value = null
        return true
    }

    override fun unavailableControls(preferences: ReaderPreferences): Set<ReaderControl> =
        if (source is RemoteComicReaderSource) emptySet() else setOf(ReaderControl.ComicQuality)

    override fun canApplyPreferences(updated: ReaderPreferences): Boolean {
        if (updated == com.ermao.library.shared.modules.reader.resetReaderPreferences()) return true
        val unavailable = unavailableControls(_preferences.value)
        return changedReaderControls(_preferences.value, updated).all { control ->
            com.ermao.library.shared.modules.reader.ReaderSettingsCatalog.resolveReaderControl(
                control,
                morphology,
                capabilities,
                updated,
                true,
                unavailable,
            ) == com.ermao.library.shared.modules.reader.ReaderControlAvailability.Available
        }
    }

    override fun updatePreferences(updated: ReaderPreferences) {
        val previous = _preferences.value
        if (previous == updated) return
        val currentNavigator = navigator
        val currentPublication = publication
        val replacementPublication = if (
            source is RemoteComicReaderSource && previous.comic.imageVariant != updated.comic.imageVariant
        ) {
            RemoteComicReadiumPublicationFactory(
                requireNotNull(comicPageServer) { "Comic page server is missing" },
                onFailure = { _contentError.value = it },
            ).open(source, updated.comic.imageVariant)
        } else {
            null
        }
        if (replacementPublication != null) {
            currentNavigator?.replacePublication(replacementPublication, updated)
            publication = replacementPublication
        } else {
            currentNavigator?.updatePreferences(updated)
        }
        try {
            persistPreferences(updated)
            _preferences.value = updated
            if (replacementPublication != null) currentPublication?.close()
        } catch (error: RuntimeException) {
            if (replacementPublication != null && currentPublication != null) {
                currentNavigator?.replacePublication(currentPublication, previous)
                publication = currentPublication
                replacementPublication.close()
            } else {
                currentNavigator?.updatePreferences(previous)
            }
            throw error
        }
    }

    override fun toggleCurrentBookmark(): ReaderBookmarkChange? = null

    override fun removeBookmark(id: String) = Unit

    override fun goToBookmark(id: String): Boolean = false

    override suspend fun flush() {
        (_currentLocation.value as? ComicReaderLocation)?.let { location ->
            val locator = locatorForPage(location.pageIndex) ?: return@let
            persist(locator, location, navigator?.currentProgress)
        }
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
        presentationJob?.cancel()
        presentationJob = null
        sessionScope = null
        navigator?.release()
        navigator = null
        publication?.close()
        publication = null
        remoteTarget = null
    }

    private fun canonicalPage(resourceHref: String, pageIndex: Int): ReaderComicPage? =
        canonicalPages.getOrNull(pageIndex)?.takeIf { it.resourceHref == resourceHref }

    private fun ReaderComicPage.toLocation() = ComicReaderLocation(
        resourceHref = resourceHref,
        pageIndex = pageIndex,
    )

    private suspend fun loadPositionSafely(): ReaderPositionLocalState? = try {
        progressStore.load(source.resourceId)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        null
    }

    private fun locatorForPage(pageIndex: Int): Locator? {
        val opened = publication ?: return null
        val link = opened.readingOrder.getOrNull(pageIndex) ?: return null
        return opened.locatorFromLink(link)
    }

    private fun pageForPosition(position: ReaderPositionReport): ReaderComicPage? {
        val locator = runCatching {
            Locator.fromJSON(org.json.JSONObject(position.locator.canonicalJson))
        }.getOrNull() ?: return null
        val href = locator.href.toString().substringBefore('#')
        return canonicalPages.firstOrNull { it.resourceHref == href }
            ?: locator.locations.position?.minus(1)?.let { canonicalPages.getOrNull(it) }
    }

    private fun positionReport(
        locator: Locator,
        location: ComicReaderLocation,
        presentationProgress: Double?,
    ): ReaderPositionReport {
        val progression = (presentationProgress ?: if (canonicalPages.size <= 1) {
            1.0
        } else {
            location.pageIndex.toDouble() / canonicalPages.lastIndex
        }).coerceIn(0.0, 1.0)
        return ReaderPositionReport(
            locator = com.ermao.library.shared.modules.reader.ReaderOpaqueLocator.parse(
                locator.toJSON().toString(),
            ),
            presentation = ReaderPositionPresentation(
                displayPercent = progression * 100.0,
                totalProgression = progression,
                currentHref = location.resourceHref,
                chapter = null,
                page = com.ermao.library.shared.modules.reader.ReaderPagePresentation(
                    number = location.pageIndex + 1,
                    total = canonicalPages.size,
                ),
                playback = null,
            ),
        )
    }

    private suspend fun persist(
        locator: Locator,
        location: ComicReaderLocation,
        presentationProgress: Double?,
    ) = saveMutex.withLock {
        val capturedAt = nowEpochMillis()
        val fallbackProgress = if (canonicalPages.size <= 1) 1.0 else {
            location.pageIndex.toDouble() / canonicalPages.lastIndex
        }
        val percent = (presentationProgress ?: fallbackProgress).coerceIn(0.0, 1.0) * 100.0
        if (lastPersistedLocation == location && lastPersistedPercent == percent) return@withLock
        val report = positionReport(locator, location, presentationProgress)
        val position = ReaderPositionLocalState(
            resourceId = source.resourceId,
            clientId = deviceIdentity.stableDeviceId(),
            capturedAtEpochMillis = capturedAt,
            position = report,
        )
        try {
            progressStore.save(position)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return@withLock
        }
        lastPersistedLocation = location
        lastPersistedPercent = percent
        val namespace = presentationNamespaceKey ?: return@withLock
        val bookId = source.bookId ?: return@withLock
        publishProgressUpdate(
            createReaderProgressPresentationUpdate(
                namespaceKey = namespace,
                bookId = bookId,
                resourceId = source.resourceId,
                position = report,
                capturedAtEpochMillis = capturedAt,
            ),
        )
    }

    private fun resumeNotice(snapshot: ReaderProgressSnapshotV5): ReaderResumeNotice = ReaderResumeNotice(
        capturedAtEpochMillis = snapshot.capturedAtEpochMillis,
        percent = snapshot.position.presentation.displayPercent,
        chapterLabel = snapshot.position.presentation.chapter?.title,
        pageNumber = snapshot.position.presentation.page?.number,
    )

    private companion object {
        const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L
    }
}
