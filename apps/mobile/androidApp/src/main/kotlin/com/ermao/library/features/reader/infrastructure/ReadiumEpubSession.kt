package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.application.ReaderResumeNotice
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderBookmarkLocation
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.createReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.domain.mergeReaderBookmarks
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderNavigationUnit
import com.ermao.library.shared.modules.reader.ReaderNavigationTarget
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetInvalid
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderResumeTarget
import com.ermao.library.shared.modules.reader.ReaderResumeSource
import com.ermao.library.shared.modules.reader.ReadiumLocatorEnvelope
import com.ermao.library.shared.modules.reader.ReflowablePublicationLocation
import com.ermao.library.shared.modules.reader.ExactBlockMatch
import com.ermao.library.shared.modules.reader.ReaderRestoreCandidate
import com.ermao.library.shared.modules.reader.ReaderRestoreExactEngineLocation
import com.ermao.library.shared.modules.reader.ReaderRestoreExactLocalLocation
import com.ermao.library.shared.modules.reader.ReaderRestorePdfPage
import com.ermao.library.shared.modules.reader.ReaderRestoreComicPage
import com.ermao.library.shared.modules.reader.ReaderRestoreAudioPosition
import com.ermao.library.shared.modules.reader.ReaderRestorePosition
import com.ermao.library.shared.modules.reader.ReaderRestorePublicEngineLocator
import com.ermao.library.shared.modules.reader.ReaderRestoreQuotedText
import com.ermao.library.shared.modules.reader.ReaderRestoreResourceProgression
import com.ermao.library.shared.modules.reader.ReaderRestoreTotalProgression
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderTocEntry
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.planReaderProgressRestore
import com.ermao.library.shared.modules.reader.decideReaderResume
import java.io.FileNotFoundException
import java.math.BigDecimal
import java.time.Instant
import java.util.logging.Level
import java.util.logging.Logger
import kotlin.math.abs
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

private fun AndroidReaderBookmarkRecord.shared(): ReaderBookmark = ReaderBookmark(
    id = id,
    location = ReaderBookmarkLocation(resourceKey, progression),
    label = label,
    percent = percent,
    createdAt = createdAt,
)

private fun ReaderBookmark.record(): AndroidReaderBookmarkRecord = AndroidReaderBookmarkRecord(
    id = id,
    resourceKey = location.resourceKey,
    progression = location.progression,
    totalProgression = null,
    position = null,
    exactEnvelope = null,
    label = label,
    percent = percent,
    createdAt = createdAt,
)

