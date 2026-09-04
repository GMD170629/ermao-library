@file:Suppress("PARAMETER_NAME_CHANGED_ON_OVERRIDE")

package com.ermao.library.features.reader.presentation

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.net.ConnectivityManager
import android.net.Network
import android.view.MotionEvent
import android.view.KeyEvent
import androidx.activity.addCallback
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.fragment.app.Fragment
import androidx.fragment.app.commitNow
import androidx.core.net.toUri
import androidx.lifecycle.lifecycleScope
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5Database
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5LocalStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPreferencesStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderBookmarkStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderCapabilities
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigatorSession
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigationCache
import com.ermao.library.features.reader.infrastructure.AndroidReadiumRuntime
import com.ermao.library.features.reader.infrastructure.ReaderOpenFailure
import com.ermao.library.features.reader.infrastructure.ReadiumEpubSession
import com.ermao.library.features.reader.infrastructure.ReadiumComicSession
import com.ermao.library.features.reader.infrastructure.ReadiumPdfSession
import com.ermao.library.features.reader.infrastructure.AndroidPdfiumFeatureFlags
import com.ermao.library.shared.modules.reader.PdfRangeMemory
import com.ermao.library.features.reader.infrastructure.AndroidRemotePdfiumSessionConfiguration
import com.ermao.library.features.reader.infrastructure.ReadiumLocatorMapper
import com.ermao.library.features.reader.infrastructure.ReadiumPreferencesMapper
import com.ermao.library.features.reader.application.ReaderStartupPositionSource
import com.ermao.library.features.reader.application.selectReaderStartupPositionSource
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderSource
import com.ermao.library.shared.modules.reader.RemoteByteRangeReaderSource
import com.ermao.library.shared.modules.reader.RemoteComicReaderSource
import com.ermao.library.shared.modules.reader.ComicPageServerPort
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.BootstrapReaderPublication
import com.ermao.library.shared.modules.reader.LocalFirstReaderPositionStore
import com.ermao.library.shared.modules.reader.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.ReaderBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderBootstrapFailure
import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.ReaderPdfPage
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderPositionSyncCoordinator
import com.ermao.library.shared.modules.reader.ReaderPositionSyncingStore
import com.ermao.library.shared.modules.reader.ReaderPositionQueryPort
import com.ermao.library.shared.modules.reader.application.ReaderPositionQueryResult as PositionQueryResult
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.ReaderTapZones
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderReadingProgression
import com.ermao.library.shared.modules.reader.ReaderComicDirection
import com.ermao.library.shared.modules.reader.ReaderPhysicalHorizontalSide
import com.ermao.library.shared.modules.reader.ReaderPageTurnDirection
import com.ermao.library.shared.modules.reader.ReaderNavigationPolicy
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapFailure
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.shared.createAndroidReaderPositionSyncPort
import com.ermao.library.shared.createAndroidReaderBookmarkSyncPort
import com.ermao.library.shared.createAndroidReaderBootstrapGateway
import com.ermao.library.shared.createAndroidPdfRangeServerPort
import com.ermao.library.shared.createAndroidComicPageServerPort
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.downloads.toDownloadNamespace
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.logging.Level
import java.util.logging.Logger
import java.io.File

class ReaderActivity : AppCompatActivity() {
    private var controller by mutableStateOf<ReaderScreenController?>(null)
    private var opening by mutableStateOf(true)
    private var openError by mutableStateOf<ReaderError?>(null)
    private var readerTitle by mutableStateOf("")
    private var controlsVisible by mutableStateOf(false)
    private var readerPanelVisible = false
    private var readerSelectionMode: android.view.ActionMode? = null
    private var touchDownX = 0f
    private var touchDownY = 0f
    private var touchDownAt = 0L

