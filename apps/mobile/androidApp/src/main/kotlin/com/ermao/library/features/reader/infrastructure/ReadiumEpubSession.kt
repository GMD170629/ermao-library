package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
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
import java.io.FileNotFoundException
import kotlin.math.abs
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
import org.readium.r2.navigator.epub.EpubNavigatorFactory
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.isRestricted
import org.readium.r2.shared.publication.services.positions
import org.readium.r2.shared.publication.services.search.search
import org.readium.r2.shared.util.asset.AssetRetriever
import org.readium.r2.shared.util.getOrElse
import org.readium.r2.streamer.PublicationOpener

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
    private val progressStore: ReaderProgressStore,
    private val deviceIdentity: AndroidReaderDeviceIdentity,
    private val readium: AndroidReadiumRuntime,
    private val locatorMapper: ReadiumLocatorMapper,
    private val preferencesMapper: ReadiumPreferencesMapper,
    private val remoteSnapshot: ReaderProgressSnapshotV4? = null,
    initialPreferences: ReaderPreferences = ReaderPreferences(),
    private val externalLinkHandler: (String) -> Unit = {},
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
) : ReaderScreenController {
    private val _currentLocation = MutableStateFlow<ReaderLocation?>(null)
    override val currentLocation: StateFlow<ReaderLocation?> = _currentLocation.asStateFlow()

    private val _preferences = MutableStateFlow(initialPreferences)
    override val preferences: StateFlow<ReaderPreferences> = _preferences.asStateFlow()

    private val _restoreWarning = MutableStateFlow<ReaderError?>(null)
    override val restoreWarning: StateFlow<ReaderError?> = _restoreWarning.asStateFlow()

    private val saveMutex = Mutex()
    private var publication: Publication? = null
    private var navigator: EpubNavigatorFragment? = null
    private var publicationPositions: List<Locator> = emptyList()
    private var locationJob: Job? = null
    private var lastPersistedLocation: ReaderLocation? = null
    private var prepared = false

    override var tableOfContents: List<ReaderTocEntry> = emptyList()
        private set

    suspend fun prepare(classLoader: ClassLoader): EpubNavigatorFragment {
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
            throw ReaderOpenFailure(
                ReaderError(ReaderErrorCode.CorruptFile),
                diagnostic = ReadiumOpeningDiagnostic.AssetRetrieval(error),
            )
        }
        val openedPublication = readium.publicationOpener.open(
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
        if (openedPublication.isRestricted) {
            openedPublication.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.DrmProtected))
        }
        if (!openedPublication.conformsTo(Publication.Profile.EPUB)) {
            openedPublication.close()
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
        }
        publication = openedPublication
        publicationPositions = openedPublication.positions()

        val restorePlan = planReaderProgressRestore(loadProgressSafely(), remoteSnapshot, source)
        val initialLocator = restorePlan.candidates.firstNotNullOfOrNull { candidate ->
            restoreCandidate(candidate, openedPublication)
        }
        if ((restorePlan.localProgress != null || restorePlan.remoteSnapshot != null) && initialLocator == null) {
            _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        } else if (restorePlan.usesLocalExact) {
            _currentLocation.value = restorePlan.localProgress?.location
            lastPersistedLocation = restorePlan.localProgress?.location
        }

        tableOfContents = openedPublication.tableOfContents.mapNotNull(::tocEntry)
        val fragmentFactory = EpubNavigatorFactory(openedPublication).createFragmentFactory(
            initialLocator = initialLocator,
            initialPreferences = preferencesMapper.toReadium(_preferences.value),
            listener = object : EpubNavigatorFragment.Listener {
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

    fun bind(scope: CoroutineScope) {
        checkNotNull(navigator) { "Reader navigator is not prepared" }
        check(locationJob == null) { "Reader navigator is already bound" }
        locationJob = scope.launch {
            checkNotNull(navigator).currentLocator.collectLatest { locator ->
                val mapped = locatorMapper.toDomain(locator, source.contentFingerprint)
                _currentLocation.value = mapped
                delay(LOCAL_SAVE_DEBOUNCE_MILLIS)
                persist(mapped)
            }
        }
    }

    override fun goPrevious(): Boolean = navigator?.goBackward(animated = true) ?: false

    override fun goNext(): Boolean = navigator?.goForward(animated = true) ?: false

    override fun goTo(location: ReaderLocation): Boolean {
        val openedPublication = publication ?: return false
        val target = locatorMapper.exactEngineLocator(location, source.contentFingerprint)
            ?.takeIf { locator -> openedPublication.contains(locator) }
            ?: locatorMapper.resourceProgressionLocator(location, openedPublication)
            ?: return false
        return navigator?.go(target, animated = true) ?: false
    }

    override fun goToTotalProgression(totalProgression: Double): Boolean {
        require(totalProgression in 0.0..1.0) { "Total progression is outside 0..1" }
        val target = publicationPositions
            .filter { it.locations.totalProgression != null }
            .minByOrNull { locator ->
                abs(checkNotNull(locator.locations.totalProgression) - totalProgression)
            }
            ?: return false
        return navigator?.go(target, animated = true) ?: false
    }

    override fun updatePreferences(updated: ReaderPreferences) {
        _preferences.value = updated
        navigator?.submitPreferences(preferencesMapper.toReadium(updated))
    }

    override suspend fun flush() {
        _currentLocation.value?.let { persist(it) }
    }

    override suspend fun close() {
        flush()
        release()
    }

    fun release() {
        locationJob?.cancel()
        locationJob = null
        navigator = null
        publication?.close()
        publication = null
        publicationPositions = emptyList()
    }

    private suspend fun persist(location: ReaderLocation) {
        saveMutex.withLock {
            if (location == lastPersistedLocation) return@withLock
            progressStore.save(
                ReaderProgress(
                    sourceId = source.sourceId,
                    location = location,
                    updatedAtEpochMillis = nowEpochMillis(),
                    deviceId = deviceIdentity.stableDeviceId(),
                ),
            )
            lastPersistedLocation = location
        }
    }

    private suspend fun loadProgressSafely(): ReaderProgress? = try {
        progressStore.load(source.sourceId)
    } catch (_: IllegalArgumentException) {
        _restoreWarning.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
        null
    }

    private suspend fun restoreCandidate(
        candidate: ReaderRestoreCandidate,
        openedPublication: Publication,
    ): Locator? = when (candidate) {
        is ReaderRestoreExactLocalLocation -> null
        is ReaderRestoreExactEngineLocation ->
            locatorMapper.exactEngineLocator(candidate.location, source.contentFingerprint)
                ?.takeIf { openedPublication.contains(it) }
        is ReaderRestorePublicEngineLocator ->
            locatorMapper.publicEngineLocator(candidate.locator)
                ?.takeIf { openedPublication.contains(it) }
        is ReaderRestoreResourceProgression ->
            locatorMapper.resourceProgressionLocator(
                candidate.resourceKey,
                candidate.progression,
                position = null,
                publication = openedPublication,
            )
        is ReaderRestoreQuotedText -> quoteLocator(candidate.exact, openedPublication)
        is ReaderRestorePosition -> publicationPositions
            .filter { it.locations.position != null }
            .minByOrNull { abs(checkNotNull(it.locations.position) - candidate.position) }
        is ReaderRestoreTotalProgression -> publicationPositions
            .filter { it.locations.totalProgression != null }
            .minByOrNull { abs(checkNotNull(it.locations.totalProgression) - candidate.progression) }
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

    private fun tocEntry(link: Link): ReaderTocEntry? {
        val openedPublication = publication ?: return null
        val title = link.title?.takeIf(String::isNotBlank) ?: return null
        val locator = openedPublication.locatorFromLink(link) ?: return null
        return ReaderTocEntry(
            title = title,
            location = locatorMapper.toDomain(locator, source.contentFingerprint),
            children = link.children.mapNotNull(::tocEntry),
        )
    }

    private companion object {
        const val LOCAL_SAVE_DEBOUNCE_MILLIS = 500L
    }
}
