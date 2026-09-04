package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.features.reader.application.ReaderStartupPositionSource
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.domain.mergeReaderBookmarks
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.ReaderSafetyImplementationException
import com.ermao.library.shared.modules.reader.readerSafetyDrmFailure
import com.ermao.library.shared.modules.reader.readerErrorCodeForFailure
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderNavigationTarget
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetInvalid
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderWritingMode
import com.ermao.library.shared.modules.reader.ReaderReadingProgression
import com.ermao.library.shared.modules.reader.ReaderPageTurnDirection
import com.ermao.library.shared.modules.reader.ReaderNavigationPolicy
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderChapterPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionSyncingStore
import com.ermao.library.shared.modules.reader.ReaderPositionReportJson
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import java.io.FileNotFoundException
import java.math.BigDecimal
import java.time.Instant
import java.util.logging.Level
import java.util.logging.Logger
import kotlin.math.abs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.readium.r2.navigator.epub.EpubNavigatorFactory
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.toDebugDescription
import org.readium.r2.shared.publication.services.isRestricted
import org.readium.r2.shared.publication.services.positions
import org.readium.r2.shared.publication.services.search.search
import org.readium.r2.shared.util.asset.AssetRetriever
import org.readium.r2.shared.util.getOrElse
import org.readium.r2.streamer.PublicationOpener
import com.ermao.library.mobi.infrastructure.MobiPublicationErrorKind
import com.ermao.library.mobi.infrastructure.MobiPublicationOpenException
import com.ermao.library.mobi.infrastructure.MobiReadiumPublication
import com.ermao.library.mobi.infrastructure.MobiReadiumPublicationFactory
import com.ermao.library.shared.modules.reader.ReaderFormat

internal class ReaderOpenFailure(
    val readerError: ReaderError,
    val diagnostic: ReadiumOpeningDiagnostic? = null,
    cause: Throwable? = null,
) : IllegalStateException(readerError.code.wireValue, cause)

internal sealed interface ReadiumOpeningDiagnostic {
    data class AssetRetrieval(val error: AssetRetriever.RetrieveError) : ReadiumOpeningDiagnostic

    data class PublicationOpening(val error: PublicationOpener.OpenError) : ReadiumOpeningDiagnostic
}

private val bookmarkPositionJson = ReaderPositionReportJson()
private const val RESTORE_PROGRESSION_EPSILON = 0.02

/**
 * Checks the navigation identity of a persisted Readium locator against the
 * first locator observed from the newly-created navigator.
 *
 * The complete locator remains opaque for persistence and transport.  This
 * small adapter-side check only answers whether the engine opened the
 * selected resource/anchor; it deliberately does not require a non-empty
 * text highlight (Readium is allowed to return an empty one).
 */
internal fun readiumLocatorMatchesRestoreCandidate(
    expected: Locator,
    actual: Locator,
): Boolean = readiumNavigationMatchesRestoreCandidate(
    expectedHref = expected.href.toString(),
    actualHref = actual.href.toString(),
    expectedFragments = expected.locations.fragments,
    actualFragments = actual.locations.fragments,
    expectedPosition = expected.locations.position,
    actualPosition = actual.locations.position,
    expectedProgression = expected.locations.progression,
    actualProgression = actual.locations.progression,
)

/**
 * Verifies only the navigation identity exposed by a Readium location event.
 * Text/highlight and all other locator fields stay outside this check.
 */
internal fun readiumNavigationMatchesRestoreCandidate(
    expectedHref: String,
    actualHref: String,
    expectedFragments: List<String>,
    actualFragments: List<String>,
    expectedPosition: Int?,
    actualPosition: Int?,
    expectedProgression: Double?,
    actualProgression: Double?,
): Boolean {
    if (expectedHref.substringBefore('#') != actualHref.substringBefore('#')) {
        return false
    }
    if (expectedFragments.isNotEmpty() && expectedFragments != actualFragments) {
        return false
    }
    expectedPosition?.let { position ->
        if (actualPosition != position) return false
    }
    expectedProgression?.let { progression ->
        val observedProgression = actualProgression ?: return false
        if (abs(observedProgression - progression) > RESTORE_PROGRESSION_EPSILON) return false
    }
    return true
}

private fun AndroidReaderBookmarkRecord.shared(): ReaderBookmark? = runCatching {
    ReaderBookmark(
        id = id,
        position = bookmarkPositionJson.decode(positionJson),
        label = label,
        createdAt = createdAt,
    )
}.getOrNull()

private fun ReaderBookmark.record(): AndroidReaderBookmarkRecord = AndroidReaderBookmarkRecord(
    id = id,
    positionJson = bookmarkPositionJson.encode(position),
    label = label,
    createdAt = createdAt,
)