    private var session: AndroidReaderNavigatorSession? = null
    private val navigatorAttachment =
        ReaderNavigatorAttachmentState<AndroidReaderNavigatorSession, Fragment>()
    private var closing = false
    private var openJob: Job? = null
    private var launchNamespace: com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace? = null
    private var accountObservation: com.ermao.library.shared.modules.auth.Observation? = null
    private val navigationCache by lazy { AndroidReaderNavigationCache(applicationContext) }
    private var syncingProgressStore: ReaderPositionSyncingStore? = null
    private var progressCoordinator: ReaderPositionSyncCoordinator? = null
    private var progressQueryPort: ReaderPositionQueryPort? = null
    private var progressSyncTarget: ReaderProgressSyncTarget? = null
    private var progressClientId: String? = null
    private var progressEtag: String? = null
    private val progressRecoveryMutex = Mutex()
    private var networkAvailable by mutableStateOf(false)
    private var networkCallbackRegistered = false
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            networkAvailable = true
            lifecycleScope.launch { recoverPendingProgressAndCheckRemote() }
        }

        override fun onLost(network: Network) {
            networkAvailable = getSystemService(ConnectivityManager::class.java).activeNetwork != null
        }
    }

    internal val controllerForTesting: ReaderScreenController?
        get() = controller
    internal val controlsVisibleForTesting: Boolean
        get() = controlsVisible

    override fun onCreate(savedInstanceState: Bundle?) {
        // Sessions restore their exact locator; SDK navigator fragments must not be restored.
        super.onCreate(null)
        enableEdgeToEdge()
        val runtime = (application as ErmaoLibraryApplication).mobileRuntime
        accountObservation = runtime.observeSession {
            runOnUiThread { if (launchNamespace != null && !isLaunchCurrent()) closeReader() }
        }
        networkAvailable = getSystemService(ConnectivityManager::class.java).activeNetwork != null

        val source = runCatching { intent.readerSourceOrNull() }.getOrNull()
        val managedRequest = runCatching { intent.managedDownloadRequestOrNull() }.getOrNull()
        val serverRequest = runCatching { intent.serverReaderRequestOrNull() }.getOrNull()
        if (source != null) {
            readerTitle = source.displayTitle
            session = createSession(
                source,
                createLocalOnlyProgressStore(source),
                startupPositionSource = ReaderStartupPositionSource.LocalOnly,
                comicPages = intent.comicPagesOrEmpty(),
                pdfPages = intent.pdfPagesOrEmpty(),
                pageCount = intent.getIntExtra(EXTRA_PAGE_COUNT, -1).takeIf { it > 0 },
            )
        } else if (managedRequest != null) {
            openJob = lifecycleScope.launch {
                try {
                    openManagedDownload(managedRequest)
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
                } catch (failure: ReaderOpenFailure) {
                    showOpenError(failure.readerError.code)
                } catch (failure: Exception) {
                    LOGGER.log(Level.WARNING, "reader_local_launch_failed", failure)
                    showOpenError(ReaderErrorCode.ReaderEngineError)
                }
            }
        } else if (serverRequest != null) {
            openJob = lifecycleScope.launch {
                try {
                    openServerReader(serverRequest)
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
                } catch (failure: ReaderOpenFailure) {
                    showOpenError(failure.readerError.code)
                } catch (failure: Exception) {
                    LOGGER.log(Level.WARNING, "reader_online_launch_failed", failure)
                    showOpenError(ReaderErrorCode.ReaderEngineError)
                }
            }
        } else {
            opening = false
            openError = ReaderError(ReaderErrorCode.ResourceMissing)
            readerTitle = getString(com.ermao.library.R.string.app_name)
        }

        onBackPressedDispatcher.addCallback(this) {
            val selection = readerSelectionMode
            if (selection != null) selection.finish() else closeReader()
        }
        setContent {
            val transition = downloadTransition
            val downloads = launchDownloads
            if (transition != null && downloads != null) {
                val records by downloads.recordsByResource.collectAsState()
                val failures by downloads.failureByResource.collectAsState()
                ReaderDownloadTransition(
                    descriptor = transition.descriptor,
                    record = records[transition.descriptor.identity.resourceId],
                    failureCode = failures[transition.descriptor.identity.resourceId],
                    preparing = preparingDownloadedFile,
                    application = application as ErmaoLibraryApplication,
                    context = downloads.requestContext,
                    onCancel = ::closeReader,
                    onRetry = { retryRequiredDownload(transition.descriptor) },
                )
            } else {
            ReaderScreen(
                title = readerTitle,
                controller = controller,
                opening = opening,
                openError = openError,
                controlsVisible = controlsVisible,
                onControlsVisibleChange = { controlsVisible = it },
                onPanelVisibilityChange = { readerPanelVisible = it },
                onClose = ::closeReader,
                onRetryOpen = when {
                    managedRequest != null -> { { recreate() } }
                    serverRequest != null -> { { retryServerReader(serverRequest) } }
                    else -> null
                },
                onNavigatorContainerReady = {
                    navigatorAttachment.markContainerReady()
                    attachNavigatorIfReady()
                },
            )
            }
        }

        if (source != null) {
            openJob = lifecycleScope.launch { prepareSession(checkNotNull(session)) }
        }
    }

    override fun onResumeFragments() {
        super.onResumeFragments()
        attachNavigatorIfReady()
        lifecycleScope.launch { recoverPendingProgressAndCheckRemote() }
    }

    override fun onStart() {
        super.onStart()
        val connectivity = getSystemService(ConnectivityManager::class.java)
        runCatching { connectivity.registerDefaultNetworkCallback(networkCallback) }
            .onSuccess { networkCallbackRegistered = true }
    }

    override fun onActionModeStarted(mode: android.view.ActionMode) {
        super.onActionModeStarted(mode)
        readerSelectionMode = mode
    }

    override fun onActionModeFinished(mode: android.view.ActionMode) {
        super.onActionModeFinished(mode)
        if (readerSelectionMode == mode) readerSelectionMode = null
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        // Reflowable content uses Readium's unhandled-tap API, after links and selection.
        if (controller?.morphology == ReaderMorphology.Reflowable || readerPanelVisible) {
            return super.dispatchTouchEvent(event)
        }
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                touchDownX = event.x
                touchDownY = event.y
                touchDownAt = event.eventTime
            }
            MotionEvent.ACTION_UP -> {
                val moved = kotlin.math.hypot(event.x - touchDownX, event.y - touchDownY)
                val tapSlop = 12 * resources.displayMetrics.density
                if (!controlsVisible && moved <= tapSlop && event.eventTime - touchDownAt <= 600) {
                    routeReaderTap(event.x / resources.displayMetrics.widthPixels.coerceAtLeast(1))
                }
            }
        }
        return super.dispatchTouchEvent(event)
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (readerPanelVisible || readerSelectionMode != null || currentFocus?.onCheckIsTextEditor() == true) {
            return super.dispatchKeyEvent(event)
        }
        if (event.action != KeyEvent.ACTION_DOWN || event.repeatCount > 0) {
            return super.dispatchKeyEvent(event)
        }
        val reader = controller ?: return super.dispatchKeyEvent(event)
        val interaction = reader.preferences.value.interaction
        val handled = when (event.keyCode) {
            KeyEvent.KEYCODE_ESCAPE -> {
                if (!controlsVisible) controlsVisible = true
                true
            }
            KeyEvent.KEYCODE_DPAD_LEFT -> interaction.keyboardPageTurn &&
                routePhysicalHorizontalTurn(reader, ReaderPhysicalHorizontalSide.Left)
            KeyEvent.KEYCODE_DPAD_RIGHT -> interaction.keyboardPageTurn &&
                routePhysicalHorizontalTurn(reader, ReaderPhysicalHorizontalSide.Right)
            KeyEvent.KEYCODE_PAGE_UP -> interaction.keyboardPageTurn && reader.goPrevious()
            KeyEvent.KEYCODE_PAGE_DOWN, KeyEvent.KEYCODE_SPACE -> interaction.keyboardPageTurn && reader.goNext()
            KeyEvent.KEYCODE_VOLUME_UP -> interaction.volumeKeyPageTurn && reader.goPrevious()
            KeyEvent.KEYCODE_VOLUME_DOWN -> interaction.volumeKeyPageTurn && reader.goNext()
            else -> false
        }
        return if (handled) true else super.dispatchKeyEvent(event)
    }

    private fun routeReaderTap(horizontalFraction: Float) {
        if (readerPanelVisible || readerSelectionMode != null) return
        val reader = controller ?: return
        when (reader.preferences.value.interaction.tapZones) {
            ReaderTapZones.Disabled -> controlsVisible = true
            ReaderTapZones.Standard -> when {
                horizontalFraction < 0.33f -> routePhysicalHorizontalTurn(reader, ReaderPhysicalHorizontalSide.Left)
                horizontalFraction > 0.67f -> routePhysicalHorizontalTurn(reader, ReaderPhysicalHorizontalSide.Right)
                else -> controlsVisible = true
            }
            ReaderTapZones.Reversed -> when {
                horizontalFraction < 0.33f -> routePhysicalHorizontalTurn(reader, ReaderPhysicalHorizontalSide.Left, reversed = true)
                horizontalFraction > 0.67f -> routePhysicalHorizontalTurn(reader, ReaderPhysicalHorizontalSide.Right, reversed = true)
                else -> controlsVisible = true
            }
        }
    }

    private fun routePhysicalHorizontalTurn(
        reader: ReaderScreenController,
        side: ReaderPhysicalHorizontalSide,
        reversed: Boolean = false,
    ): Boolean {
        val preferences = reader.preferences.value
        val progression = when {
            reader.morphology == ReaderMorphology.Comic &&
                reader.capabilities.comic.supportsDirection -> {
                when (preferences.comic.direction) {
                    ReaderComicDirection.LeftToRight -> ReaderReadingProgression.LeftToRight
                    ReaderComicDirection.RightToLeft -> ReaderReadingProgression.RightToLeft
                }
            }
            reader.morphology == ReaderMorphology.Reflowable &&
                reader.capabilities.supportsReadingProgression -> preferences.epub.readingProgression
            else -> ReaderReadingProgression.LeftToRight
        }
        val effectiveSide = if (!reversed) side else when (side) {
            ReaderPhysicalHorizontalSide.Left -> ReaderPhysicalHorizontalSide.Right
            ReaderPhysicalHorizontalSide.Right -> ReaderPhysicalHorizontalSide.Left
        }
        return when (ReaderNavigationPolicy.physicalHorizontalPageTurn(effectiveSide, progression)) {
            ReaderPageTurnDirection.Previous -> reader.goPrevious()
            ReaderPageTurnDirection.Next -> reader.goNext()
        }
    }

    override fun onStop() {
        if (networkCallbackRegistered) {
            runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(networkCallback) }
            networkCallbackRegistered = false
        }
        if (!closing && !isChangingConfigurations) session?.let { readerSession ->
            lifecycleScope.launch {
                runCatching { readerSession.flush() }
                runCatching { retryPendingUploadWithinLifecycleBudget() }
            }
        }
        super.onStop()
    }

    private suspend fun checkRemoteProgress() {
        val query = progressQueryPort ?: return
        val target = progressSyncTarget ?: return
        val coordinator = progressCoordinator ?: return
        val clientId = progressClientId ?: return
        when (val result = query.load(target, progressEtag)) {
            is PositionQueryResult.Current -> {
                progressEtag = result.etag ?: progressEtag
                val snapshot = result.snapshot ?: return
                coordinator.observeRemotePosition(snapshot, clientId)
            }
            is PositionQueryResult.Unchanged -> progressEtag = result.etag ?: progressEtag
            is PositionQueryResult.Failure -> Unit
        }
    }

    private suspend fun recoverPendingProgressAndCheckRemote() {
        progressRecoveryMutex.withLock {
            runCatching { syncingProgressStore?.retryPendingUpload() }
            runCatching { syncingProgressStore?.awaitPendingUpload() }
            runCatching { checkRemoteProgress() }
        }
    }

    override fun onDestroy() {
        accountObservation?.cancel()
        if (isChangingConfigurations) downloadObservation?.cancel() else cancelLaunchDownload()
        openJob?.cancel()
        lifecycleScope.launch { progressCoordinator?.cancelWorker() }
        session?.release()
        session = null
        super.onDestroy()
    }

    private var launchDownloads: com.ermao.library.features.downloads.AccountDownloads? = null
    private var launchCoordinator: com.ermao.library.shared.modules.reader.ReaderLaunchCoordinator? = null
    private var launchRequest: ServerReaderRequest? = null
    private var downloadTransition by mutableStateOf<com.ermao.library.shared.modules.reader.ReaderLaunchDownload?>(null)
    private var preparingDownloadedFile by mutableStateOf(false)
    private var ownsLaunchDownload = false
    private var downloadObservation: kotlinx.coroutines.Job? = null
    private var managedArtifactRebuildAttempted = false

    private fun isLaunchCurrent(): Boolean {
        if (closing) return false
        val expected = launchNamespace ?: return true
        val current = (application as ErmaoLibraryApplication).mobileRuntime.currentSession as? AppSession.Authenticated
        return current?.identity?.namespace == expected
    }

    private fun cancelLaunchDownload() {
        downloadObservation?.cancel()
        if (ownsLaunchDownload) launchRequest?.resourceId?.let { launchDownloads?.cancelReaderDownload(it) }
        ownsLaunchDownload = false
    }

    private fun startRequiredDownload(
        decision: com.ermao.library.shared.modules.reader.ReaderLaunchDownload,
        request: ServerReaderRequest,
    ) {
        if (closing || downloadTransition != null) return
        val downloads = launchDownloads ?: return
        val coordinator = launchCoordinator ?: return
        val descriptor = decision.descriptor
        navigatorAttachment.markContainerUnavailable()
        downloadTransition = decision
        ownsLaunchDownload = downloads.requestReaderDownload(request.resourceId, descriptor)
        downloadObservation = lifecycleScope.launch {
            val completed = downloads.recordsByResource
                .map { coordinator.complete(descriptor) }
                .first { it is com.ermao.library.shared.modules.reader.ReaderLaunchLocal }
                as com.ermao.library.shared.modules.reader.ReaderLaunchLocal
            val active = (application as ErmaoLibraryApplication).mobileRuntime.currentSession as? AppSession.Authenticated
            if (closing || active?.identity?.namespace?.let {
                    it.serverIdentity == downloads.requestContext.namespace.serverIdentity &&
                        it.userId == downloads.requestContext.namespace.userId &&
                        it.authorizationVersion == downloads.requestContext.namespace.authorizationVersion
                } != true) return@launch
            ownsLaunchDownload = false
            preparingDownloadedFile = true
            try {
                openLaunchArtifact(completed.artifact, request)
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (failure: ReaderOpenFailure) {
                showOpenError(failure.readerError.code)
            } catch (failure: Exception) {
                LOGGER.log(Level.WARNING, "reader_downloaded_open_failed", failure)
                showOpenError(ReaderErrorCode.ReaderEngineError)
            } finally {
                if (downloadTransition == decision) downloadTransition = null
                preparingDownloadedFile = false
            }
        }
    }

    private fun retryRequiredDownload(descriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor) {
        val downloads = launchDownloads ?: return
        ownsLaunchDownload = downloads.requestReaderDownload(descriptor.identity.resourceId, descriptor)
    }

    private suspend fun openLaunchArtifact(
        artifact: com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact,
        request: ServerReaderRequest,
    ) {
        val descriptor = artifact.descriptor
        openManagedDownload(ManagedDownloadReaderRequest(
            request.profileId, descriptor.identity.bookId, request.resourceId, descriptor.identity.assetId,
            descriptor.resourceTitle, artifact.localReference, descriptor.format, request.initialTarget,
        ))
    }

    private suspend fun openServerReader(
        request: ServerReaderRequest,
    ) {
        val runtime = (application as ErmaoLibraryApplication).mobileRuntime
        if (runtime.currentSession !is AppSession.Authenticated) runtime.start()
        val authenticated = runtime.currentSession as? AppSession.Authenticated
        if (authenticated == null || authenticated.profile.id != request.profileId) {
            showOpenError(ReaderErrorCode.ResourceMissing)
            return
        }
        launchRequest = request
        launchNamespace = authenticated.identity.namespace
        val downloads = (application as ErmaoLibraryApplication).accountDownloads(authenticated)
        launchDownloads = downloads
        val coordinator = downloads.readerLaunchCoordinator()
        launchCoordinator = coordinator
        val streamDescriptor = when (val launch = coordinator.prepare(downloads.requestContext, request.resourceId)) {
            is com.ermao.library.shared.modules.reader.ReaderLaunchLocal -> {
                openLaunchArtifact(launch.artifact, request)
                return
            }
            is com.ermao.library.shared.modules.reader.ReaderLaunchUnavailable -> {
                showOpenError(launch.code, launch.safetyFailure)
                return
            }
            is com.ermao.library.shared.modules.reader.ReaderLaunchStream -> launch.descriptor
            is com.ermao.library.shared.modules.reader.ReaderLaunchDownload -> {
                startRequiredDownload(launch, request)
                return
            }
        }
        val privateNamespace = authenticated.identity.namespace
        val namespace = ReaderSyncNamespace(
            privateNamespace.serverIdentity,
            privateNamespace.userId,
            privateNamespace.authorizationVersion,
        )
        val preferencesStore = AndroidReaderPreferencesStore(
            applicationContext,
            namespace.serverIdentity,
            namespace.userId,
        )
        val serverGateway = createAndroidReaderBootstrapGateway(applicationContext)
        val bootstrapper = BootstrapReaderPublication(bootstrapGateway = serverGateway)
        when (val result = bootstrapper.execute(
            ReaderBootstrapRequest(authenticated.profile, namespace, request.resourceId),
        )) {
            is ReaderPublicationBootstrapFailure -> {
                LOGGER.log(
                    Level.SEVERE,
                    "reader_error platform=android format=unknown entry=work_detail stage=bootstrap " +
                        "code=${result.failureCode}",
                )
                showOpenError(result.readerErrorCode)
            }
            is ReaderPublicationBootstrapContent -> {
                result.source.assetId?.let { assetId ->
                    AndroidReaderPublicationStore(applicationContext, namespace)
                        .removeAutomaticReplica(request.resourceId, assetId)
                }
                navigationCache.save(
                    namespace,
                    request.resourceId,
                    result.bootstrap,
                )
                val source = result.source
                if (source !is LocalReaderSource &&
                    source !is RemoteByteRangeReaderSource &&
                    source !is RemoteComicReaderSource
                ) {
                    showOpenError(ReaderErrorCode.UnsupportedFormat)
                    return
                }
                var sessionProgressStore: ReaderPositionSyncingStore = NonBlockingReaderPositionStore
                var startupRemoteSnapshot = result.bootstrap.remoteSnapshot
                var startupPositionSource = selectReaderStartupPositionSource(
                    hasExplicitTarget = request.initialTarget != null,
                    hasLocalPending = false,
                    hasServerSnapshot = result.bootstrap.remoteSnapshot != null,
                    localOnlySource = false,
                )
                var sessionCoordinator: ReaderPositionSyncCoordinator? = null
                try {
                    val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
                    val database = AndroidReaderV5Database(
                        applicationContext,
                        ReaderLocalProgressIdentity(
                            namespace = namespace,
                            clientId = clientId,
                            bookId = result.bootstrap.target.bookId,
                            resourceId = source.resourceId,
                        ),
                    )
                    val progressServer = createAndroidReaderPositionSyncPort(
                        applicationContext,
                        authenticated.profile,
                    )
                    val coordinator = ReaderPositionSyncCoordinator(database, progressServer, lifecycleScope)
                    val syncingStore = LocalFirstReaderPositionStore(
                        database,
                        result.bootstrap.target,
                        coordinator,
                    )
                    val durableState = database.loadPositionSyncState()
                    progressCoordinator = coordinator
                    sessionCoordinator = coordinator
                    coordinator.beginSession(result.bootstrap.remoteSnapshot)
                    progressQueryPort = progressServer
                    progressSyncTarget = result.bootstrap.target
                    progressClientId = clientId
                    progressEtag = result.bootstrap.remoteSnapshot?.revision?.let(::readerProgressEtag)
                        ?: readerProgressEtag(0)
                    if (durableState.pending != null) {
                        // A pending v5 mutation is the local restore owner. Keep
                        // its exact body and let the single coordinator retry it.
                        if (request.initialTarget == null) {
                            startupPositionSource = ReaderStartupPositionSource.LocalPending
                            startupRemoteSnapshot = null
                        }
                        coordinator.retryPending(result.bootstrap.target)
                    }
                    syncingProgressStore = syncingStore
                    sessionProgressStore = syncingStore
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
                } catch (failure: Exception) {
                    LOGGER.log(Level.WARNING, "reader_progress_startup_ignored", failure)
                    clearProgressRuntime()
                }
                readerTitle = source.displayTitle
                session = createSession(
                    source,
                    sessionProgressStore,
                    startupRemoteSnapshot,
                    sessionCoordinator,
                    preferencesStore,
                    AndroidReaderBookmarkStore(
                        applicationContext,
                        namespace,
                        source.resourceId,
                    ),
                    createAndroidReaderBookmarkSyncPort(applicationContext, authenticated.profile),
                    ReaderBookmarkSyncTarget(
                        namespace.serverIdentity,
                        source.resourceId,
                    ),
                    namespaceKey = namespace.presentationKey(),
                    initialTarget = request.initialTarget,
                    startupPositionSource = startupPositionSource,
                    comicPages = result.bootstrap.comicPages,
                    pdfPages = result.bootstrap.pdfPages,
                    pageCount = result.bootstrap.pageCount,
                    namespace = namespace,
                    comicPageServer = (source as? RemoteComicReaderSource)?.let {
                        createAndroidComicPageServerPort(applicationContext, authenticated.profile)
                    },
                    remotePdfium = (source as? RemoteByteRangeReaderSource)?.let {
                        val rangeCache = PdfRangeMemory()
                        rangeCache.activateNamespace(it.namespace)
                        AndroidRemotePdfiumSessionConfiguration(
                            cache = rangeCache,
                            server = createAndroidPdfRangeServerPort(applicationContext, authenticated.profile),
                            materializeOriginal = {
                                materializePdfOriginal(downloads, coordinator, streamDescriptor)
                            },
                        )
                    },
                )
                prepareSession(checkNotNull(session))
            }
        }
    }

    private suspend fun materializePdfOriginal(
        downloads: com.ermao.library.features.downloads.AccountDownloads,
        coordinator: com.ermao.library.shared.modules.reader.ReaderLaunchCoordinator,
        descriptor: com.ermao.library.shared.modules.downloads.DownloadDescriptor,
    ): File {
        val resourceId = descriptor.identity.resourceId
        try {
            val existing = coordinator.complete(descriptor)
            val local = if (existing is com.ermao.library.shared.modules.reader.ReaderLaunchLocal) {
                LOGGER.info(
                    "event=pdf_materialization_reused platform=android resource=$resourceId " +
                        "bytes=${descriptor.totalBytes} result=success",
                )
                existing
            } else {
                LOGGER.info(
                    "event=pdf_materialization_started platform=android resource=$resourceId " +
                        "bytes=${descriptor.totalBytes}",
                )
                withContext(Dispatchers.Main.immediate) {
                    downloads.requestDownload(resourceId, descriptor)
                }
                combine(downloads.recordsByResource, downloads.failureByResource) { _, failures ->
                    failures[resourceId]?.let { failureCode ->
                        LOGGER.warning(
                            "event=pdf_materialization_failed platform=android resource=$resourceId " +
                                "bytes=${descriptor.totalBytes} result=$failureCode",
                        )
                        throw ReaderOpenFailure(
                            ReaderError(
                                com.ermao.library.shared.modules.reader.readerErrorCodeForFailure(
                                    failureCode,
                                    false,
                                ),
                            ),
                        )
                    }
                    coordinator.complete(descriptor)
                }.first { it is com.ermao.library.shared.modules.reader.ReaderLaunchLocal }
                    as com.ermao.library.shared.modules.reader.ReaderLaunchLocal
            }
            if (!withContext(Dispatchers.Main.immediate) { isLaunchCurrent() }) {
                throw kotlinx.coroutines.CancellationException("Reader namespace changed")
            }
            val file = (application as ErmaoLibraryApplication).downloadFiles
                .resolveLocalReference(local.artifact.localReference)
            if (file == null || !file.isFile || file.length() != descriptor.totalBytes) {
                LOGGER.warning(
                    "event=pdf_materialization_failed platform=android resource=$resourceId " +
                        "bytes=${descriptor.totalBytes} result=DOWNLOAD_LOCAL_FILE_INVALID",
                )
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing))
            }
            LOGGER.info(
                "event=pdf_materialization_completed platform=android resource=$resourceId " +
                    "bytes=${descriptor.totalBytes} result=success",
            )
            return file
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            LOGGER.info(
                "event=pdf_materialization_cancelled platform=android resource=$resourceId " +
                    "bytes=${descriptor.totalBytes} result=cancelled",
            )
            throw cancelled
        } catch (error: Exception) {
            LOGGER.warning(
                "event=pdf_materialization_failed platform=android resource=$resourceId " +
                    "bytes=${descriptor.totalBytes} result=terminal_failure",
            )
            throw error
        }
    }

    private suspend fun openManagedDownload(request: ManagedDownloadReaderRequest) {
        val application = application as ErmaoLibraryApplication
        val runtime = application.mobileRuntime
        if (runtime.currentSession !is AppSession.Authenticated) {
            runtime.start()
        }
        val activeSession = when (val current = runtime.currentSession) {
            is AppSession.Authenticated -> ActiveReaderSession(current.profile, current.identity, current)
            else -> null
        }
        if (activeSession == null || activeSession.profile.id != request.profileId) {
            showOpenError(ReaderErrorCode.ResourceMissing)
            return
        }
        val privateIdentity = activeSession.identity.namespace
        launchNamespace = privateIdentity
        val artifact = application.sharedDownloadCatalog.listArtifacts(
            com.ermao.library.shared.modules.downloads.DownloadNamespace(privateIdentity.serverIdentity,
                privateIdentity.userId, privateIdentity.authorizationVersion),
        ).firstOrNull { it.identity.resourceId == request.resourceId && it.identity.assetId == request.assetId &&
            it.localReference == request.localReference }
        if (artifact == null) {
            if (!rebuildMissingManagedArtifact(request)) showOpenError(ReaderErrorCode.ResourceMissing)
            return
        }
        com.ermao.library.shared.modules.reader.ReaderAdmission.localFailure(request.sourceFormat, artifact.verifiedBytes)?.let {
            showOpenError(
                it,
                com.ermao.library.shared.modules.reader.ReaderAdmission.localSafetyFailure(
                    request.sourceFormat,
                    artifact.verifiedBytes,
                ),
            )
            return
        }
        val readerNamespace = activeSession.identity.namespace
        val preferencesStore = AndroidReaderPreferencesStore(
            applicationContext,
            readerNamespace.serverIdentity,
            readerNamespace.userId,
        )
        val localFile = application.downloadFiles.resolveLocalReference(request.localReference)
        val exactSourceFormat = ReaderSourceFormat.fromWireValue(request.sourceFormat)
        if (exactSourceFormat == null) {
            showOpenError(ReaderErrorCode.UnsupportedFormat)
            return
        }
        val isOriginalPageSet = exactSourceFormat == ReaderSourceFormat.ImageDir
        if (localFile == null || (isOriginalPageSet && !localFile.isDirectory) || (!isOriginalPageSet && !localFile.isFile)) {
            if (!rebuildMissingManagedArtifact(request)) showOpenError(ReaderErrorCode.ResourceMissing)
            return
        }
        val source = LocalReaderSource(
            resourceId = request.resourceId, displayTitle = request.displayTitle,
            format = exactSourceFormat.readerFormat, bookId = request.bookId,
            assetId = request.assetId, sourceFormat = exactSourceFormat,
        )
        val cachedNavigation = navigationCache.load(
            ReaderSyncNamespace(
                readerNamespace.serverIdentity,
                readerNamespace.userId,
                readerNamespace.authorizationVersion,
            ),
            request.resourceId,
        )
        val comicPages: List<ReaderComicPage> = cachedNavigation?.comicPages.orEmpty()
        val pdfPages: List<ReaderPdfPage> = cachedNavigation?.pdfPages.orEmpty()
        val pageCount: Int? = cachedNavigation?.pageCount
        // Verified Downloads are a local entry. Progress synchronization runs after opening.
        val progressSetup = createBestEffortManagedProgressStore(activeSession, request, source, exactSourceFormat)
        readerTitle = source.displayTitle
        session = createSession(
            source,
            progressSetup.store,
            progressSetup.remoteSnapshot,
            progressCoordinator,
            preferencesStore,
            AndroidReaderBookmarkStore(
                applicationContext,
                ReaderSyncNamespace(
                    readerNamespace.serverIdentity,
                    readerNamespace.userId,
                    readerNamespace.authorizationVersion,
                ),
                source.resourceId,
            ),
            createAndroidReaderBookmarkSyncPort(applicationContext, activeSession.profile),
            ReaderBookmarkSyncTarget(
                readerNamespace.serverIdentity,
                source.resourceId,
            ),
            namespaceKey = readerNamespace.presentationKey(),
            initialTarget = request.initialTarget,
            startupPositionSource = progressSetup.startupPositionSource,
            comicPages = comicPages,
            pdfPages = pdfPages,
            pageCount = pageCount,
            localPageSetDirectory = localFile.takeIf { isOriginalPageSet },
            completedPublication = com.ermao.library.features.reader.infrastructure.AndroidCompletedPublication(source, localFile),
            namespace = ReaderSyncNamespace(
                readerNamespace.serverIdentity,
                readerNamespace.userId,
                readerNamespace.authorizationVersion,
            ),
        )
        prepareSession(checkNotNull(session))
    }

    private suspend fun rebuildMissingManagedArtifact(request: ManagedDownloadReaderRequest): Boolean {
        if (managedArtifactRebuildAttempted) return false
        managedArtifactRebuildAttempted = true
        downloadTransition = null
        openServerReader(ServerReaderRequest(request.profileId, request.resourceId, request.initialTarget))
        return true
    }


    private fun retryServerReader(request: ServerReaderRequest) {
        if (openJob?.isActive == true) return
        openError = null
        opening = true
        controller = null
        navigatorAttachment.resetSession()
        session?.release()
        session = null
        openJob = lifecycleScope.launch {
            try {
                openServerReader(request)
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (failure: ReaderOpenFailure) {
                showOpenError(failure.readerError.code)
            } catch (failure: Exception) {
                LOGGER.log(Level.WARNING, "reader_server_retry_failed", failure)
                showOpenError(ReaderErrorCode.ReaderEngineError)
            }
        }
    }

    private data class ManagedProgressStoreSetup(
        val store: ReaderPositionSyncingStore,
        val startupPositionSource: ReaderStartupPositionSource,
        val remoteSnapshot: ReaderProgressSnapshotV5?,
    )

    private suspend fun createOfflineManagedProgressStore(
        activeSession: ActiveReaderSession,
        request: ManagedDownloadReaderRequest,
        source: LocalReaderSource,
        sourceFormat: ReaderSourceFormat,
    ): ManagedProgressStoreSetup {
        val privateNamespace = activeSession.identity.namespace
        val namespace = ReaderSyncNamespace(
            privateNamespace.serverIdentity,
            privateNamespace.userId,
            privateNamespace.authorizationVersion,
        )
        val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
        val target = ReaderProgressSyncTarget(
            namespace = namespace,
            bookId = request.bookId,
            resourceId = source.resourceId,
            sourceFormat = sourceFormat.readerFormat,
        )
        val database = AndroidReaderV5Database(
            applicationContext,
            ReaderLocalProgressIdentity(namespace, clientId, request.bookId, source.resourceId),
        )
        val progressServer = createAndroidReaderPositionSyncPort(applicationContext, activeSession.profile)
        val coordinator = ReaderPositionSyncCoordinator(database, progressServer, lifecycleScope)
        val syncingStore = LocalFirstReaderPositionStore(database, target, coordinator)
        val durableState = database.loadPositionSyncState()
        progressEtag = readerProgressEtag(durableState.confirmedRevision)

        val remoteSnapshot = try {
            // A managed local artifact does not have a bootstrap snapshot. Ask
            // for the body unconditionally so an unchanged response cannot
            // accidentally look like the empty/start state.
            when (val result = progressServer.load(target, null)) {
                is PositionQueryResult.Current -> {
                    progressEtag = result.etag ?: progressEtag
                    result.snapshot
                }
                is PositionQueryResult.Unchanged -> {
                    progressEtag = result.etag ?: progressEtag
                    null
                }
                is PositionQueryResult.Failure -> null
            }
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            null
        }
        coordinator.beginSession(snapshot = remoteSnapshot)
        progressCoordinator = coordinator
        progressQueryPort = progressServer
        progressSyncTarget = target
        progressClientId = clientId
        syncingProgressStore = syncingStore

        val startupPositionSource = selectReaderStartupPositionSource(
            hasExplicitTarget = request.initialTarget != null,
            hasLocalPending = durableState.pending != null,
            hasServerSnapshot = remoteSnapshot != null,
            localOnlySource = false,
        )
        if (durableState.pending != null) coordinator.retryPending(target)
        return ManagedProgressStoreSetup(
            store = syncingStore,
            startupPositionSource = startupPositionSource,
            remoteSnapshot = remoteSnapshot.takeIf {
                startupPositionSource != ReaderStartupPositionSource.LocalPending
            },
        )
    }

    private suspend fun createBestEffortManagedProgressStore(
        activeSession: ActiveReaderSession,
        request: ManagedDownloadReaderRequest,
        source: LocalReaderSource,
        sourceFormat: ReaderSourceFormat,
    ): ManagedProgressStoreSetup = try {
        createOfflineManagedProgressStore(activeSession, request, source, sourceFormat)
    } catch (cancelled: kotlinx.coroutines.CancellationException) {
        throw cancelled
    } catch (failure: Exception) {
        LOGGER.log(Level.WARNING, "reader_progress_store_unavailable", failure)
        clearProgressRuntime()
        ManagedProgressStoreSetup(
            store = NonBlockingReaderPositionStore,
            startupPositionSource = selectReaderStartupPositionSource(
                hasExplicitTarget = request.initialTarget != null,
                hasLocalPending = false,
                hasServerSnapshot = false,
                localOnlySource = false,
            ),
            remoteSnapshot = null,
        )
    }

    private fun clearProgressRuntime() {
        syncingProgressStore = null
        progressCoordinator = null
        progressQueryPort = null
        progressSyncTarget = null
        progressClientId = null
        progressEtag = null
    }

    private suspend fun prepareSession(readerSession: AndroidReaderNavigatorSession): Boolean {
        try {
            val preparedNavigator = readerSession.prepare(classLoader)
            if (!isLaunchCurrent() || !navigatorAttachment.publish(session, readerSession, preparedNavigator)) {
                readerSession.release()
                return false
            }
            attachNavigatorIfReady()
            return true
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            navigatorAttachment.discard(readerSession)
            readerSession.release()
            throw cancelled
        } catch (failure: ReaderOpenFailure) {
            navigatorAttachment.discard(readerSession)
            readerSession.release()
            showOpenError(failure.readerError)
            LOGGER.log(
                Level.SEVERE,
                "reader_error platform=android format=unknown entry=reader stage=open " +
                    "code=${failure.readerError.code.wireValue}",
            )
            return false
        } catch (failure: Exception) {
            navigatorAttachment.discard(readerSession)
            readerSession.release()
            LOGGER.log(Level.WARNING, "reader_engine_prepare_failed", failure)
            showOpenError(ReaderErrorCode.ReaderEngineError)
            return false
        }
    }

    private fun showOpenError(
        code: ReaderErrorCode,
        safetyFailure: com.ermao.library.shared.modules.reader.ReaderSafetyFailure? = null,
    ) = showOpenError(
        ReaderError(
            code = code,
            safeContext = safetyFailure?.let { failure ->
                mapOf("ruleId" to failure.ruleId, "errorCode" to failure.errorCode)
            }.orEmpty(),
        ),
    )

    private fun showOpenError(error: ReaderError) {
        opening = false
        openError = error
        LOGGER.log(
            Level.SEVERE,
            "reader_error platform=android format=unknown entry=reader " +
                "stage=${error.safeContext["stage"] ?: "open"} " +
                "code=${error.safeContext["code"] ?: error.code.wireValue}",
        )
    }

    private suspend fun retryPendingUploadWithinLifecycleBudget() {
        withTimeoutOrNull(SYNC_FLUSH_TIMEOUT_MILLIS) {
            syncingProgressStore?.retryPendingUpload()
            syncingProgressStore?.awaitPendingUpload()
        }
    }

    private fun createSession(
        source: ReaderSource,
        progressStore: ReaderPositionSyncingStore,
        remoteSnapshot: ReaderProgressSnapshotV5? = null,
        progressCoordinator: ReaderPositionSyncCoordinator? = null,
        preferencesStore: AndroidReaderPreferencesStore? = null,
        bookmarkStore: AndroidReaderBookmarkStore? = null,
        bookmarkSyncPort: ReaderBookmarkSyncPort? = null,
        bookmarkSyncTarget: ReaderBookmarkSyncTarget? = null,
        namespaceKey: String? = null,
        initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null,
        startupPositionSource: ReaderStartupPositionSource = ReaderStartupPositionSource.Start,
        comicPages: List<ReaderComicPage> = emptyList(),
        pdfPages: List<ReaderPdfPage> = emptyList(),
        pageCount: Int? = null,
        comicPageServer: ComicPageServerPort? = null,
        remotePdfium: AndroidRemotePdfiumSessionConfiguration? = null,
        localPageSetDirectory: File? = null,
        completedPublication: com.ermao.library.features.reader.infrastructure.AndroidCompletedPublication? = null,
        namespace: ReaderSyncNamespace? = null,
    ): AndroidReaderNavigatorSession {
        val sourceFormat = requireNotNull(source.sourceFormat) { "Reader source format is missing" }
        if (source is LocalReaderSource && !sourceFormat.isComic) {
            try {
                AndroidReaderCapabilities.registry.requireOpenable(sourceFormat)
            } catch (error: IllegalArgumentException) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat), cause = error)
            }
        }
        if (sourceFormat.isComic) {
            val publicationStore = AndroidReaderPublicationStore(applicationContext, namespace, completedPublication)
            val readium = AndroidReadiumRuntime(applicationContext)
            val sessionPages = if (source is LocalReaderSource) {
                if (source.sourceFormat == ReaderSourceFormat.ImageDir) {
                    com.ermao.library.features.reader.infrastructure.ImageDirectoryReadiumPublicationFactory()
                        .indexPages(
                            requireNotNull(localPageSetDirectory) { "IMAGE_DIR bundle is missing" },
                            source.resourceId,
                        )
                } else {
                    val file = publicationStore.resolve(source)
                    com.ermao.library.features.reader.infrastructure.CbzReadiumPublicationFactory()
                        .indexPages(file, comicPages)
                }
            } else {
                comicPages
            }
            if (sessionPages.isEmpty()) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile))
            }
            return ReadiumComicSession(
                source = source,
                canonicalPages = sessionPages,
                publicationStore = publicationStore,
                localPageSetDirectory = localPageSetDirectory,
                progressStore = progressStore,
                deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
                readium = readium,
                comicPageServer = comicPageServer,
                remoteSnapshot = remoteSnapshot,
                initialTarget = initialTarget,
                startupPositionSource = startupPositionSource,
                progressCoordinator = progressCoordinator,
                initialPreferences = runCatching { preferencesStore?.load() }.getOrNull()
                    ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
                persistPreferences = { preferences -> preferencesStore?.save(preferences) },
                presentationNamespaceKey = namespaceKey,
                publishProgressUpdate = (application as ErmaoLibraryApplication)
                    .readerProgressPresentationCenter::publish,
            )
        }
        if (sourceFormat == ReaderSourceFormat.Pdf) {
            return ReadiumPdfSession(
                source = source,
                expectedPageCount = pageCount,
                canonicalPages = pdfPages,
                publicationStore = AndroidReaderPublicationStore(applicationContext, namespace, completedPublication),
                progressStore = progressStore,
                deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
                remotePdfium = remotePdfium,
                remoteSnapshot = remoteSnapshot,
                initialTarget = initialTarget,
                startupPositionSource = startupPositionSource,
                progressCoordinator = progressCoordinator,
                initialPreferences = runCatching { preferencesStore?.load() }.getOrNull()
                    ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
                persistPreferences = { preferences -> preferencesStore?.save(preferences) },
                presentationNamespaceKey = namespaceKey,
                publishProgressUpdate = (application as ErmaoLibraryApplication)
                    .readerProgressPresentationCenter::publish,
            )
        }
        val localSource = source as? LocalReaderSource
            ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat))
        return ReadiumEpubSession(
            source = localSource,
            publicationStore = AndroidReaderPublicationStore(applicationContext, namespace, completedPublication),
            progressStore = progressStore,
            deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
            readium = AndroidReadiumRuntime(applicationContext),
            locatorMapper = ReadiumLocatorMapper(),
            preferencesMapper = ReadiumPreferencesMapper(resources),
            remoteSnapshot = remoteSnapshot,
            initialTarget = initialTarget,
            startupPositionSource = startupPositionSource,
            progressCoordinator = progressCoordinator,
            initialPreferences = runCatching { preferencesStore?.load() }.getOrNull()
                ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
            persistPreferences = { preferences -> preferencesStore?.save(preferences) },
            bookmarkStore = bookmarkStore,
            bookmarkSyncPort = bookmarkSyncPort,
            bookmarkSyncTarget = bookmarkSyncTarget,
            externalLinkHandler = ::openExternalLink,
            onUnhandledTap = ::routeReaderTap,
            presentationNamespaceKey = namespaceKey,
            publishProgressUpdate = (application as ErmaoLibraryApplication)
                .readerProgressPresentationCenter::publish,
        )
    }

    private fun createLocalOnlyProgressStore(source: ReaderSource): ReaderPositionSyncingStore {
        val namespace = ReaderSyncNamespace(LOCAL_READER_SERVER, LOCAL_READER_USER, 0)
        val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
        return AndroidReaderV5LocalStore(
            AndroidReaderV5Database(
                applicationContext,
                ReaderLocalProgressIdentity(
                    namespace = namespace,
                    clientId = clientId,
                    bookId = source.bookId ?: "local-${source.resourceId}",
                    resourceId = source.resourceId,
                ),
            ),
        )
    }

    private fun ReaderSyncNamespace.presentationKey(): String =
        "$serverIdentity|$userId|$authorizationVersion"

    private fun com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace.presentationKey(): String =
        "$serverIdentity|$userId|$authorizationVersion"

    private fun openExternalLink(rawUrl: String) {
        val uri = rawUrl.toUri()
        if (uri.scheme?.lowercase() !in setOf("https", "http")) return
        val externalIntent = Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)
        try {
            startActivity(externalIntent)
        } catch (_: ActivityNotFoundException) {
            LOGGER.log(Level.WARNING, "reader_external_link_unhandled scheme={0}", uri.scheme)
        }
    }

    private fun attachNavigatorIfReady() {
        if (!isLaunchCurrent()) return
        val prepared = navigatorAttachment.claim(session, supportFragmentManager.isStateSaved) ?: return
        supportFragmentManager.commitNow {
            replace(READER_NAVIGATOR_CONTAINER_ID, prepared.navigator, NAVIGATOR_FRAGMENT_TAG)
        }
        prepared.session.bind(lifecycleScope)
        navigatorAttachment.markBound(prepared)
        controller = prepared.session
        opening = false
        downloadTransition = null
        lifecycleScope.launch { recoverPendingProgressAndCheckRemote() }
    }

    private fun closeReader() {
        if (closing) return
        closing = true
        cancelLaunchDownload()
        lifecycleScope.launch {
            openJob?.cancel()
            try {
                runCatching { session?.close() }
                runCatching { retryPendingUploadWithinLifecycleBudget() }
            } finally {
                finish()
            }
        }
    }

    companion object {
        private val LOGGER = Logger.getLogger("MobileReader")
        private const val NAVIGATOR_FRAGMENT_TAG = "reader-epub-navigator"
        private const val EXTRA_RESOURCE_ID = "reader.resource-id"
        private const val EXTRA_TITLE = "reader.title"
        private const val EXTRA_SOURCE_FORMAT = "reader.source-format"
        private const val EXTRA_BOOK_ID = "reader.book-id"
        private const val EXTRA_ASSET_ID = "reader.asset-id"
        private const val EXTRA_SERVER_PROFILE_ID = "reader.server-profile-id"
        private const val EXTRA_SERVER_RESOURCE_ID = "reader.server-resource-id"
        private const val EXTRA_MANAGED_LOCAL_REFERENCE = "reader.managed-local-reference"
        private const val EXTRA_COMIC_PAGE_HREFS = "reader.comic-page-hrefs"
        private const val EXTRA_COMIC_PAGE_MEDIA_TYPES = "reader.comic-page-media-types"
        private const val EXTRA_PDF_PAGE_TITLES = "reader.pdf-page-titles"
        private const val EXTRA_PAGE_COUNT = "reader.page-count"
        private const val LOCAL_READER_SERVER = "local-reader"
        private const val LOCAL_READER_USER = "local-user"
        private const val SYNC_FLUSH_TIMEOUT_MILLIS = 2_500L

        fun createIntent(
            context: Context,
            source: LocalReaderSource,
            comicPages: List<ReaderComicPage> = emptyList(),
            pdfPages: List<ReaderPdfPage> = emptyList(),
            pageCount: Int? = null,
        ): Intent {
            require(source.format in setOf(ReaderFormat.Epub, ReaderFormat.Mobi, ReaderFormat.Text, ReaderFormat.Comic, ReaderFormat.Pdf)) {
                "Reader accepts only supported local sources"
            }
            require(source.format == ReaderFormat.Comic || comicPages.isEmpty())
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_RESOURCE_ID, source.resourceId)
                .putExtra(EXTRA_TITLE, source.displayTitle)
                .putExtra(EXTRA_SOURCE_FORMAT, source.sourceFormat?.wireValue ?: source.format.wireValue)
                .putExtra(EXTRA_BOOK_ID, source.bookId)
                .putExtra(EXTRA_ASSET_ID, source.assetId)
                .putStringArrayListExtra(
                    EXTRA_COMIC_PAGE_HREFS,
                    ArrayList(comicPages.map(ReaderComicPage::resourceHref)),
                )
                .putStringArrayListExtra(
                    EXTRA_COMIC_PAGE_MEDIA_TYPES,
                    ArrayList(comicPages.map(ReaderComicPage::mediaType)),
                )
                .putStringArrayListExtra(
                    EXTRA_PDF_PAGE_TITLES,
                    ArrayList(pdfPages.map(ReaderPdfPage::title)),
                )
                .putExtra(EXTRA_PAGE_COUNT, pageCount ?: -1)
        }

        fun createServerIntent(context: Context, profileId: String, resourceId: String, initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null): Intent {
            require(profileId.isNotBlank() && resourceId.isNotBlank())
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SERVER_PROFILE_ID, profileId)
                .putExtra(EXTRA_SERVER_RESOURCE_ID, resourceId)
                .putExtra("reader.initialTarget", initialTarget?.let { com.ermao.library.shared.modules.reader.encodeReaderLaunchTarget(it) })
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        fun createManagedDownloadIntent(
            context: Context,
            profileId: String,
            bookId: String,
            resourceId: String,
            assetId: String = resourceId,
            displayTitle: String,
            localReference: String,
            sourceFormat: String,
        ): Intent {
            require(
                profileId.isNotBlank() && bookId.isNotBlank() && resourceId.isNotBlank() && assetId.isNotBlank() &&
                    displayTitle.isNotBlank() && localReference.isNotBlank() &&
                    sourceFormat.isSupportedManagedSourceFormat(),
            )
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SERVER_PROFILE_ID, profileId)
                .putExtra(EXTRA_BOOK_ID, bookId)
                .putExtra(EXTRA_SERVER_RESOURCE_ID, resourceId)
                .putExtra(EXTRA_ASSET_ID, assetId)
                .putExtra(EXTRA_TITLE, displayTitle)
                .putExtra(EXTRA_MANAGED_LOCAL_REFERENCE, localReference)
                .putExtra(EXTRA_SOURCE_FORMAT, sourceFormat.trim().lowercase())
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        private fun Intent.readerSourceOrNull(): LocalReaderSource? {
            val resourceId = getStringExtra(EXTRA_RESOURCE_ID) ?: return null
            val sourceFormatValue = getStringExtra(EXTRA_SOURCE_FORMAT)
            val sourceFormat = if (sourceFormatValue == null) {
                ReaderSourceFormat.Epub
            } else {
                ReaderSourceFormat.fromWireValue(sourceFormatValue) ?: return null
            }
            val format = sourceFormat.readerFormat
            return LocalReaderSource(
                resourceId = resourceId,
                displayTitle = checkNotNull(getStringExtra(EXTRA_TITLE)),
                format = format,
                bookId = getStringExtra(EXTRA_BOOK_ID),
                assetId = getStringExtra(EXTRA_ASSET_ID),
                sourceFormat = sourceFormat,
            )
        }

        private fun Intent.comicPagesOrEmpty(): List<ReaderComicPage> {
            val hrefs = getStringArrayListExtra(EXTRA_COMIC_PAGE_HREFS).orEmpty()
            val mediaTypes = getStringArrayListExtra(EXTRA_COMIC_PAGE_MEDIA_TYPES).orEmpty()
            check(hrefs.size == mediaTypes.size) { "Comic launch page index is inconsistent" }
            return hrefs.indices.map { index ->
                ReaderComicPage(index, hrefs[index], mediaTypes[index])
            }
        }

        private fun Intent.pdfPagesOrEmpty(): List<ReaderPdfPage> =
            getStringArrayListExtra(EXTRA_PDF_PAGE_TITLES).orEmpty().mapIndexed { index, title ->
                ReaderPdfPage(index, title)
            }

        private fun Intent.serverReaderRequestOrNull(): ServerReaderRequest? {
            val profileId = getStringExtra(EXTRA_SERVER_PROFILE_ID) ?: return null
            val resourceId = getStringExtra(EXTRA_SERVER_RESOURCE_ID) ?: return null
            return ServerReaderRequest(profileId, resourceId, com.ermao.library.shared.modules.reader.decodeReaderLaunchTarget(getStringExtra("reader.initialTarget")))
        }


        private fun Intent.managedDownloadRequestOrNull(): ManagedDownloadReaderRequest? {
            val localReference = getStringExtra(EXTRA_MANAGED_LOCAL_REFERENCE) ?: return null
            return ManagedDownloadReaderRequest(
                profileId = checkNotNull(getStringExtra(EXTRA_SERVER_PROFILE_ID)),
                bookId = checkNotNull(getStringExtra(EXTRA_BOOK_ID)),
                resourceId = checkNotNull(getStringExtra(EXTRA_SERVER_RESOURCE_ID)),
                assetId = checkNotNull(getStringExtra(EXTRA_ASSET_ID)),
                displayTitle = checkNotNull(getStringExtra(EXTRA_TITLE)),
                localReference = localReference,
                sourceFormat = checkNotNull(getStringExtra(EXTRA_SOURCE_FORMAT))
                    .also { check(it.isSupportedManagedSourceFormat()) },
            )
        }
    }

    private data class ServerReaderRequest(val profileId: String, val resourceId: String, val initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null)
    private data class ManagedDownloadReaderRequest(
        val profileId: String,
        val bookId: String,
        val resourceId: String,
        val assetId: String,
        val displayTitle: String,
        val localReference: String,
        val sourceFormat: String,
        val initialTarget: com.ermao.library.shared.modules.reader.ReaderNavigationTarget? = null,
    )
    private data class ActiveReaderSession(
        val profile: com.ermao.library.shared.modules.servers.domain.ServerProfile,
        val identity: com.ermao.library.shared.modules.auth.domain.SessionIdentity,
        val authenticated: AppSession.Authenticated?,
    )
}


private fun String.isSupportedManagedSourceFormat(): Boolean =
    trim().uppercase() in setOf(
        "EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT", "FB2",
        "CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR", "PDF",
    )

private fun readerProgressEtag(revision: Long): String = "\"reader-v5-progress-$revision\""

private object NonBlockingReaderPositionStore : ReaderPositionSyncingStore {
    override suspend fun load(resourceId: String): com.ermao.library.shared.modules.reader.ReaderPositionLocalState? = null
    override suspend fun save(position: com.ermao.library.shared.modules.reader.ReaderPositionLocalState) = Unit
    override suspend fun delete(resourceId: String) = Unit
    override suspend fun awaitPendingUpload() = Unit
    override suspend fun retryPendingUpload() = Unit
    override suspend fun syncState() = com.ermao.library.shared.modules.reader.ReaderPositionDurableState()
}
