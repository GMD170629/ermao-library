package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.PdfPublicationLocation
import com.ermao.library.shared.modules.reader.ReaderRestoreExactLocalLocation
import com.ermao.library.shared.modules.reader.ReaderRestorePdfPage
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
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
import org.readium.adapter.pdfium.navigator.PdfiumEngineProvider
import org.readium.adapter.pdfium.navigator.PdfiumNavigatorFactory
import org.readium.adapter.pdfium.navigator.PdfiumNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.isRestricted
import org.readium.r2.shared.publication.services.positions
import org.readium.r2.shared.util.getOrElse

@OptIn(ExperimentalReadiumApi::class)
internal class ReadiumPdfSession(
    private val source: LocalReaderSource,
    private val expectedPageCount: Int,
    private val publicationStore: AndroidReaderPublicationStore,
    private val progressStore: ReaderProgressStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val remoteSnapshot: ReaderProgressSnapshotV4? = null,
    private val progressCoordinator: ReaderProgressSyncCoordinator? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val persistPreferences: (ReaderPreferences) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
    private val presentationNamespaceKey: String? = null,
    private val publishProgressUpdate: (ReaderProgressPresentationUpdate) -> Unit = {},
) : AndroidReaderNavigatorSession {
    override val capabilities = ReaderCapabilities(
        canGoPrevious = true, canGoNext = true, hasTableOfContents = true,
        supportsBookmarks = false, supportsAnnotations = false, supportsTheme = true,
        supportsSystemTheme = true, supportsFontSize = false, supportsFontFamily = false,
        supportsFontWeight = false, supportsLineHeight = false,
        supportsPositiveLetterSpacing = false, supportsNegativeLetterSpacing = false,
        supportsPageMargins = false, supportsPageWidth = false, supportsReadingMode = false,
        supportsSpreadMode = false, supportsParagraphLayout = false,
        supportsIndependentPublisherStyles = false, supportsProgressStyles = true,
        supportsClock = true, supportsKeepAwake = true, supportsTapZones = true,
        supportsSwipeToggle = false, supportsPageTurnAnimation = false,
        supportsSmartOptimization = false, supportsKeyboardPageTurn = true,
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
    private var navigator: PdfiumNavigatorFragment? = null
    private var positions: List<Locator> = emptyList()
    private var locationJob: Job? = null
    private var lastPersistedLocation: PdfReaderLocation? = null
    private var expectedRestorePage: Int? = null
    private var remoteTarget: ReaderProgressSnapshotV4? = null
    private var awaitingInitialObservation = true
    private var prepared = false
    private val saveMutex = Mutex()

    @Suppress("UNCHECKED_CAST")
    override suspend fun prepare(classLoader: ClassLoader): PdfiumNavigatorFragment {
        check(!prepared) { "Reader session is already prepared" }
        prepared = true
        val file = try {
            publicationStore.resolveVerified(source)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        }
        val asset = readium.assetRetriever.retrieve(file).getOrElse { error ->
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile), ReadiumOpeningDiagnostic.AssetRetrieval(error))
        }
        val opened = readium.publicationOpener.open(asset, allowUserInteraction = false).getOrElse { error ->
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ParseFailed), ReadiumOpeningDiagnostic.PublicationOpening(error))
        }
        if (opened.isRestricted) {
            opened.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.DrmProtected))
        }
        if (!opened.conformsTo(Publication.Profile.PDF)) {
            opened.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
        }
        val openedPageCount = opened.metadata.numberOfPages
        if (openedPageCount == null || openedPageCount <= 0 || openedPageCount != expectedPageCount) {
            opened.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile))
        }
        publication = opened
        positions = opened.positions()
        if (positions.size != expectedPageCount) {
            release()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile))
        }

        val localProgress = loadProgressSafely()
        val decision = decideReaderResume(localProgress, remoteSnapshot, source)
        val restorePlan = planReaderProgressRestore(
            decision.selected?.localProgress,
            decision.selected?.remoteSnapshot,
            source,
        )
        val restorePage = restorePlan.candidates.firstNotNullOfOrNull { candidate ->
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
            _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        } else if (restorePlan.usesLocalExact) {
            val location = restorePlan.localProgress?.location as? PdfReaderLocation
            _currentLocation.value = location
            lastPersistedLocation = location
        }
        tableOfContents = opened.tableOfContents.mapNotNull { link ->
            val locator = opened.locatorFromLink(link) ?: return@mapNotNull null
            val page = locator.pageIndex() ?: return@mapNotNull null
            ReaderTocEntry(link.title ?: "${page + 1}", page.toLocation())
        }
        val factory = PdfiumNavigatorFactory(opened, PdfiumEngineProvider()).createFragmentFactory(
            initialLocator = initialLocator,
        )
        return (factory.instantiate(classLoader, PdfiumNavigatorFragment::class.java.name) as PdfiumNavigatorFragment)
            .also { navigator = it }
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
                    _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
                    return@collectLatest
                }
                val location = page.toLocation()
                _currentLocation.value = location
                expectedRestorePage?.let { expected ->
                    expectedRestorePage = null
                    if (expected != page) {
                        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
                        return@collectLatest
                    }
                }
                val target = remoteTarget
                val targetLocation = target?.locator as? PdfPublicationLocation
                if (targetLocation?.pageIndex == page) {
                    progressCoordinator?.acceptVerifiedRemoteProgress(
                        ReaderProgress(source.sourceId, location, nowEpochMillis(), deviceIdentity.stableDeviceId()),
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

    override fun goPrevious(): Boolean = navigator?.goBackward(animated = true) ?: false
    override fun goNext(): Boolean = navigator?.goForward(animated = true) ?: false

    override fun goTo(location: ReaderLocation): Boolean {
        val pdf = location as? PdfReaderLocation ?: return false
        if (pdf.contentFingerprint != source.contentFingerprint || !isValidPage(pdf.pageIndex)) return false
        expectedRestorePage = pdf.pageIndex
        return navigator?.go(positions[pdf.pageIndex], animated = true) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val page = (positions.lastIndex * totalProgression).toInt().coerceIn(positions.indices)
        return goTo(page.toLocation())
    }

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
        if (_preferences.value == updated) return
        _preferences.value = updated
        persistPreferences(updated)
    }
    override fun toggleCurrentBookmark() = Unit
    override fun removeBookmark(id: String) = Unit
    override fun goToBookmark(id: String): Boolean = false
    override suspend fun flush() { (_currentLocation.value as? PdfReaderLocation)?.let { persist(it) } }
    override suspend fun close() { flush(); release() }
    override fun release() {
        locationJob?.cancel()
        locationJob = null
        navigator = null
        positions = emptyList()
        publication?.close()
        publication = null
    }

    private fun isValidPage(pageIndex: Int): Boolean = pageIndex in 0 until expectedPageCount
    private fun Int.toLocation() = PdfReaderLocation(
        pageIndex = this,
        pageProgression = 0.0,
        contentFingerprint = source.contentFingerprint,
    )
    private fun Locator.pageIndex(): Int? = locations.position?.minus(1)
    private suspend fun loadProgressSafely(): ReaderProgress? = try {
        progressStore.load(source.sourceId)
    } catch (_: IllegalArgumentException) {
        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        null
    }
    private suspend fun persist(location: PdfReaderLocation) = saveMutex.withLock {
        if (lastPersistedLocation == location) return@withLock
        val capturedAt = nowEpochMillis()
        val percent = if (expectedPageCount == 1) 100.0 else
            location.pageIndex.toDouble() / (expectedPageCount - 1) * 100.0
        val progress = ReaderProgress(source.sourceId, location, capturedAt, deviceIdentity.stableDeviceId(), percent)
        progressStore.save(progress)
        lastPersistedLocation = location
        val namespace = presentationNamespaceKey ?: return@withLock
        val workId = source.workId ?: return@withLock
        publishProgressUpdate(createReaderProgressPresentationUpdate(
            namespaceKey = namespace,
            workId = workId,
            volumeId = source.volumeId ?: source.sourceId,
            percent = percent,
            progress = progress,
            chapterTitle = null,
        ))
    }

    private companion object { const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L }
}