@OptIn(ExperimentalReadiumApi::class)
internal class ReadiumEpubSession(
    private val source: LocalReaderSource,
    private val canonicalUnits: List<ReaderNavigationUnit> = emptyList(),
    private val publicationStore: AndroidReaderPublicationStore,
    private val progressStore: ReaderProgressStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val locatorMapper: ReadiumLocatorMapper,
    private val preferencesMapper: ReadiumPreferencesMapper,
    private val remoteSnapshot: ReaderProgressSnapshotV4? = null,
    private val progressCoordinator: com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val persistPreferences: (ReaderPreferences) -> Unit = {},
    private val bookmarkStore: AndroidReaderBookmarkStore? = null,
    private val bookmarkSyncPort: ReaderBookmarkSyncPort? = null,
    private val bookmarkSyncTarget: ReaderBookmarkSyncTarget? = null,
    private val externalLinkHandler: (String) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
    private val presentationNamespaceKey: String? = null,
    private val publishProgressUpdate: (ReaderProgressPresentationUpdate) -> Unit = {},
) : AndroidReaderNavigatorSession {
    override val morphology = ReaderMorphology.Reflowable
    override val capabilities: ReaderCapabilities = ReaderCapabilities.epub(
        supportsVolumeKeys = true,
        supportsCustomFonts = false,
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

    private val _bookmarks = MutableStateFlow<List<ReaderBookmark>>(emptyList())
    override val bookmarks: StateFlow<List<ReaderBookmark>> = _bookmarks.asStateFlow()

    private val _bookmarkSyncPending = MutableStateFlow(false)
    override val bookmarkSyncPending: StateFlow<Boolean> = _bookmarkSyncPending.asStateFlow()

    private val saveMutex = Mutex()
    private val bookmarkSyncMutex = Mutex()
    private var bookmarkRecords: List<AndroidReaderBookmarkRecord> = emptyList()
    private var publication: Publication? = null
    private var mobiPublication: MobiReadiumPublication? = null
    private var navigator: EpubNavigatorFragment? = null
    private var publicationPositions: List<Locator> = emptyList()
    private var locationJob: Job? = null
    private var bookmarkScope: CoroutineScope? = null
    private var lastPersistedLocation: ReaderLocation? = null
    private var expectedRestoreEnvelope: ReadiumLocatorEnvelope? = null
    private var restoreObservationCount = 0
    private var awaitingInitialObservation = true
    private var resumeTarget: ResumeTarget? = null
    private var returningToResumeTarget = false
    private var suppressNextPreferenceLocation = false
    private var currentPageUnreadable = false
    private var prepared = false

    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    override suspend fun prepare(classLoader: ClassLoader): EpubNavigatorFragment {
        check(!prepared) { "Reader session is already prepared" }
        prepared = true
        val file = try {
            publicationStore.resolve(source)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        } catch (error: FileNotFoundException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing), cause = error)
        }
        val openedPublication = if (source.format == ReaderFormat.Mobi) {
            val opened = try {
                MobiReadiumPublicationFactory().open(file, EpubContentSecurityPolicy::apply)
            } catch (error: MobiPublicationOpenException) {
                throw ReaderOpenFailure(ReaderError(error.kind.toReaderErrorCode()), cause = error)
            }
            mobiPublication = opened
            opened.publication
        } else if (source.format == ReaderFormat.Text) {
            try {
                TxtReadiumPublicationFactory().open(file, source.displayTitle)
            } catch (error: IllegalArgumentException) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile), cause = error)
            }
        } else {
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
        if (openedPublication.isRestricted) {
            openedPublication.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.DrmProtected))
        }
        if (!openedPublication.conformsTo(Publication.Profile.EPUB)) {
            openedPublication.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
        }
        publication = openedPublication
        progressCoordinator?.beginSession(remoteSnapshot)
        publicationPositions = openedPublication.positions()
        runCatching { bookmarkStore?.load() }.getOrNull()?.let { state ->
            bookmarkRecords = state.bookmarks
            _bookmarks.value = state.bookmarks.map(AndroidReaderBookmarkRecord::shared)
            _bookmarkSyncPending.value = state.pending != null
        }

        val localProgress = loadProgressSafely()
        val resumeDecision = decideReaderResume(localProgress, remoteSnapshot, source)
        val selected = resumeDecision.selected
        val restorePlan = planReaderProgressRestore(
            selected?.localProgress,
            selected?.remoteSnapshot,
            source,
        )
        expectedRestoreEnvelope = restorePlan.localProgress
            ?.location
            ?.let { it as? ReflowReaderLocation }
            ?.let { ReadiumLocatorEnvelope.from(it) }
            ?: (restorePlan.remoteSnapshot?.locator as? ReflowablePublicationLocation)?.readiumEnvelope
        val initialLocator = restorePlan.candidates.firstNotNullOfOrNull { candidate ->
            restoreCandidate(candidate, openedPublication)
        }
        resumeDecision.alternative?.let { alternative ->
            resumeTarget = alternative.toResumeTarget(openedPublication)
            _resumeNotice.value = resumeTarget?.notice
        }
        if ((restorePlan.localProgress != null || restorePlan.remoteSnapshot != null) && initialLocator == null) {
            _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        } else if (restorePlan.usesLocalExact) {
            _currentLocation.value = restorePlan.localProgress?.location
            lastPersistedLocation = restorePlan.localProgress?.location
        }

        val canonicalToc = canonicalUnits.mapNotNull { unit ->
            val canonicalLocator = unit.href
                ?.let { href -> Url(href) }
                ?.let { href -> openedPublication.locatorFromLink(Link(href = href, title = unit.title)) }
                ?: return@mapNotNull null
            ReaderTocEntry(
                title = unit.title,
                location = locatorMapper.toDomain(canonicalLocator),
                id = unit.id,
                index = unit.index,
                target = ReaderNavigationTargetReflowable(canonicalLocator.href.toString()),
            )
        }
        val canonicalHrefs = canonicalToc.mapNotNull { (it.location as? ReflowReaderLocation)?.resourceKey }
            .map { it.substringBefore('#') }
            .toSet()
        val publicationToc = openedPublication.tableOfContents
            .ifEmpty { openedPublication.readingOrder }
            .mapIndexedNotNull { index, link ->
                val locator = openedPublication.locatorFromLink(link) ?: return@mapIndexedNotNull null
                val href = locator.href.toString()
                if (href.substringBefore('#') in canonicalHrefs) return@mapIndexedNotNull null
                ReaderTocEntry(
                    title = link.title?.takeIf(String::isNotBlank) ?: (index + 1).toString(),
                    location = locatorMapper.toDomain(locator),
                    id = href,
                    index = canonicalToc.size + index,
                    target = ReaderNavigationTargetReflowable(href),
                )
            }
        tableOfContents = canonicalToc + publicationToc
        val fragmentFactory = EpubNavigatorFactory(openedPublication).createFragmentFactory(
            initialLocator = initialLocator,
            initialPreferences = preferencesMapper.toReadium(_preferences.value),
            listener = object : EpubNavigatorFragment.Listener {
                override fun onResourceLoadFailed(href: Url, error: ReadError) {
                    LOGGER.log(
                        Level.SEVERE,
                        "reader_epub_resource_load_failed href=$href error=${error.toDebugDescription()}",
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
        return created
    }


    override fun bind(scope: CoroutineScope) {
        checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        bookmarkScope = scope
        progressCoordinator?.let { coordinator ->
            scope.launch {
                coordinator.remoteProgressNotices.collectLatest { notice ->
                    val snapshot = notice?.snapshot
                    if (snapshot == null) {
                        if (!returningToResumeTarget) hideResumeNotice()
                    } else {
                        val target = ReaderResumeTarget(
                            source = ReaderResumeSource.Server,
                            capturedAtEpochMillis = snapshot.effectiveCapturedAtEpochMillis,
                            displayPercent = snapshot.displayPercent,
                            remoteSnapshot = snapshot,
                        ).toResumeTarget(checkNotNull(publication))
                        resumeTarget = target
                        _resumeNotice.value = target?.notice
                    }
                }
            }
        }
        locationJob = scope.launch {
            checkNotNull(navigator).currentLocator.collectLatest { locator ->
                val mapped = locatorMapper.toDomain(locator)
                _currentLocation.value = mapped
                delay(LOCAL_SAVE_DEBOUNCE_MILLIS)
                val exactLocation = captureFirstVisibleExactLocation() ?: mapped
                _currentLocation.value = exactLocation
                currentPageUnreadable = isUnreadablePage(exactLocation)
                expectedRestoreEnvelope?.let { expected ->
                    val explicitReturn = returningToResumeTarget
                    val recaptured = exactLocation.engineLocator
                        ?.let { locatorMapper.publicEngineLocator(it) }
                    val match = recaptured?.let {
                        locatorMapper.compareExactBlock(expected, it)
                    } ?: ExactBlockMatch.AnchorMismatch
                    restoreObservationCount += 1
                    when (match) {
                        ExactBlockMatch.Exact -> {
                            expectedRestoreEnvelope = null
                            restoreObservationCount = 0
                            awaitingInitialObservation = false
                            if (returningToResumeTarget) {
                                returningToResumeTarget = false
                                _resumeNotice.value = null
                                val verifiedTarget = resumeTarget
                                resumeTarget = null
                                val coordinator = progressCoordinator
                                val snapshot = verifiedTarget?.snapshot
                                if (coordinator != null && snapshot != null) {
                                    val verified = ReaderProgress(
                                        source.sourceId,
                                        exactLocation,
                                        nowEpochMillis(),
                                        deviceIdentity.stableDeviceId(),
                                    )
                                    coordinator.acceptVerifiedRemoteProgress(verified, snapshot)
                                    lastPersistedLocation = exactLocation
                                    return@collectLatest
                                }
                            }
                            if (!explicitReturn) return@collectLatest
                        }
                        ExactBlockMatch.ResourceMismatch, ExactBlockMatch.AnchorMismatch -> {
                            if (restoreObservationCount < RESTORE_STABLE_OBSERVATIONS) return@collectLatest
                            expectedRestoreEnvelope = null
                            awaitingInitialObservation = false
                            if (returningToResumeTarget) {
                                returningToResumeTarget = false
                                _resumeActionFailed.value = true
                            } else {
                                _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
                            }
                            return@collectLatest
                        }
                    }
                }
                if (awaitingInitialObservation) {
                    awaitingInitialObservation = false
                    return@collectLatest
                }
                if (suppressNextPreferenceLocation) {
                    suppressNextPreferenceLocation = false
                    return@collectLatest
                }
                if (_resumeNotice.value != null && !returningToResumeTarget) {
                    hideResumeNotice()
                }
                if (!currentPageUnreadable) persist(exactLocation)
            }
        }
        if (bookmarkStore != null && bookmarkSyncPort != null && bookmarkSyncTarget != null) {
            scope.launch { refreshBookmarksFromServer() }
            scope.launch { flushBookmarkOutbox() }
        }
    }

    override fun goPrevious(): Boolean {
        dismissResumeNotice()
        return navigator?.goBackward(animated = true) ?: false
    }

    override fun goNext(): Boolean {
        dismissResumeNotice()
        return navigator?.goForward(animated = true) ?: false
    }

    override fun goTo(location: ReaderLocation): Boolean {
        dismissResumeNotice()
        val openedPublication = publication ?: return false
        val target = locatorMapper.exactEngineLocator(location)
            ?.takeIf { locator -> openedPublication.contains(locator) }
            ?: locatorMapper.resourceProgressionLocator(location, openedPublication)
            ?: return false
        return navigator?.go(target, animated = true) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        dismissResumeNotice()
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val target = publicationPositions
            .filter { it.locations.totalProgression != null }
            .minByOrNull { locator ->
                abs(checkNotNull(locator.locations.totalProgression) - totalProgression)
            }
            ?: return false
        return navigator?.go(target, animated = true) ?: false
    }

    override fun dismissResumeNotice() {
        if (returningToResumeTarget) return
        progressCoordinator?.dismissRemoteProgressNotice()
        hideResumeNotice()
    }

    private fun hideResumeNotice() {
        _resumeNotice.value = null
        _resumeActionFailed.value = false
        resumeTarget = null
    }

    override fun returnToResumeNotice(): Boolean {
        val target = resumeTarget ?: return false
        _resumeActionFailed.value = false
        returningToResumeTarget = true
        expectedRestoreEnvelope = target.envelope
        restoreObservationCount = 0
        val moved = navigator?.go(target.locator, animated = true) ?: false
        if (!moved) {
            returningToResumeTarget = false
            expectedRestoreEnvelope = null
            _resumeActionFailed.value = true
        }
        return moved
    }

    override fun updatePreferences(updated: ReaderPreferences) {
        if (_preferences.value == updated) return
        suppressNextPreferenceLocation = true
        _preferences.value = updated
        navigator?.submitPreferences(preferencesMapper.toReadium(updated))
        persistPreferences(updated)
    }

    override fun toggleCurrentBookmark() {
        if (currentPageUnreadable) return
        val location = _currentLocation.value as? ReflowReaderLocation ?: return
        val resourceKey = location.resourceKey ?: return
        val id = bookmarkId(resourceKey, location.totalProgression ?: location.progression ?: 0.0)
        val next = if (bookmarkRecords.any { it.id == id }) {
            bookmarkRecords.filterNot { it.id == id }
        } else {
            bookmarkRecords + AndroidReaderBookmarkRecord(
                id = id,
                resourceKey = resourceKey,
                progression = location.progression,
                totalProgression = location.totalProgression,
                position = location.position,
                exactEnvelope = ReadiumLocatorEnvelope.from(location)?.canonicalJson(),
                label = tableOfContents.firstOrNull {
                    (it.location as? ReflowReaderLocation)?.resourceKey == location.resourceKey
                }?.title ?: source.displayTitle,
                percent = ((location.totalProgression ?: location.progression ?: 0.0) * 100).coerceIn(0.0, 100.0),
                createdAt = Instant.ofEpochMilli(nowEpochMillis()).toString(),
            )
        }
        commitBookmarkMutation(next)
    }

    override fun removeBookmark(id: String) {
        if (bookmarkRecords.none { it.id == id }) return
        commitBookmarkMutation(bookmarkRecords.filterNot { it.id == id })
    }

    override fun goToBookmark(id: String): Boolean {
        val record = bookmarkRecords.firstOrNull { it.id == id } ?: return false
        val exact = record.exactEnvelope?.let { value ->
            runCatching { ReadiumLocatorEnvelope.parse(value) }.getOrNull()
        }
        val location = ReflowReaderLocation(
            resourceKey = record.resourceKey,
            progression = record.progression,
            totalProgression = record.totalProgression,
            position = record.position,
            engineLocator = exact?.asEngineLocator(),
        )
        return goTo(location)
    }

    override suspend fun flush() {
        val location = captureFirstVisibleExactLocation() ?: _currentLocation.value
        if (location != null) {
            _currentLocation.value = location
            persist(location)
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
        bookmarkScope = null
        navigator = null
        publication?.close()
        publication = null
        mobiPublication?.close()
        mobiPublication = null
        publicationPositions = emptyList()
    }

    private fun commitBookmarkMutation(next: List<AndroidReaderBookmarkRecord>) {
        val store = bookmarkStore ?: return
        val ordered = next.sortedWith(compareBy({ it.percent }, { it.createdAt }, { it.id }))
        store.save(AndroidReaderBookmarkState(bookmarks = ordered, pending = ordered))
        bookmarkRecords = ordered
        _bookmarks.value = ordered.map(AndroidReaderBookmarkRecord::shared)
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
            local = state.bookmarks.map(AndroidReaderBookmarkRecord::shared),
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
            val response = port.replace(target, pending.map(AndroidReaderBookmarkRecord::shared))
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

    private suspend fun persist(location: ReaderLocation) {
        saveMutex.withLock {
            if (location == lastPersistedLocation) return@withLock
            val exactProgress = runCatching {
                ReaderProgress(
                    sourceId = source.sourceId,
                    location = location,
                    updatedAtEpochMillis = nowEpochMillis(),
                    deviceId = deviceIdentity.stableDeviceId(),
                )
            }.getOrNull() ?: return@withLock
            try {
                progressStore.save(exactProgress)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                return@withLock
            }
            lastPersistedLocation = location
            publishPresentationUpdate(exactProgress)
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

    private suspend fun captureFirstVisibleExactLocation(): ReflowReaderLocation? {
        val currentNavigator = navigator ?: return null
        val locator = try {
            currentNavigator.firstVisibleElementLocator()
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: RuntimeException) {
            return null
        } ?: return null
        val fallback = _currentLocation.value as? ReflowReaderLocation
        val enrichedLocator = locator.copyWithLocations(
            progression = locator.locations.progression ?: fallback?.progression,
            position = locator.locations.position ?: fallback?.position,
            totalProgression = locator.locations.totalProgression ?: fallback?.totalProgression,
        )
        val location = locatorMapper.toDomain(enrichedLocator)
        return location.takeIf { ReadiumLocatorEnvelope.from(it) != null }
    }

    private fun publishPresentationUpdate(progress: ReaderProgress) {
        val reflow = progress.location as? ReflowReaderLocation ?: return
        val namespaceKey = presentationNamespaceKey ?: return
        val workId = source.workId ?: return
        val volumeId = source.volumeId ?: source.sourceId
        val href = reflow.resourceKey ?: return
        val percent = ((reflow.totalProgression ?: reflow.progression ?: 0.0) * 100).coerceIn(0.0, 100.0)
        val chapterTitle = tableOfContents.firstOrNull {
            (it.location as? ReflowReaderLocation)?.resourceKey == href
        }?.title
        publishProgressUpdate(
            createReaderProgressPresentationUpdate(
                namespaceKey = namespaceKey,
                workId = workId,
                volumeId = volumeId,
                percent = percent,
                progress = progress,
                chapterTitle = chapterTitle,
            ),
        )
    }

    private suspend fun ReaderResumeTarget.toResumeTarget(openedPublication: Publication): ResumeTarget? {
        val plan = planReaderProgressRestore(localProgress, remoteSnapshot, this@ReadiumEpubSession.source)
        val locator = plan.candidates.firstNotNullOfOrNull { restoreCandidate(it, openedPublication) } ?: return null
        val envelope = localProgress?.location
            ?.let { it as? ReflowReaderLocation }
            ?.let(ReadiumLocatorEnvelope::from)
            ?: (remoteSnapshot?.locator as? ReflowablePublicationLocation)?.readiumEnvelope
            ?: return null
        return ResumeTarget(
            notice = ReaderResumeNotice(capturedAtEpochMillis, displayPercent, locator.title),
            locator = locator,
            envelope = envelope,
            snapshot = remoteSnapshot,
        )
    }

    private suspend fun loadProgressSafely(): ReaderProgress? = try {
        progressStore.load(source.sourceId)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        null
    }

    private suspend fun restoreCandidate(
        candidate: ReaderRestoreCandidate,
        openedPublication: Publication,
    ): Locator? = when (candidate) {
        is ReaderRestoreExactLocalLocation ->
            locatorMapper.exactEngineLocator(candidate.location)
                ?.takeIf { openedPublication.contains(it) }
        is ReaderRestoreExactEngineLocation ->
            locatorMapper.exactEngineLocator(candidate.location)
                ?.takeIf { openedPublication.contains(it) }
        is ReaderRestorePublicEngineLocator ->
            locatorMapper.publicEngineLocator(candidate.locator)
                ?.takeIf { openedPublication.contains(it) }
        is ReaderRestoreResourceProgression,
        is ReaderRestoreQuotedText,
        is ReaderRestorePosition,
        is ReaderRestoreTotalProgression,
        -> null
        is ReaderRestorePdfPage, is ReaderRestoreComicPage, is ReaderRestoreAudioPosition -> null
    }

    private suspend fun quoteLocator(exact: String, openedPublication: Publication): Locator? {
        val iterator = openedPublication.search(exact) ?: return null
        try {
            while (true) {
                val page = iterator.next().getOrElse { return null } ?: break
                page.locators.firstOrNull()?.let { return it }
            }
        } finally {
            iterator.close()
        }
        return null
    }

    private fun Publication.contains(locator: Locator): Boolean {
        val target = locator.href.toString().substringBefore('#')
        return readingOrder.any { link ->
            url(link).toString().substringBefore('#') == target ||
                link.href.toString().substringBefore('#') == target
        }
    }

    private companion object {
        val LOGGER: Logger = Logger.getLogger("MobileReader")
        const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L
        const val RESTORE_STABLE_OBSERVATIONS = 3
        val UNREADABLE_PAGE_MARKER =
            "data-shuku-resource-error=\"RESOURCE_UNREADABLE\"".encodeToByteArray()
    }

    private data class ResumeTarget(
        val notice: ReaderResumeNotice,
        val locator: Locator,
        val envelope: ReadiumLocatorEnvelope,
        val snapshot: ReaderProgressSnapshotV4?,
    )
}

private fun ByteArray.containsSequence(needle: ByteArray): Boolean {
    if (needle.isEmpty() || size < needle.size) return false
    return (0..size - needle.size).any { offset ->
        needle.indices.all { index -> this[offset + index] == needle[index] }
    }
}

internal typealias ReadiumReflowableSession = ReadiumEpubSession

private fun MobiPublicationErrorKind.toReaderErrorCode(): ReaderErrorCode = when (this) {
    MobiPublicationErrorKind.DrmProtected -> ReaderErrorCode.DrmProtected
    MobiPublicationErrorKind.Unsupported -> ReaderErrorCode.UnsupportedFormat
    MobiPublicationErrorKind.Corrupt -> ReaderErrorCode.CorruptFile
    MobiPublicationErrorKind.LimitExceeded, MobiPublicationErrorKind.OutOfMemory -> ReaderErrorCode.OutOfMemoryRisk
    MobiPublicationErrorKind.Io -> ReaderErrorCode.ResourceMissing
}
