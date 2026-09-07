package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.features.reader.application.ReaderStartupPositionSource
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.ReaderSafetyImplementationException
import com.ermao.library.shared.modules.reader.readerSafetyDrmFailure
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveIntegrityFailure
import com.ermao.library.shared.modules.reader.readerErrorCodeForFailure
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderNavigationTarget
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetChapter
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetInvalid
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable
import com.ermao.library.shared.modules.reader.ReaderNavigationCompleted
import com.ermao.library.shared.modules.reader.ReaderNavigationRejected
import com.ermao.library.shared.modules.reader.ReaderNavigationResult
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderCommandCompleted
import com.ermao.library.shared.modules.reader.ReaderCommandRejected
import com.ermao.library.shared.modules.reader.ReaderCommandResult
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
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import java.io.FileNotFoundException
import java.math.BigDecimal
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
import kotlinx.coroutines.flow.collect
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
import org.readium.r2.shared.util.asset.ContainerAsset
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
    private val _currentNavigationEntryId = MutableStateFlow<String?>(null)
    override val currentNavigationEntryId: StateFlow<String?> = _currentNavigationEntryId.asStateFlow()
    private val _presentationProgress = MutableStateFlow<Double?>(null)
    override val presentationProgress: StateFlow<Double?> = _presentationProgress.asStateFlow()

    private val _preferences = MutableStateFlow(initialPreferences)
    override val preferences: StateFlow<ReaderPreferences> = _preferences.asStateFlow()


    private val _resumeNotice = MutableStateFlow<ReaderResumeNotice?>(null)
    override val resumeNotice: StateFlow<ReaderResumeNotice?> = _resumeNotice.asStateFlow()

    private val _resumeActionFailed = MutableStateFlow(false)
    override val resumeActionFailed: StateFlow<Boolean> = _resumeActionFailed.asStateFlow()

    private val _contentError = MutableStateFlow<ReaderError?>(null)
    override val contentError: StateFlow<ReaderError?> = _contentError.asStateFlow()

    private val saveMutex = Mutex()
    private val viewportNavigationMutex = Mutex()
    private val contentsMutex = Mutex()
    private var publication: Publication? = null
    private var protectedEpubAsset: ContainerAsset? = null
    private var mobiPublication: MobiReadiumPublication? = null
    private var navigator: EpubNavigatorFragment? = null
    private var publicationPositionIndex = ReadiumPublicationPositionIndex.Empty
    private var locationJob: Job? = null
    private var bookmarkScope: CoroutineScope? = null
    private var lastPersistedReport: ReaderPositionReport? = null
    private var lastObservedLocator: Locator? = null
    private var remoteTarget: ReaderProgressSnapshotV5? = null
    private var suppressNextPreferenceLocation = false
    private var currentPageUnreadable = false
    private var openingSafetyFailureSink: ReaderSafetyFailureSink? = null
    private var prepared = false
    private var contentsLoaded = false
    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    private val bookmarkCoordinator = AndroidReaderBookmarkCoordinator(
        bookmarkStore = bookmarkStore,
        bookmarkSyncPort = bookmarkSyncPort,
        bookmarkSyncTarget = bookmarkSyncTarget,
        currentPosition = {
            if (currentPageUnreadable) {
                null
            } else {
                lastObservedLocator?.let(::positionReport)
            }
        },
        bookmarkLabel = {
            val location = _currentLocation.value as? ReflowReaderLocation
            tableOfContents.firstOrNull { entry ->
                (entry.location as? ReflowReaderLocation)?.resourceKey == location?.resourceKey
            }?.title ?: source.displayTitle
        },
        bookmarkId = { position ->
            val location = _currentLocation.value as? ReflowReaderLocation
            val resourceKey = location?.resourceKey ?: position.presentation.currentHref
            resourceKey?.let {
                bookmarkId(
                    it,
                    location?.totalProgression ?: location?.progression
                        ?: position.presentation.totalProgression,
                )
            }.orEmpty()
        },
        navigateToPosition = ::navigateToBookmarkPosition,
        nowEpochMillis = nowEpochMillis,
    )

    override val bookmarks: StateFlow<List<ReaderBookmark>> = bookmarkCoordinator.bookmarks
    override val bookmarkSyncPending: StateFlow<Boolean> = bookmarkCoordinator.bookmarkSyncPending

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
            val archiveSafety = try {
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
            val safetyFailureSink = ReaderSafetyFailureSink()
            openingSafetyFailureSink = safetyFailureSink
            val resourceRoles = EpubContentSecurityPolicy.ArchiveResourceRoleResolver()
            val protectedAsset = try {
                EpubContentSecurityPolicy.protectAsset(
                    asset = asset,
                    onFailure = { error, role -> safetyFailureSink.record(error, role) },
                    archiveSafety = archiveSafety,
                    resourceRoles = resourceRoles,
                )
            } catch (error: ReaderSafetyException) {
                throw readerOpenFailure(error)
            } catch (error: ReaderSafetyImplementationException) {
                throw readerOpenFailure(error)
            }
            protectedEpubAsset = protectedAsset as? ContainerAsset
            safetyFailureSink.throwIfPresent()
            val openedPublication = readium.publicationOpener.open(
                asset = protectedAsset,
                allowUserInteraction = false,
                onCreatePublication = {
                    val parsedManifest = this.manifest
                    resourceRoles.markReadingOrder(
                        parsedManifest.readingOrder.mapNotNull { link -> link.url().path },
                    )
                },
            ).getOrElse { error ->
                safetyFailureSink.throwIfPresent()
                // A protected resource that was actually touched before the SDK
                // failed to build a Publication is required by that opening path,
                // even when it was not yet present in the manifest reading order.
                // Optional NCX/nav/cover/font failures leave the SDK open and never
                // reach this boundary.
                if (archiveSafety.quarantinedResources.keys.any { path ->
                        resourceRoles.wasObserved(path) &&
                            resourceRoles.roleFor(path) !=
                            com.ermao.library.shared.modules.reader.domain.ReaderSafetyResourceRole.OPTIONAL_RESOURCE
                    }) {
                    throw readerOpenFailure(
                        ReaderSafetyException(readerSafetyEpubArchiveIntegrityFailure())
                    )
                }
                throw ReaderOpenFailure(
                    ReaderError(ReaderErrorCode.ParseFailed),
                    diagnostic = ReadiumOpeningDiagnostic.PublicationOpening(error),
                )
            }
            safetyFailureSink.throwIfPresent()
            openedPublication
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
        openingSafetyFailureSink?.throwIfPresent()
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
        bookmarkCoordinator.load()

        val explicitLocator = initialTarget?.let { target ->
            val resolvedTarget = when (target) {
                is ReaderNavigationTargetChapter -> resolveChapterTarget(target, openedPublication)
                else -> target
            }
            locatorMapper.navigationLocator(resolvedTarget, openedPublication)
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
        }
        val localPosition = if (
            initialTarget == null &&
            startupPositionSource in setOf(
                ReaderStartupPositionSource.LocalPending,
                ReaderStartupPositionSource.LocalOnly,
                ReaderStartupPositionSource.LocalFallback,
            )
        ) {
            loadPositionSafely()
        } else {
            null
        }
        val initialLocator = when {
            explicitLocator != null -> explicitLocator
            localPosition != null -> positionLocator(localPosition.position)
            startupPositionSource == ReaderStartupPositionSource.ServerSnapshot && remoteSnapshot != null ->
                positionLocator(remoteSnapshot.position)
            else -> null
        }
        if (localPosition != null && initialLocator != null) {
            val restoredLocalLocator = initialLocator
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
        bookmarkCoordinator.bind(scope)
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
            checkNotNull(navigator).currentLocator.collect { locator ->
                lastObservedLocator = locator
                updateCurrentNavigationEntry(locator)
                val mapped = locatorMapper.toDomain(locator)
                val eventReport = positionReport(locator)
                _currentLocation.value = mapped
                _presentationProgress.value = eventReport.presentation.totalProgression
                if (suppressNextPreferenceLocation) {
                    suppressNextPreferenceLocation = false
                    return@collect
                }
                if (_resumeNotice.value != null) {
                    hideResumeNotice()
                }
                currentPageUnreadable = isUnreadablePage(mapped)
                if (!currentPageUnreadable) persist(locator, eventReport)
            }
        }
    }

    override fun goPrevious(): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
        if (isContinuousScroll(_preferences.value)) {
            return advanceContinuousScroll(direction = ReaderPageTurnDirection.Previous)
        }
        return navigator?.goBackward(animated = navigationAnimationsEnabled()) ?: false
    }

    override fun goNext(): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
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
        val openedPublication = publication ?: return false
        val target = locatorMapper.resourceLocator(location, openedPublication)
            ?: return false
        requestedNavigationTarget = com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable(target.href.toString())
        return navigator?.go(target, animated = navigationAnimationsEnabled()) ?: false
    }

    override suspend fun navigateTo(entry: ReaderTocEntry): ReaderNavigationResult {
        val navigationTarget = entry.target
        val target = navigationTarget as? ReaderNavigationTargetReflowable
            ?: return if (navigationTarget is ReaderNavigationTargetInvalid) {
                ReaderNavigationRejected(navigationTarget.reasonCode)
            } else {
                ReaderNavigationRejected("READER_NAVIGATION_REJECTED")
            }
        val openedPublication = publication ?: return ReaderNavigationRejected("READER_NAVIGATION_REJECTED")
        val activeNavigator = navigator ?: return ReaderNavigationRejected("READER_NAVIGATION_REJECTED")
        val targetHref = target.href
        val targetLocator = locatorMapper.navigationLocator(target, openedPublication)
            ?: return ReaderNavigationRejected("READER_NAVIGATION_REJECTED")

        if (isLocatorVisible(activeNavigator, targetLocator)) {
            return ReaderNavigationCompleted(moved = false)
        }
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
        requestedNavigationTarget = ReaderNavigationTargetReflowable(targetHref)
        val changesResource = activeNavigator.currentLocator.value.href != targetLocator.href
        if (!activeNavigator.go(targetLocator, animated = navigationAnimationsEnabled())) {
            return ReaderNavigationRejected("READER_NAVIGATION_REJECTED")
        }
        val verified = withTimeoutOrNull(com.ermao.library.features.reader.application.NAVIGATION_VERIFICATION_TIMEOUT_MILLIS) {
            if (changesResource) {
                // Readium emits this only after the resource is loaded and its transition
                // has settled. Its initial page selection may place a backward jump at
                // the resource end; apply the authored locator after that placement.
                activeNavigator.currentLocator.first { it.href == targetLocator.href }
                if (!activeNavigator.go(targetLocator, animated = false)) return@withTimeoutOrNull false
            }
            // The progression stream need not echo the requested HTML anchor.
            while (!isLocatorVisible(activeNavigator, targetLocator)) delay(50)
            true
        } == true
        return if (verified) ReaderNavigationCompleted(moved = true)
        else ReaderNavigationRejected("READER_NAVIGATION_VERIFICATION_FAILED")
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        suppressNextPreferenceLocation = false
        dismissResumeNotice()
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
        lastObservedLocator?.let(::updateCurrentNavigationEntry)
        loaded
    }

    private fun updateCurrentNavigationEntry(locator: Locator) {
        _currentNavigationEntryId.value = currentReadiumChapter(tableOfContents, locator)?.id
    }

    override fun dismissResumeNotice() {
        progressCoordinator?.dismissRemotePositionNotice()
        hideResumeNotice()
    }

    private fun hideResumeNotice() {
        remoteTarget = null
        _resumeNotice.value = null
        _resumeActionFailed.value = false
    }

    override fun returnToResumeNotice(): Boolean {
        val snapshot = remoteTarget ?: return false
        val locator = positionLocator(snapshot.position) ?: run {
            _resumeActionFailed.value = true
            return false
        }
        val moved = runCatching {
            navigator?.go(locator, animated = navigationAnimationsEnabled()) == true
        }.getOrDefault(false)
        if (!moved) {
            _resumeActionFailed.value = true
            return false
        }
        bookmarkScope?.launch {
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
        lastPersistedReport = snapshot.position
        hideResumeNotice()
        return true
    }

    override suspend fun applyPreferences(updated: ReaderPreferences): ReaderCommandResult =
        viewportNavigationMutex.withLock {
            if (_preferences.value.epub.fontSize == updated.epub.fontSize) {
                return@withLock super.applyPreferences(updated)
            }
            if (!canApplyPreferences(updated)) {
                return@withLock ReaderCommandRejected("READER_CONTROL_UNAVAILABLE")
            }
            val active = navigator
                ?: return@withLock ReaderCommandRejected("READER_PREFERENCES_ENGINE_FAILED")
            try {
                // Readium 3.3 changes font CSS without retaining the visible block. Capture
                // its semantic locator before reflow; percentage is not a restore target.
                val visible = active.firstVisibleElementLocator()
                    ?: return@withLock ReaderCommandRejected("READER_PREFERENCES_ENGINE_FAILED")
                if (visible.locations["cssSelector"] !is String) {
                    return@withLock ReaderCommandRejected("READER_PREFERENCES_ENGINE_FAILED")
                }
                val result = super.applyPreferences(updated)
                if (result != ReaderCommandCompleted) return@withLock result
                val fontScale = preferencesMapper.toReadium(updated, capabilities.supportsWritingMode).fontSize
                    ?: return@withLock ReaderCommandRejected("READER_PREFERENCES_ENGINE_FAILED")
                val restored = withTimeoutOrNull(com.ermao.library.features.reader.application.NAVIGATION_VERIFICATION_TIMEOUT_MILLIS) {
                    while (active.evaluateJavascript("""
                        Math.abs(parseFloat(getComputedStyle(document.documentElement)
                          .getPropertyValue('--USER__fontSize')) - ${fontScale * 100.0}) < 0.01
                    """.trimIndent()) != "true") delay(50)
                    if (!active.go(visible, animated = false)) return@withTimeoutOrNull false
                    while (!isLocatorVisible(active, visible)) delay(50)
                    true
                } == true
                if (restored) ReaderCommandCompleted
                else ReaderCommandRejected("READER_PREFERENCES_ENGINE_FAILED")
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: RuntimeException) {
                ReaderCommandRejected("READER_PREFERENCES_ENGINE_FAILED", error)
            }
        }

    private suspend fun isLocatorVisible(active: EpubNavigatorFragment, locator: Locator): Boolean {
        if (active.currentLocator.value.href != locator.href) return false
        val selector = locator.locations["cssSelector"] as? String
        // TOC locators come from locatorFromLink, which preserves the authored URL fragment.
        val htmlId = locator.locations.fragments.singleOrNull()?.removePrefix("#")
        val element = when {
            selector != null -> "document.querySelector(${org.json.JSONObject.quote(selector)})"
            htmlId != null -> "document.getElementById(${org.json.JSONObject.quote(htmlId)})"
            else -> return locator.locations.fragments.isEmpty()
        }
        return active.evaluateJavascript("""
            (() => {
              const element = $element;
              return element && [...element.getClientRects()].some(rect =>
                rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
                rect.left < window.innerWidth && rect.top < window.innerHeight);
            })()
        """.trimIndent()) == "true"
    }

    override fun updatePreferences(updated: ReaderPreferences) {
        val active = checkNotNull(navigator) { "READER_NOT_READY" }
        val previous = _preferences.value
        val supported = updated
        if (previous == supported) return
        // Persistence precedes the single SDK submission; applyPreferences retains its anchor.
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

    override fun toggleCurrentBookmark(): ReaderBookmarkChange? =
        bookmarkCoordinator.toggleCurrentBookmark()

    override fun undoBookmarkChange(change: ReaderBookmarkChange): Boolean =
        bookmarkCoordinator.undoBookmarkChange(change)

    override fun removeBookmark(id: String) = bookmarkCoordinator.removeBookmark(id)

    override fun undoBookmarkRemoval(id: String): Boolean =
        bookmarkCoordinator.undoBookmarkRemoval(id)

    override fun goToBookmark(id: String): Boolean = bookmarkCoordinator.goToBookmark(id)

    private fun navigateToBookmarkPosition(position: ReaderPositionReport): Boolean {
        val locator = runCatching {
            Locator.fromJSON(org.json.JSONObject(position.locator.canonicalJson))
        }.getOrNull() ?: return false
        val opened = publication ?: return false
        val locatorIndex = epubReadingOrderIndex(opened, locator.href.toString()) ?: return false
        val presentedHref = position.presentation.currentHref
        if (presentedHref != null && epubReadingOrderIndex(opened, presentedHref) != locatorIndex) {
            return false
        }
        requestedNavigationTarget = ReaderNavigationTargetReflowable(locator.href.toString())
        return navigator?.go(locator, animated = navigationAnimationsEnabled()) ?: false
    }

    private fun epubReadingOrderIndex(publication: Publication, href: String): Int? {
        val normalized = href.substringBefore('#')
        return publication.readingOrder.indexOfFirst { link ->
            link.href.toString().substringBefore('#') == normalized ||
                publication.url(link).toString().substringBefore('#') == normalized
        }.takeIf { it >= 0 }
    }

    override suspend fun flush() {
        if (suppressNextPreferenceLocation) return
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
        bookmarkCoordinator.release()
        bookmarkScope = null
        navigator = null
        publication?.close()
        publication = null
        _presentationProgress.value = null
        mobiPublication?.close()
        mobiPublication = null
        publicationPositionIndex = ReadiumPublicationPositionIndex.Empty
        remoteTarget = null
        openingSafetyFailureSink?.clear()
        openingSafetyFailureSink = null
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
        openingSafetyFailureSink?.throwIfPresent()
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
    } catch (_: Exception) {
        null
    }

    private fun resumeNotice(snapshot: ReaderProgressSnapshotV5): ReaderResumeNotice = ReaderResumeNotice(
        capturedAtEpochMillis = snapshot.capturedAtEpochMillis,
        percent = snapshot.position.presentation.displayPercent,
        chapterLabel = snapshot.position.presentation.chapter?.title,
        pageNumber = snapshot.position.presentation.page?.number,
    )

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
        val chapter = currentReadiumChapter(tableOfContents, locator)?.let { entry ->
            ReaderChapterPresentation(
                href = (entry.target as? ReaderNavigationTargetReflowable)?.href,
                title = entry.title,
                index = entry.index,
                navigationKey = entry.id,
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

    private suspend fun buildTableOfContents(openedPublication: Publication): List<ReaderTocEntry> {
        // For an EPUB, read nav/NCX from the same protected container that was
        // handed to PublicationOpener. Readium's processed TOC is not a stable
        // source for chapter-core identity because it may promote or rewrite
        // structural nodes. Synthetic TXT/FB2/MOBI publications have no asset
        // here and keep their factory-owned authored links.
        val links = if (protectedEpubAsset != null) {
            EpubChapterProjection.project(requireNotNull(protectedEpubAsset))
        } else {
            openedPublication.tableOfContents
        }
        return mapReadiumTocEntries(links) { link ->
            openedPublication.locatorFromLink(link)?.let(locatorMapper::toDomain)
        }
    }

    private suspend fun resolveChapterTarget(
        target: ReaderNavigationTargetChapter,
        openedPublication: Publication,
    ): ReaderNavigationTargetReflowable {
        val matches = com.ermao.library.features.reader.application.flattenTableOfContents(
            buildTableOfContents(openedPublication),
        ).map { it.entry }
            .filter { it.id == target.navigationKey }
            .mapNotNull { it.target as? ReaderNavigationTargetReflowable }
        val match = matches.singleOrNull()
            ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.LocationRestoreFailed))
        return match
    }

    private companion object {
        val LOGGER: Logger = Logger.getLogger("MobileReader")
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

/** Matches the Web Readium chapter projection: a same-resource TOC entry is usable
 * only when its authored fragment is uniquely evidenced by the current locator. */
private fun currentReadiumChapter(entries: List<ReaderTocEntry>, locator: Locator): ReaderTocEntry? {
    val flattened = com.ermao.library.features.reader.application.flattenTableOfContents(entries)
    val candidates = flattened.mapNotNull { node ->
        val target = node.entry.target as? ReaderNavigationTargetReflowable ?: return@mapNotNull null
        com.ermao.library.shared.modules.reader.ReaderNavigationEntry(node.entry.id, target.href, node.depth)
    }
    val key = com.ermao.library.shared.modules.reader.resolveCurrentReaderNavigationEntryId(
        entries = candidates,
        currentHref = locator.href.toString(),
        fragments = locator.locations.fragments.toSet(),
        cssSelector = locator.locations["cssSelector"] as? String,
    ) ?: return null
    return flattened.singleOrNull { it.entry.id == key }?.entry
}

/** Keeps the chapter-core navigation tree intact while projecting it into the
 * renderer-neutral model. Structural entries remain in place with an Invalid
 * target; their children are never promoted or re-keyed. */
internal fun mapReadiumTocEntries(
    links: List<Link>,
    resolveLocation: (Link) -> ReflowReaderLocation?,
): List<ReaderTocEntry> {
    val usedIds = linkedSetOf<String>()

    fun map(items: List<Link>): List<ReaderTocEntry> = buildList {
        items.forEach { link ->
            // Keep the authored Link href, including its fragment. Readium's
            // Locator projection may carry the fragment separately in
            // locations.fragments, so deriving the target from the projected
            // resource key can silently turn an anchored TOC entry into a
            // resource-only entry.
            val href = link.href.toString().takeIf { it.substringBefore('#').isNotBlank() }
            val rawNavigationKey = link.properties.otherProperties["shuku:navigationKey"]
                ?.toString()
                ?.takeIf(String::isNotBlank)
            val id = requireNotNull(rawNavigationKey) {
                "Chapter-core TOC link is missing shuku:navigationKey"
            }
            require(usedIds.add(id)) { "Duplicate chapter-core TOC key: $id" }
            require(id.startsWith("chapter-")) { "Chapter-core TOC key is invalid: $id" }
            val location = href?.let { resolveLocation(link) }
            val entryIndex = rawNavigationKey
                .removePrefix("chapter-")
                .toIntOrNull()
                ?: error("Chapter-core TOC key has no numeric index: $rawNavigationKey")
            val children = map(link.children)
            val title = link.title?.takeIf(String::isNotBlank)
                ?: error("Chapter-core TOC link has a blank title: $id")
            add(
                ReaderTocEntry(
                    title = title,
                    location = location ?: ReflowReaderLocation(progression = 0.0),
                    children = children,
                    id = id,
                    index = entryIndex,
                    target = if (href != null) {
                        ReaderNavigationTargetReflowable(href)
                    } else {
                        ReaderNavigationTargetInvalid()
                    },
                ),
            )
        }
    }

    return map(links)
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
