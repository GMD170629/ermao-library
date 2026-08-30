package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.enforceAndroidSinglePagePreferences

import com.ermao.library.shared.modules.reader.PdfRangeLoader
import com.ermao.library.shared.modules.reader.PdfRangeFailure

import com.ermao.library.shared.modules.reader.PdfRangeMemory
import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderPdfPage
import com.ermao.library.shared.modules.reader.ReaderSource
import com.ermao.library.shared.modules.reader.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.reader.RemoteComicReaderSource
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import java.io.File
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.PdfPublicationLocation
import com.ermao.library.shared.modules.reader.ReaderRestoreExactLocalLocation
import com.ermao.library.shared.modules.reader.ReaderRestorePdfPage
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.readerErrorCodeForFailure
import com.ermao.library.shared.modules.reader.readerSafetyDrmFailure
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.decideReaderResume
import com.ermao.library.shared.modules.reader.planReaderProgressRestore
import java.io.FileNotFoundException
import androidx.fragment.app.FragmentFactory
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
import org.readium.r2.navigator.pdf.PdfNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.isRestricted
import org.readium.r2.shared.publication.services.positions

@OptIn(ExperimentalReadiumApi::class)
internal class ReadiumPdfSession(
    private val source: ReaderSource,
    @Suppress("unused") private val expectedPageCount: Int?,
    private val canonicalPages: List<ReaderPdfPage>,
    private val publicationStore: AndroidReaderPublicationStore,
    private val progressStore: ReaderProgressStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val remotePdfium: AndroidRemotePdfiumSessionConfiguration? = null,
    private val remoteSnapshot: ReaderProgressSnapshotV4? = null,
    private val initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null,
    private val progressCoordinator: ReaderProgressSyncCoordinator? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val persistPreferences: (ReaderPreferences) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
    private val presentationNamespaceKey: String? = null,
    private val publishProgressUpdate: (ReaderProgressPresentationUpdate) -> Unit = {},
) : AndroidReaderNavigatorSession {
    override var requestedNavigationTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = initialTarget
        private set
    override val morphology = ReaderMorphology.Pdf
    override val capabilities = ReaderCapabilities(
        canGoPrevious = true, canGoNext = true, hasTableOfContents = true,
        supportsBookmarks = false, supportsAnnotations = false, supportsTheme = true,
        supportsSystemTheme = true, supportsFontSize = false, supportsFontFamily = false,
        supportsFontWeight = false, supportsLineHeight = false,
        supportsPositiveLetterSpacing = false, supportsNegativeLetterSpacing = false,
        supportsPageMargins = false, supportsPageWidth = true, supportsReadingMode = false,
        supportsSpreadMode = false, supportsParagraphLayout = false,
        supportsProgressStyles = true, supportsClock = true, supportsKeepAwake = true, supportsTapZones = true,
        supportsSwipeToggle = false, supportsPageTurnAnimation = false,
        supportsSmartOptimization = false, supportsKeyboardPageTurn = true,
        supportsVolumeKeyPageTurn = true,
        supportsPdfFit = false,
    )
    private val _currentLocation = MutableStateFlow<ReaderLocation?>(null)
    override val currentLocation: StateFlow<ReaderLocation?> = _currentLocation.asStateFlow()
    private val _preferences = MutableStateFlow(enforceAndroidSinglePagePreferences(initialPreferences))
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

    override fun dismissRestoreWarning() {
        _restoreWarning.value = null
    }
    private var navigator: PdfNavigatorFragment<*, *>? = null
    private var nativeDocument: ShukuPdfiumDocument? = null
    private var positions: List<Locator> = emptyList()
    private var pageCount: Int = 0
    private var pages: List<ReaderPdfPage> = emptyList()
    private var locationJob: Job? = null
    private var lastPersistedLocation: PdfReaderLocation? = null
    private var expectedRestorePage: Int? = null
    private var remoteTarget: ReaderProgressSnapshotV4? = null
    private var awaitingInitialObservation = true
    private var prepared = false
    private val saveMutex = Mutex()

    override suspend fun prepare(classLoader: ClassLoader): PdfNavigatorFragment<*, *> {
        check(!prepared) { "Reader session is already prepared" }
        prepared = true
        val opened = openPublication()
        if (opened.isRestricted) {
            closeOpeningResources(opened)
            val failure = readerSafetyDrmFailure()
            throw ReaderOpenFailure(
                ReaderError(
                    code = readerErrorCodeForFailure(failure.errorCode, recoverable = false),
                    safeContext = mapOf(
                        "ruleId" to failure.ruleId,
                        "errorCode" to failure.errorCode,
                    ),
                ),
            )
        }
        if (!opened.conformsTo(Publication.Profile.PDF)) {
            closeOpeningResources(opened)
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
        }
        publication = opened
        positions = opened.positions()
        val openedPageCount = opened.metadata.numberOfPages
            ?: nativeDocument?.pageCount
            ?: positions.size.takeIf { it > 0 }
        if (openedPageCount == null || openedPageCount <= 0 || positions.size != openedPageCount) {
            release()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile))
        }
        pageCount = openedPageCount
        pages = pageHints(openedPageCount)

        val localProgress = if (initialTarget == null) loadProgressSafely() else null
        val decision = decideReaderResume(localProgress, remoteSnapshot.takeIf { initialTarget == null }, source)
        val restorePlan = planReaderProgressRestore(
            decision.selected?.localProgress,
            decision.selected?.remoteSnapshot,
            source,
        )
        val explicitPage = initialTarget?.let { target ->
            (target as? com.ermao.library.shared.modules.reader.ReaderNavigationTargetPdf)?.pageIndex?.takeIf(::isValidPage)
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
        }
        val restorePage = explicitPage ?: restorePlan.candidates.firstNotNullOfOrNull { candidate ->
            when (candidate) {
                is ReaderRestorePdfPage -> candidate.pageIndex.takeIf(::isValidPage)
                is ReaderRestoreExactLocalLocation ->
                    (candidate.location as? PdfReaderLocation)?.pageIndex?.takeIf(::isValidPage)
                else -> null
            }
        }
        val initialLocator = restorePage?.let(positions::get)
        expectedRestorePage = restorePage
        if ((restorePlan.localProgress != null || restorePlan.remoteSnapshot != null) && initialLocator == null) {
            publishReaderRestoreWarning(_restoreWarning, "pdf", "candidate_resolution")
        } else if (restorePlan.usesLocalExact) {
            val location = restorePlan.localProgress?.location as? PdfReaderLocation
            _currentLocation.value = location
            lastPersistedLocation = location
        }
        tableOfContents = pages.map { page ->
            ReaderTocEntry(
                title = page.title,
                location = page.pageIndex.toLocation(),
                id = "pdf-page-${page.pageIndex}",
                index = page.pageIndex,
            )
        }
        val factory = navigatorFactory(opened, initialLocator)
        @Suppress("UNCHECKED_CAST")
        val created = factory.instantiate(classLoader, PdfNavigatorFragment::class.java.name)
            as PdfNavigatorFragment<*, *>
        navigator = created
        return created
    }

    private suspend fun openPublication(): Publication = when (val currentSource = source) {
        is LocalReaderSource -> openLocalPublication(currentSource)
        is RemoteByteRangeReaderSource -> openRemotePublication(currentSource)
        is RemoteComicReaderSource -> throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
    }

    private suspend fun openLocalPublication(localSource: LocalReaderSource): Publication {
        val file = try {
            publicationStore.resolve(localSource)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        }
        return openPdfiumPublication(
            dataSource = AndroidLocalPdfiumDataSource(file),
            identifier = localSource.resourceId,
            title = localSource.displayTitle,
        )
    }

    private suspend fun openRemotePublication(remoteSource: RemoteByteRangeReaderSource): Publication {
        val configuration = remotePdfium
            ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ReaderEngineError))
        val identity = PdfRangeCacheIdentity(
            namespace = remoteSource.namespace,
            resourceId = remoteSource.resourceId,
        )
        val loader = PdfRangeLoader(
            source = remoteSource,
            identity = identity,
            cache = configuration.cache,
            server = configuration.server,
        )
        return openPdfiumPublication(
            dataSource = AndroidRemotePdfiumDataSource(remoteSource.expectedSizeBytes, loader),
            identifier = remoteSource.resourceId,
            title = remoteSource.displayTitle,
        )
    }

    private suspend fun openPdfiumPublication(
        dataSource: AndroidPdfiumDataSource,
        identifier: String,
        title: String,
    ): Publication = try {
        val document = ShukuPdfiumDocument.open(dataSource, identifier)
        nativeDocument = document
        createShukuPdfPublication(
            identifier = identifier,
            title = title,
            pages = pageHints(document.pageCount),
        )
    } catch (failure: ReaderOpenFailure) {
        closeNativeDocument()
        throw failure
    } catch (failure: PdfRangeFailure) {
        closeNativeDocument()
        val safeContext = failure.safetyFailure?.let { safety ->
            mapOf("ruleId" to safety.ruleId, "errorCode" to safety.errorCode)
        }.orEmpty()
        throw ReaderOpenFailure(ReaderError(failure.code, safeContext), cause = failure)
    } catch (failure: ShukuPdfiumFailure) {
        closeNativeDocument()
        throw ReaderOpenFailure(ReaderError(failure.code, failure.safeContext), cause = failure)
    } catch (failure: OutOfMemoryError) {
        closeNativeDocument()
        throw ReaderOpenFailure(ReaderError(ReaderErrorCode.OutOfMemoryRisk), cause = failure)
    } catch (failure: RuntimeException) {
        closeNativeDocument()
        throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ReaderEngineError), cause = failure)
    }

    private fun navigatorFactory(opened: Publication, initialLocator: Locator?): FragmentFactory {
        val document = checkNotNull(nativeDocument) { "PDFium document is not open" }
        return org.readium.r2.navigator.pdf.PdfNavigatorFactory(
            opened,
            ShukuPdfiumEngineProvider(document),
        ).createFragmentFactory(initialLocator = initialLocator)
    }

    override fun bind(scope: CoroutineScope) {
        val currentNavigator = checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        progressCoordinator?.let { coordinator ->
            scope.launch {
                coordinator.remoteProgressNotices.collectLatest { notice ->
                    val snapshot = notice?.snapshot
                    val location = snapshot?.locator as? PdfPublicationLocation
                    remoteTarget = snapshot?.takeIf { location?.pageIndex?.let(::isValidPage) == true }
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
                val page = locator.pageIndex()?.takeIf(::isValidPage) ?: run {
                    publishReaderRestoreWarning(_restoreWarning, "pdf", "locator_mapping")
                    return@collectLatest
                }
                val location = page.toLocation()
                _currentLocation.value = location
                expectedRestorePage?.let { expected ->
                    expectedRestorePage = null
                    if (expected != page) {
                        publishReaderRestoreWarning(_restoreWarning, "pdf", "exact_locator_verification")
                        return@collectLatest
                    }
                }
                val target = remoteTarget
                val targetLocation = target?.locator as? PdfPublicationLocation
                if (targetLocation?.pageIndex == page) {
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
        val pdf = location as? PdfReaderLocation ?: return false
        if (!isValidPage(pdf.pageIndex)) return false
        requestedNavigationTarget = com.ermao.library.shared.modules.reader.ReaderNavigationTargetPdf(pdf.pageIndex)
        expectedRestorePage = pdf.pageIndex
        return navigator?.go(positions[pdf.pageIndex], animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val page = (positions.lastIndex * totalProgression).toInt().coerceIn(positions.indices)
        return goTo(page.toLocation())
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
        val location = (remoteTarget?.locator as? PdfPublicationLocation)?.pageIndex?.toLocation() ?: return false
        val moved = goTo(location)
        if (!moved) _resumeActionFailed.value = true
        return moved
    }
    override fun updatePreferences(updated: ReaderPreferences) {
        val supported = enforceAndroidSinglePagePreferences(updated)
        if (_preferences.value == supported) return
        persistPreferences(supported)
        _preferences.value = supported
    }
    override fun toggleCurrentBookmark(): ReaderBookmarkChange? = null
    override fun removeBookmark(id: String) = Unit
    override fun goToBookmark(id: String): Boolean = false
    override suspend fun flush() { (_currentLocation.value as? PdfReaderLocation)?.let { persist(it) } }
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
        positions = emptyList()
        publication?.close()
        publication = null
        closeNativeDocument()
    }

    private fun closeOpeningResources(opened: Publication) {
        opened.close()
        closeNativeDocument()
    }

    private fun closeNativeDocument() {
        nativeDocument?.close()
        nativeDocument = null
        remotePdfium?.cache?.clear()
    }

    private fun isValidPage(pageIndex: Int): Boolean = pageIndex in 0 until pageCount
    private fun pageHints(count: Int): List<ReaderPdfPage> = List(count) { index ->
        ReaderPdfPage(index, canonicalPages.getOrNull(index)?.title ?: "${index + 1}")
    }
    private fun Int.toLocation() = PdfReaderLocation(
        pageIndex = this,
        pageProgression = 0.0,
    )
    private fun Locator.pageIndex(): Int? = locations.position?.minus(1)
    private suspend fun loadProgressSafely(): ReaderProgress? = try {
        progressStore.load(source.resourceId)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (error: Exception) {
        publishReaderRestoreWarning(_restoreWarning, "pdf", "progress_load", error)
        null
    }
    private suspend fun persist(location: PdfReaderLocation) = saveMutex.withLock {
        if (lastPersistedLocation == location) return@withLock
        val capturedAt = nowEpochMillis()
        val percent = if (pageCount == 1) 100.0 else
            location.pageIndex.toDouble() / (pageCount - 1) * 100.0
        val progress = ReaderProgress(source.resourceId, location, capturedAt, deviceIdentity.stableDeviceId(), percent)
        try {
            progressStore.save(progress)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return@withLock
        }
        lastPersistedLocation = location
        _restoreWarning.value = null
        val namespace = presentationNamespaceKey ?: return@withLock
        val bookId = source.bookId ?: return@withLock
        publishProgressUpdate(createReaderProgressPresentationUpdate(
            namespaceKey = namespace,
            bookId = bookId,
            resourceId = source.resourceId,
            percent = percent,
            progress = progress,
            chapterTitle = null,
        ))
    }

    private companion object { const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L }
}

internal data class AndroidRemotePdfiumSessionConfiguration(
    val cache: PdfRangeMemory,
    val server: PdfRangeServerPort,
)