@OptIn(ExperimentalReadiumApi::class)
internal class ReadiumEpubSession(
    private val source: LocalReaderSource,
    private val publicationStore: AndroidReaderPublicationStore,
    private val progressStore: ReaderPositionSyncingStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val locatorMapper: ReadiumLocatorMapper,
    private val preferencesMapper: ReadiumPreferencesMapper,
    private val remoteSnapshot: ReaderProgressSnapshotV5? = null,
    private val initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null,
    private val startupPositionSource: ReaderStartupPositionSource = ReaderStartupPositionSource.Start,
    private val progressCoordinator: com.ermao.library.shared.modules.reader.ReaderPositionSyncCoordinator? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val persistPreferences: (ReaderPreferences) -> Unit = {},
    private val bookmarkStore: AndroidReaderBookmarkStore? = null,
    private val bookmarkSyncPort: ReaderBookmarkSyncPort? = null,
    private val bookmarkSyncTarget: ReaderBookmarkSyncTarget? = null,
    private val externalLinkHandler: (String) -> Unit = {},
    private val onUnhandledTap: (Float) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
    private val presentationNamespaceKey: String? = null,
    private val publishProgressUpdate: (ReaderProgressPresentationUpdate) -> Unit = {},
) : AndroidReaderNavigatorSession {
    override var requestedNavigationTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = initialTarget
        private set
    override val morphology = ReaderMorphology.Reflowable
    override var capabilities: ReaderCapabilities = ReaderCapabilities.epub(
        supportsVolumeKeys = true,
        supportsCustomFonts = true,
    ).copy(supportsPageWidth = true)
        private set
    private val _currentLocation = MutableStateFlow<ReaderLocation?>(null)
    override val currentLocation: StateFlow<ReaderLocation?> = _currentLocation.asStateFlow()
    private val _presentationProgress = MutableStateFlow<Double?>(null)
    override val presentationProgress: StateFlow<Double?> = _presentationProgress.asStateFlow()

    private val _preferences = MutableStateFlow(initialPreferences)
    override val preferences: StateFlow<ReaderPreferences> = _preferences.asStateFlow()

    private val _restoreWarning = MutableStateFlow<ReaderError?>(null)
    override val restoreWarning: StateFlow<ReaderError?> = _restoreWarning.asStateFlow()

    private val _resumeNotice = MutableStateFlow<ReaderResumeNotice?>(null)
    override val resumeNotice: StateFlow<ReaderResumeNotice?> = _resumeNotice.asStateFlow()

    private val _resumeActionFailed = MutableStateFlow(false)
    override val resumeActionFailed: StateFlow<Boolean> = _resumeActionFailed.asStateFlow()

    private val _bookmarks = MutableStateFlow<List<ReaderBookmark>>(emptyList())
    override val bookmarks: StateFlow<List<ReaderBookmark>> = _bookmarks.asStateFlow()

    private val _bookmarkSyncPending = MutableStateFlow(false)
    override val bookmarkSyncPending: StateFlow<Boolean> = _bookmarkSyncPending.asStateFlow()

    private val _contentError = MutableStateFlow<ReaderError?>(null)
    override val contentError: StateFlow<ReaderError?> = _contentError.asStateFlow()

    private val saveMutex = Mutex()
    private val viewportNavigationMutex = Mutex()
    private val bookmarkSyncMutex = Mutex()
    private val contentsMutex = Mutex()
    private var bookmarkRecords: List<AndroidReaderBookmarkRecord> = emptyList()
    private var publication: Publication? = null
    private var mobiPublication: MobiReadiumPublication? = null
    private var navigator: EpubNavigatorFragment? = null
    private var publicationPositionIndex = ReadiumPublicationPositionIndex.Empty
    private var locationJob: Job? = null
    private var bookmarkScope: CoroutineScope? = null
    private var removedBookmark: AndroidReaderBookmarkRecord? = null
    private var lastPersistedReport: ReaderPositionReport? = null
    private var lastObservedLocator: Locator? = null
    private var expectedRestoreLocator: Locator? = null
    private var failedRestoreLocator: Locator? = null
    private var restoreFailed = false
    private var awaitingInitialObservation = true
    private var hasLocalReadingActivity = false
    private var suppressNextPreferenceLocation = false
    private var currentPageUnreadable = false
    private var prepared = false
    private var contentsLoaded = false
    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    private suspend fun openLocalPublication(): Publication {
        val file = try {
            publicationStore.resolve(source)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        }
        return if (source.sourceFormat == ReaderSourceFormat.Fb2) {
            try {
                Fb2ReadiumPublicationFactory().open(file, source.displayTitle)
            } catch (error: ReaderSafetyException) {
                throw readerOpenFailure(error)
            } catch (error: IllegalArgumentException) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ParseFailed), cause = error)
            }
        } else if (source.format == ReaderFormat.Mobi) {
            val opened = try {
                MobiReadiumPublicationFactory().open(file, EpubContentSecurityPolicy::applyMobi)
            } catch (error: ReaderSafetyException) {
                throw readerOpenFailure(error)
            } catch (error: MobiPublicationOpenException) {
                throw ReaderOpenFailure(ReaderError(error.kind.toReaderErrorCode()), cause = error)
            }
            mobiPublication = opened
            opened.publication
        } else if (source.format == ReaderFormat.Text) {
            try {
                TxtReadiumPublicationFactory().open(file, source.displayTitle)
            } catch (error: ReaderSafetyException) {
                throw readerOpenFailure(error)
            } catch (error: com.ermao.library.shared.modules.reader.TxtPublicationEmptyException) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.TxtEmpty), cause = error)
            } catch (error: IllegalArgumentException) {
                val code = if (error.cause is java.nio.charset.CharacterCodingException) {
                    ReaderErrorCode.TxtEncodingUnsupported
                } else ReaderErrorCode.ParseFailed
                throw ReaderOpenFailure(ReaderError(code), cause = error)
            }
        } else {
            try {
                AndroidEpubArchiveSafetyPreflight.verify(file)
            } catch (error: ReaderSafetyException) {
                throw readerOpenFailure(error)
            } catch (error: ReaderSafetyImplementationException) {
                throw readerOpenFailure(error)
            }
            val asset = readium.assetRetriever.retrieve(file).getOrElse { error ->
                throw ReaderOpenFailure(
                    ReaderError(ReaderErrorCode.CorruptFile),
                    diagnostic = ReadiumOpeningDiagnostic.AssetRetrieval(error),
                )
            }
            readium.publicationOpener.open(
                asset = asset,
                allowUserInteraction = false,
                onCreatePublication = {
                    container = EpubContentSecurityPolicy.apply(container)
                },
            ).getOrElse { error ->
                throw ReaderOpenFailure(
                    ReaderError(ReaderErrorCode.ParseFailed),
                    diagnostic = ReadiumOpeningDiagnostic.PublicationOpening(error),
                )
            }
        }
    }

    private fun readerOpenFailure(error: ReaderSafetyException): ReaderOpenFailure = ReaderOpenFailure(
        ReaderError(
            readerErrorCodeForFailure(error.failure.errorCode, recoverable = false),
            safeContext = mapOf(
                "ruleId" to error.failure.ruleId,
                "errorCode" to error.failure.errorCode,
            ),
            cause = error,
        ),
        cause = error,
    )

    private fun readerOpenFailure(error: ReaderSafetyImplementationException): ReaderOpenFailure = ReaderOpenFailure(
        ReaderError(
            readerErrorCodeForFailure(error.failure.errorCode, recoverable = false),
            safeContext = mapOf(
                "ruleId" to error.failure.ruleId,
                "errorCode" to error.failure.errorCode,
            ),
            cause = error,
        ),
        cause = error,
    )

    override suspend fun prepare(classLoader: ClassLoader): EpubNavigatorFragment {
        check(!prepared) { "Reader session is already prepared" }
        prepared = true
        val openedPublication = openLocalPublication()
        if (openedPublication.isRestricted) {
            openedPublication.close()
            throw readerOpenFailure(ReaderSafetyException(readerSafetyDrmFailure()))
        }
        if (!openedPublication.conformsTo(Publication.Profile.EPUB)) {
            openedPublication.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
        }
        publication = openedPublication
        val supportsTextLayout = openedPublication.metadata.layout != org.readium.r2.shared.publication.Layout.FIXED
        capabilities = capabilities.copy(
            supportsReadingProgression = supportsTextLayout,
            supportsWritingMode = supportsTextLayout,
        )
        progressCoordinator?.beginSession(remoteSnapshot)
        publicationPositionIndex = ReadiumPublicationPositionIndex.from(
            openedPublication.positions(),
            openedPublication.readingOrder.flatMap { link ->
                listOf(
                    link.href.toString().substringBefore('#'),
                    openedPublication.url(link).toString().substringBefore('#'),
                )
            }.distinct(),
        )
        runCatching { bookmarkStore?.load() }.getOrNull()?.let { state ->
            bookmarkRecords = state.bookmarks
            _bookmarks.value = state.bookmarks.mapNotNull(AndroidReaderBookmarkRecord::shared)
            _bookmarkSyncPending.value = state.pending != null
        }

        val explicitLocator = initialTarget?.let { target ->
            val href = (target as? ReaderNavigationTargetReflowable)?.href
            val link = href?.let { Url(it) }?.let { Link(href = it) }
            link?.let { openedPublication.locatorFromLink(it) }
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
        val initialLocator = when {
            explicitLocator != null -> explicitLocator
            localPosition != null -> positionLocator(localPosition.position)
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
            startupPositionSource == ReaderStartupPositionSource.ServerSnapshot && remoteSnapshot != null ->
                positionLocator(remoteSnapshot.position)
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
            else -> null
        }
        expectedRestoreLocator = initialLocator
        if (localPosition != null) {
            val restoredLocalLocator = checkNotNull(initialLocator)
            _currentLocation.value = locatorMapper.toDomain(restoredLocalLocator)
            _presentationProgress.value = positionReport(restoredLocalLocator).presentation.totalProgression
            lastPersistedReport = localPosition.position
        }

        val fragmentFactory = EpubNavigatorFactory(openedPublication).createFragmentFactory(
            initialLocator = initialLocator,
            initialPreferences = preferencesMapper.toReadium(
                _preferences.value,
                supportsTextLayout = capabilities.supportsWritingMode,
            ),
            configuration = readerNavigatorConfiguration(),
            listener = object : EpubNavigatorFragment.Listener {
                override fun onResourceLoadFailed(href: Url, error: ReadError) {
                    @Suppress("UNUSED_VARIABLE")
                    val ignoredBoundaryDetails = href to error
                    LOGGER.log(
                        Level.SEVERE,
                        "reader_error platform=android format=epub entry=reader stage=resource_load " +
                            "code=READIUM_RESOURCE_LOAD_FAILED",
                    )
                }

                override fun onExternalLinkActivated(url: org.readium.r2.shared.util.AbsoluteUrl) {
                    externalLinkHandler(url.toString())
                }
            },
        )
        val created = fragmentFactory.instantiate(classLoader, EpubNavigatorFragment::class.java.name)
            as EpubNavigatorFragment
        navigator = created
        created.addInputListener(object : org.readium.r2.navigator.input.InputListener {
            override fun onTap(event: org.readium.r2.navigator.input.TapEvent): Boolean {
                onUnhandledTap(event.point.x / (created.view?.width ?: 1).coerceAtLeast(1))
                return true
            }
            override fun onDrag(event: org.readium.r2.navigator.input.DragEvent): Boolean {
                suppressNextPreferenceLocation = false
                return false
            }
        })
        return created
    }


    override fun bind(scope: CoroutineScope) {
        checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        bookmarkScope = scope
        locationJob = scope.launch {
            checkNotNull(navigator).currentLocator.collectLatest { locator ->
                lastObservedLocator = locator
                val mapped = locatorMapper.toDomain(locator)
                val eventReport = positionReport(locator)
                _currentLocation.value = mapped
                _presentationProgress.value = eventReport.presentation.totalProgression
                if (awaitingInitialObservation) {
                    awaitingInitialObservation = false
                    val expected = expectedRestoreLocator
                    expectedRestoreLocator = null
                    if (expected != null && !readiumLocatorMatchesRestoreCandidate(expected, locator)) {
                        restoreFailed = true
                        failedRestoreLocator = locator
                        publishReaderRestoreWarning(_restoreWarning, "epub", "initial_locator_verification")
                    }
                    return@collectLatest
                }
                if (restoreFailed) {
                    // Keep fencing repeated observations of the failed candidate. A later
                    // different observation is a gesture/navigation event and may be saved.
                    if (failedRestoreLocator == locator) return@collectLatest
                    restoreFailed = false
                    failedRestoreLocator = null
                }
                if (suppressNextPreferenceLocation) {
                    return@collectLatest
                }
                hasLocalReadingActivity = true
                if (_resumeNotice.value != null) {
                    hideResumeNotice()
                }
                delay(LOCAL_SAVE_DEBOUNCE_MILLIS)
                val observedLocation = locatorMapper.toDomain(locator)
                val observedReport = positionReport(locator)
                _currentLocation.value = observedLocation
                _presentationProgress.value = observedReport.presentation.totalProgression
                currentPageUnreadable = isUnreadablePage(observedLocation)
                if (!currentPageUnreadable) persist(locator, observedReport)
            }
        }
        if (bookmarkStore != null && bookmarkSyncPort != null && bookmarkSyncTarget != null) {
            scope.launch { refreshBookmarksFromServer() }
            scope.launch { flushBookmarkOutbox() }
        }
    }

    override fun goPrevious(): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
        restoreFailed = false
        failedRestoreLocator = null
        expectedRestoreLocator = null
        if (isContinuousScroll(_preferences.value)) {
            return advanceContinuousScroll(direction = ReaderPageTurnDirection.Previous)
        }
        return navigator?.goBackward(animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goNext(): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
        restoreFailed = false
        failedRestoreLocator = null
        expectedRestoreLocator = null
        if (isContinuousScroll(_preferences.value)) {
            return advanceContinuousScroll(direction = ReaderPageTurnDirection.Next)
        }
        return navigator?.goForward(animated = navigationAnimationsEnabled()) ?: false
    }

    private fun isContinuousScroll(preferences: ReaderPreferences): Boolean =
        preferences.epub.flow == ReaderReadingMode.ContinuousScroll ||
            (capabilities.supportsWritingMode && preferences.epub.writingMode == ReaderWritingMode.Vertical)

    private fun advanceContinuousScroll(direction: ReaderPageTurnDirection): Boolean {
        val activeNavigator = navigator ?: return false
        val activeScope = bookmarkScope ?: return false
        val animated = navigationAnimationsEnabled()
        val epub = _preferences.value.epub
        val writingMode = if (capabilities.supportsWritingMode) epub.writingMode else ReaderWritingMode.Horizontal
        val readingProgression = if (capabilities.supportsReadingProgression) {
            epub.readingProgression
        } else {
            ReaderReadingProgression.LeftToRight
        }
        activeScope.launch(Dispatchers.Main.immediate) {
            viewportNavigationMutex.withLock {
                val result = runCatching {
                    activeNavigator.evaluateJavascript(
                        continuousScrollViewportScript(
                            direction = direction,
                            animated = animated,
                            writingMode = writingMode,
                            readingProgression = readingProgression,
                        ),
                    ).orEmpty().trim().trim('"')
                }.getOrDefault("unavailable")
                if (result == "moved" && animated) {
                    awaitContinuousScrollSettle(
                        activeNavigator,
                        writingMode,
                        readingProgression,
                    )
                }
                if (result == "boundary") {
                    goToAdjacentScrollResource(activeNavigator, direction, writingMode, readingProgression)
                }
            }
        }
        return true
    }

    private suspend fun awaitContinuousScrollSettle(
        activeNavigator: EpubNavigatorFragment,
        writingMode: ReaderWritingMode,
        readingProgression: ReaderReadingProgression,
    ) {
        var previous: Double? = null
        var stableSamples = 0
        repeat(SCROLL_SETTLE_SAMPLE_LIMIT) { sampleIndex ->
            delay(SCROLL_SETTLE_SAMPLE_MILLIS)
            val current = runCatching {
                activeNavigator.evaluateJavascript(
                    continuousScrollOffsetScript(writingMode, readingProgression),
                ).orEmpty().trim().trim('"').toDoubleOrNull()
            }.getOrNull() ?: return
            stableSamples = if (previous != null && abs(current - previous) <=
                ReaderNavigationPolicy.SCROLL_BOUNDARY_EPSILON_CSS_PIXELS
            ) stableSamples + 1 else 0
            if (sampleIndex >= SCROLL_SETTLE_MINIMUM_SAMPLE_INDEX &&
                stableSamples >= SCROLL_SETTLE_REQUIRED_SAMPLES
            ) return
            previous = current
        }
    }

    private suspend fun goToAdjacentScrollResource(
        activeNavigator: EpubNavigatorFragment,
        direction: ReaderPageTurnDirection,
        writingMode: ReaderWritingMode,
        readingProgression: ReaderReadingProgression,
    ) {
        val openedPublication = publication ?: return
        val resourceKey = activeNavigator.currentLocator.value.href.toString().substringBefore('#')
        val currentIndex = openedPublication.readingOrder.indexOfFirst { link ->
            link.href.toString().substringBefore('#') == resourceKey ||
                openedPublication.url(link).toString().substringBefore('#') == resourceKey
        }
        if (currentIndex < 0) return
        val offset = if (direction == ReaderPageTurnDirection.Next) 1 else -1
        val targetLink = openedPublication.readingOrder.getOrNull(currentIndex + offset) ?: return
        val baseLocator = openedPublication.locatorFromLink(targetLink) ?: return
        val target = baseLocator.copy(
            locations = Locator.Locations(
                progression = ReaderNavigationPolicy.adjacentResourceProgression(direction),
            ),
        )
        requestedNavigationTarget = ReaderNavigationTargetReflowable(target.href.toString())
        // A native cross-resource animation may complete after the next queued
        // command and overwrite its locator. Viewport turns remain animated;
        // resource commits are intentionally atomic.
        val accepted = activeNavigator.go(target, animated = false)
        if (!accepted) return
        val targetKey = target.href.toString().substringBefore('#')
        val loaded = withTimeoutOrNull(3_000) {
            activeNavigator.currentLocator.first {
                it.href.toString().substringBefore('#') == targetKey
            }
        } != null
        if (!loaded) return
        var stableSamples = 0
        repeat(SCROLL_SETTLE_SAMPLE_LIMIT) { sampleIndex ->
            val positioned = runCatching {
                activeNavigator.evaluateJavascript(
                    continuousScrollResourceEdgeScript(
                        direction,
                        writingMode,
                        readingProgression,
                    ),
                ).orEmpty().trim().trim('"').toBooleanStrictOrNull()
            }.getOrNull() == true
            stableSamples = if (positioned) stableSamples + 1 else 0
            if (sampleIndex >= RESOURCE_SETTLE_MINIMUM_SAMPLE_INDEX &&
                stableSamples >= SCROLL_SETTLE_REQUIRED_SAMPLES
            ) return
            delay(SCROLL_SETTLE_SAMPLE_MILLIS)
        }
    }

    override fun goTo(location: ReaderLocation): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
        restoreFailed = false
        failedRestoreLocator = null
        expectedRestoreLocator = null
        val openedPublication = publication ?: return false
        val target = locatorMapper.resourceLocator(location, openedPublication)
            ?: return false
        requestedNavigationTarget = com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable(target.href.toString())
        return navigator?.go(target, animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
        restoreFailed = false
        failedRestoreLocator = null
        expectedRestoreLocator = null
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val target = publicationPositionIndex.nearestLocator(totalProgression) ?: return false
        requestedNavigationTarget = com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable(target.href.toString())
        return navigator?.go(target, animated = navigationAnimationsEnabled()) ?: false
    }

    override suspend fun loadTableOfContents(): List<ReaderTocEntry> = contentsMutex.withLock {
        if (contentsLoaded) return@withLock tableOfContents
        val openedPublication = publication ?: return@withLock emptyList()
        val loaded = withContext(Dispatchers.Default) {
            buildTableOfContents(openedPublication)
        }
        tableOfContents = loaded
        contentsLoaded = true
        loaded
    }

    override fun dismissResumeNotice() {
        hideResumeNotice()
    }

    override fun dismissRestoreWarning() {
        _restoreWarning.value = null
    }

    private fun hideResumeNotice() {
        _resumeNotice.value = null
        _resumeActionFailed.value = false
    }

    /** Remote v5 snapshots are applied only while opening the next session. */
    override fun returnToResumeNotice(): Boolean = false

    override fun updatePreferences(updated: ReaderPreferences) {
        val active = checkNotNull(navigator) { "READER_NOT_READY" }
        val previous = _preferences.value
        val supported = updated
        if (previous == supported) return
        // Persistence precedes SDK submission. Reflow is owned by Readium.
        persistPreferences(supported)
        _preferences.value = supported
        val target = preferencesMapper.toReadium(supported, capabilities.supportsWritingMode)
        if (target != preferencesMapper.toReadium(previous, capabilities.supportsWritingMode)) {
            suppressNextPreferenceLocation = true
            active.submitPreferences(target)
        }
    }

    override fun unavailableControls(preferences: ReaderPreferences): Set<com.ermao.library.shared.modules.reader.ReaderControl> {
        val opened = publication ?: return com.ermao.library.shared.modules.reader.ReaderControl.entries.toSet()
        val native = preferencesMapper.toReadium(preferences, capabilities.supportsWritingMode)
        // A null textAlign means publisher default, not that selecting an alignment is unsupported.
        return EpubNavigatorFactory(opened).createPreferencesEditor(
            native.copy(textAlign = native.textAlign ?: org.readium.r2.navigator.preferences.TextAlign.START),
        ).unavailableReaderControls()
    }

    private fun navigationAnimationsEnabled(): Boolean =
        shouldAnimateAndroidReaderNavigation(_preferences.value, morphology)

    override fun toggleCurrentBookmark(): ReaderBookmarkChange? {
        if (currentPageUnreadable) return null
        val location = _currentLocation.value as? ReflowReaderLocation ?: return null
        val resourceKey = location.resourceKey ?: return null
        val locator = lastObservedLocator ?: return null
        val report = positionReport(locator)
        val id = bookmarkId(resourceKey, location.totalProgression ?: location.progression ?: 0.0)
        val existing = bookmarkRecords.firstOrNull { it.id == id }
        val added = existing == null
        val next = if (existing != null) {
            removedBookmark = existing
            bookmarkRecords.filterNot { it.id == id }
        } else {
            bookmarkRecords + AndroidReaderBookmarkRecord(
                id = id,
                positionJson = bookmarkPositionJson.encode(report),
                label = tableOfContents.firstOrNull {
                    (it.location as? ReflowReaderLocation)?.resourceKey == location.resourceKey
                }?.title ?: source.displayTitle,
                createdAt = Instant.ofEpochMilli(nowEpochMillis()).toString(),
            )
        }
        commitBookmarkMutation(next)
        return ReaderBookmarkChange(id, added)
    }

    override fun undoBookmarkChange(change: ReaderBookmarkChange): Boolean =
        if (change.added) {
            if (bookmarkRecords.none { it.id == change.bookmarkId }) {
                false
            } else {
                commitBookmarkMutation(bookmarkRecords.filterNot { it.id == change.bookmarkId })
                true
            }
        } else {
            undoBookmarkRemoval(change.bookmarkId)
        }

    override fun removeBookmark(id: String) {
        removedBookmark = bookmarkRecords.firstOrNull { it.id == id } ?: return
        commitBookmarkMutation(bookmarkRecords.filterNot { it.id == id })
    }

    override fun undoBookmarkRemoval(id: String): Boolean {
        val bookmark = removedBookmark?.takeIf { it.id == id } ?: return false
        if (bookmarkRecords.any { it.id == id }) return false
        removedBookmark = null
        commitBookmarkMutation(bookmarkRecords + bookmark)
        return true
    }

    override fun goToBookmark(id: String): Boolean {
        val record = bookmarkRecords.firstOrNull { it.id == id } ?: return false
        val locator = runCatching {
            Locator.fromJSON(org.json.JSONObject(
                bookmarkPositionJson.decode(record.positionJson).locator.canonicalJson,
            ))
        }.getOrNull() ?: return false
        restoreFailed = false
        failedRestoreLocator = null
        expectedRestoreLocator = null
        requestedNavigationTarget = ReaderNavigationTargetReflowable(locator.href.toString())
        return navigator?.go(locator, animated = navigationAnimationsEnabled()) ?: false
    }

    override suspend fun flush() {
        if (suppressNextPreferenceLocation || restoreFailed || !hasLocalReadingActivity) return
        val locator = lastObservedLocator ?: return
        val location = locatorMapper.toDomain(locator)
        _currentLocation.value = location
        if (isUnreadablePage(location)) return
        persist(locator)
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
        bookmarkScope = null
        navigator = null
        publication?.close()
        publication = null
        _presentationProgress.value = null
        mobiPublication?.close()
        mobiPublication = null
        publicationPositionIndex = ReadiumPublicationPositionIndex.Empty
        expectedRestoreLocator = null
        failedRestoreLocator = null
        restoreFailed = false
    }

    private fun commitBookmarkMutation(next: List<AndroidReaderBookmarkRecord>) {
        val store = bookmarkStore ?: return
        val ordered = next.sortedWith(compareBy<AndroidReaderBookmarkRecord>({
            runCatching { bookmarkPositionJson.decode(it.positionJson).presentation.displayPercent }
                .getOrDefault(0.0)
        }, { it.createdAt }, { it.id }))
        store.save(AndroidReaderBookmarkState(bookmarks = ordered, pending = ordered))
        bookmarkRecords = ordered
        _bookmarks.value = ordered.mapNotNull(AndroidReaderBookmarkRecord::shared)
        _bookmarkSyncPending.value = true
        bookmarkScope?.launch { flushBookmarkOutbox() }
    }

    private suspend fun refreshBookmarksFromServer() {
        val store = bookmarkStore ?: return
        val port = bookmarkSyncPort ?: return
        val target = bookmarkSyncTarget ?: return
        val response = port.load(target)
        if (!response.succeeded) return
        val state = store.load()
        val merged = mergeReaderBookmarks(
            local = state.bookmarks.mapNotNull(AndroidReaderBookmarkRecord::shared),
            remote = response.bookmarks,
            hasPendingLocalSnapshot = state.pending != null,
        )
        if (state.pending != null) return
        val localById = state.bookmarks.associateBy(AndroidReaderBookmarkRecord::id)
        val records = merged.map { bookmark ->
            localById[bookmark.id] ?: bookmark.record()
        }
        store.save(AndroidReaderBookmarkState(records, null))
        bookmarkRecords = records
        _bookmarks.value = merged
    }

    private suspend fun flushBookmarkOutbox() = bookmarkSyncMutex.withLock {
        val store = bookmarkStore ?: return@withLock
        val port = bookmarkSyncPort ?: return@withLock
        val target = bookmarkSyncTarget ?: return@withLock
        while (true) {
            val before = store.load()
            val pending = before.pending ?: break
            val response = port.replace(target, pending.mapNotNull(AndroidReaderBookmarkRecord::shared))
            if (!response.succeeded) break
            val latest = store.load()
            if (latest.pending != pending) continue
            val localById = latest.bookmarks.associateBy(AndroidReaderBookmarkRecord::id)
            val acknowledged = response.bookmarks.map { localById[it.id] ?: it.record() }
            store.save(AndroidReaderBookmarkState(acknowledged, null))
            bookmarkRecords = acknowledged
            _bookmarks.value = response.bookmarks
            _bookmarkSyncPending.value = false
            break
        }
    }

    private fun bookmarkId(resourceKey: String, progression: Double): String {
        val rounded = kotlin.math.round(progression * 10_000) / 10_000
        val wireProgression = BigDecimal.valueOf(rounded).stripTrailingZeros().toPlainString()
        return "reflowable:epub:position:$resourceKey:$wireProgression"
    }

    private suspend fun persist(
        locator: Locator,
        report: ReaderPositionReport = positionReport(locator),
    ) {
        saveMutex.withLock {
            if (restoreFailed) return@withLock
            if (report == lastPersistedReport) return@withLock
            val capturedAt = nowEpochMillis()
            val state = ReaderPositionLocalState(
                resourceId = source.resourceId,
                clientId = deviceIdentity.stableDeviceId(),
                capturedAtEpochMillis = capturedAt,
                position = report,
            )
            try {
                progressStore.save(state)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                LOGGER.log(
                    Level.WARNING,
                    "reader_progress_save_failed platform=android format=epub stage=local_persist",
                    error,
                )
                return@withLock
            }
            lastPersistedReport = report
            _restoreWarning.value = null
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
    }

    private suspend fun isUnreadablePage(location: ReflowReaderLocation): Boolean {
        val openedPublication = publication ?: return false
        val target = location.resourceKey?.substringBefore('#') ?: return false
        val link = openedPublication.readingOrder.firstOrNull {
            it.href.toString().substringBefore('#') == target ||
                openedPublication.url(it).toString().substringBefore('#') == target
        } ?: return false
        val resource = openedPublication.get(link) ?: return false
        val content = resource.read().getOrElse { return false }
        return content.containsSequence(UNREADABLE_PAGE_MARKER)
    }

    private suspend fun loadPositionSafely(): ReaderPositionLocalState? = try {
        progressStore.load(source.resourceId)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (error: Exception) {
        publishReaderRestoreWarning(_restoreWarning, "epub", "position_load", error)
        null
    }

    private fun positionLocator(position: ReaderPositionReport): Locator? = runCatching {
        Locator.fromJSON(org.json.JSONObject(position.locator.canonicalJson))
    }.getOrNull()

    private fun positionReport(locator: Locator): ReaderPositionReport {
        val href = locator.href.toString()
        val resourceProgression = locator.locations.progression ?: 0.0
        // The SDK Locator remains opaque.  The display projection is derived
        // from the publication position/navigation index and never copies the
        // Locator's own totalProgression value.
        val totalProgression = (
            publicationPositionIndex.totalProgression(locator)
                ?: resourceProgression
            ).coerceIn(0.0, 1.0)
        val chapter = tableOfContents.firstOrNull { entry ->
            val entryHref = (entry.location as? ReflowReaderLocation)?.resourceKey
            entryHref?.substringBefore('#') == href.substringBefore('#')
        }?.let { entry ->
            ReaderChapterPresentation(
                href = (entry.location as? ReflowReaderLocation)?.resourceKey,
                title = entry.title,
                index = entry.index,
            )
        }
        return ReaderPositionReport(
            locator = locatorMapper.opaqueLocator(locator),
            presentation = ReaderPositionPresentation(
                displayPercent = totalProgression * 100.0,
                totalProgression = totalProgression,
                currentHref = href,
                chapter = chapter,
                page = null,
                playback = null,
            ),
        )
    }

    private fun buildTableOfContents(openedPublication: Publication): List<ReaderTocEntry> {
        return openedPublication.tableOfContents
            .ifEmpty { openedPublication.readingOrder }
            .mapIndexedNotNull { index, link ->
                val locator = openedPublication.locatorFromLink(link) ?: return@mapIndexedNotNull null
                val href = locator.href.toString()
                ReaderTocEntry(
                    title = link.title?.takeIf(String::isNotBlank) ?: (index + 1).toString(),
                    location = locatorMapper.toDomain(locator),
                    id = href,
                    index = index,
                    target = ReaderNavigationTargetReflowable(href),
                )
            }
    }

    private companion object {
        val LOGGER: Logger = Logger.getLogger("MobileReader")
        const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L
        const val RESTORE_STABLE_OBSERVATIONS = 3
        const val SCROLL_SETTLE_SAMPLE_MILLIS = 16L
        const val SCROLL_SETTLE_SAMPLE_LIMIT = 38
        const val SCROLL_SETTLE_MINIMUM_SAMPLE_INDEX = 7
        const val RESOURCE_SETTLE_MINIMUM_SAMPLE_INDEX = 24
        const val SCROLL_SETTLE_REQUIRED_SAMPLES = 3
        val UNREADABLE_PAGE_MARKER =
            "data-shuku-resource-error=\"RESOURCE_UNREADABLE\"".encodeToByteArray()
    }

}

private fun ByteArray.containsSequence(needle: ByteArray): Boolean {
    if (needle.isEmpty() || size < needle.size) return false
    return (0..size - needle.size).any { offset ->
        needle.indices.all { index -> this[offset + index] == needle[index] }
    }
}

private fun continuousScrollViewportScript(
    direction: ReaderPageTurnDirection,
    animated: Boolean,
    writingMode: ReaderWritingMode,
    readingProgression: ReaderReadingProgression,
): String {
    val behavior = if (animated) "smooth" else "auto"
    val logicalDelta = if (direction == ReaderPageTurnDirection.Next) 1 else -1
    val coordinates = continuousScrollCoordinateDeclarations(writingMode, readingProgression)
    return """
        (() => {
          const root = document.scrollingElement || document.documentElement;
          if (!root) return 'unavailable';
$coordinates
          const current = Math.max(0, Math.min(maximum,
            normalize(horizontal ? root.scrollLeft : root.scrollTop)));
          const atBoundary = $logicalDelta < 0
            ? current <= ${ReaderNavigationPolicy.SCROLL_BOUNDARY_EPSILON_CSS_PIXELS}
            : maximum - current <= ${ReaderNavigationPolicy.SCROLL_BOUNDARY_EPSILON_CSS_PIXELS};
          if (atBoundary) return 'boundary';
          const viewport = horizontal ? window.innerWidth : window.innerHeight;
          const target = Math.max(0, Math.min(maximum,
            current + ($logicalDelta * viewport * ${ReaderNavigationPolicy.SCROLL_VIEWPORT_FRACTION})));
          if (horizontal) root.scrollTo({ left: denormalize(target), behavior: '$behavior' });
          else root.scrollTo({ top: target, behavior: '$behavior' });
          return 'moved';
        })()
    """.trimIndent()
}

private fun continuousScrollOffsetScript(
    writingMode: ReaderWritingMode,
    readingProgression: ReaderReadingProgression,
): String {
    val coordinates = continuousScrollCoordinateDeclarations(writingMode, readingProgression)
    return """
        (() => {
          const root = document.scrollingElement || document.documentElement;
          if (!root) return null;
$coordinates
          return Math.max(0, Math.min(maximum,
            normalize(horizontal ? root.scrollLeft : root.scrollTop)));
        })()
    """.trimIndent()
}

private fun continuousScrollResourceEdgeScript(
    direction: ReaderPageTurnDirection,
    writingMode: ReaderWritingMode,
    readingProgression: ReaderReadingProgression,
): String {
    val coordinates = continuousScrollCoordinateDeclarations(writingMode, readingProgression)
    val atEnd = direction == ReaderPageTurnDirection.Previous
    return """
        (() => {
          const root = document.scrollingElement || document.documentElement;
          if (!root) return false;
$coordinates
          const target = $atEnd ? maximum : 0;
          if (horizontal) root.scrollTo({ left: denormalize(target), behavior: 'auto' });
          else root.scrollTo({ top: target, behavior: 'auto' });
          const actual = normalize(horizontal ? root.scrollLeft : root.scrollTop);
          return Math.abs(actual - target) <= ${ReaderNavigationPolicy.SCROLL_BOUNDARY_EPSILON_CSS_PIXELS};
        })()
    """.trimIndent()
}

private fun continuousScrollCoordinateDeclarations(
    writingMode: ReaderWritingMode,
    readingProgression: ReaderReadingProgression,
): String {
    val horizontal = writingMode == ReaderWritingMode.Vertical
    val rtl = horizontal && readingProgression == ReaderReadingProgression.RightToLeft
    return """
        const horizontal = $horizontal;
        const rtl = $rtl;
        const maximum = Math.max(0, horizontal
          ? root.scrollWidth - window.innerWidth
          : root.scrollHeight - window.innerHeight);
        let rtlModel = 'reverse';
        if (rtl) {
          const outer = document.createElement('div');
          const inner = document.createElement('div');
          outer.dir = 'rtl';
          outer.style.cssText = 'position:absolute;left:-10000px;top:-10000px;width:4px;height:1px;overflow:scroll;visibility:hidden';
          inner.style.cssText = 'width:8px;height:1px';
          outer.appendChild(inner);
          document.body.appendChild(outer);
          if (outer.scrollLeft > 0) rtlModel = 'default';
          else { outer.scrollLeft = 1; rtlModel = outer.scrollLeft === 0 ? 'negative' : 'reverse'; }
          outer.remove();
        }
        const normalize = raw => !rtl ? raw
          : rtlModel === 'negative' ? -raw
          : rtlModel === 'reverse' ? raw
          : maximum - raw;
        const denormalize = value => !rtl ? value
          : rtlModel === 'negative' ? -value
          : rtlModel === 'reverse' ? value
          : maximum - value;
    """.trimIndent().prependIndent("          ")
}

private fun MobiPublicationErrorKind.toReaderErrorCode(): ReaderErrorCode = when (this) {
    MobiPublicationErrorKind.Unsupported -> ReaderErrorCode.UnsupportedFormat
    MobiPublicationErrorKind.Corrupt -> ReaderErrorCode.CorruptFile
    MobiPublicationErrorKind.LimitExceeded, MobiPublicationErrorKind.OutOfMemory -> ReaderErrorCode.OutOfMemoryRisk
    MobiPublicationErrorKind.Io -> ReaderErrorCode.ResourceMissing
}
