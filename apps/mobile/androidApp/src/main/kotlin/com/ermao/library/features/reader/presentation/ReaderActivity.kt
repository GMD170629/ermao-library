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
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.fragment.app.Fragment
import androidx.fragment.app.commitNow
import androidx.core.net.toUri
import androidx.lifecycle.lifecycleScope
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressDatabase
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPreferencesStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderBookmarkStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderCapabilities
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigatorSession
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigationCache
import com.ermao.library.features.reader.infrastructure.AndroidReadiumRuntime
import com.ermao.library.features.reader.infrastructure.ReaderOpenFailure
import com.ermao.library.features.reader.infrastructure.ReadiumReflowableSession
import com.ermao.library.features.reader.infrastructure.ReadiumComicSession
import com.ermao.library.features.reader.infrastructure.ReadiumPdfSession
import com.ermao.library.features.reader.infrastructure.AndroidPdfiumFeatureFlags
import com.ermao.library.features.reader.infrastructure.AndroidPdfRangeCache
import com.ermao.library.features.reader.infrastructure.AndroidRemotePdfiumSessionConfiguration
import com.ermao.library.features.reader.infrastructure.ReadiumLocatorMapper
import com.ermao.library.features.reader.infrastructure.ReadiumPreferencesMapper
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
import com.ermao.library.shared.modules.reader.LocalFirstReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.ReaderNavigationUnit
import com.ermao.library.shared.modules.reader.ReaderBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderBootstrapFailure
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.ReaderPdfPage
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore
import com.ermao.library.shared.modules.reader.ReaderProgressQueryPort
import com.ermao.library.shared.modules.reader.application.ReaderProgressQueryResult as ProgressQueryResult
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.decidePendingVsServerStartup
import com.ermao.library.shared.modules.reader.application.PendingVsServerDecision
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.ReaderTapZones
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapFailure
import com.ermao.library.shared.modules.reader.application.PublicationDownloadResult.Content as PublicationDownloadContent
import com.ermao.library.shared.modules.reader.application.PublicationDownloadResult.Failure as PublicationDownloadFailure
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.shared.createAndroidReaderProgressSyncPort
import com.ermao.library.shared.createAndroidReaderBookmarkSyncPort
import com.ermao.library.shared.createAndroidReaderServerGateway
import com.ermao.library.shared.createAndroidPdfRangeServerPort
import com.ermao.library.shared.createAndroidComicPageServerPort
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.downloads.toDownloadNamespace
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.image.ImageNavigatorFragment
import org.readium.adapter.pdfium.navigator.PdfiumEngineProvider
import org.readium.adapter.pdfium.navigator.PdfiumNavigatorFragment
import androidx.fragment.app.FragmentFactory
import org.readium.r2.shared.ExperimentalReadiumApi
import java.util.logging.Level
import java.util.logging.Logger
import java.io.File

@OptIn(ExperimentalReadiumApi::class)
class ReaderActivity : AppCompatActivity() {
    private var controller by mutableStateOf<ReaderScreenController?>(null)
    private var opening by mutableStateOf(true)
    private var openError by mutableStateOf<ReaderError?>(null)
    private var readerTitle by mutableStateOf("")
    private var controlsVisible by mutableStateOf(false)
    private var touchDownX = 0f
    private var touchDownY = 0f
    private var touchDownAt = 0L

    private var session: AndroidReaderNavigatorSession? = null
    private var pendingNavigator: Fragment? = null
    private var containerReady = false
    private var navigatorBound = false
    private var closing = false
    private var openJob: Job? = null
    private var pendingManagedRepair: PendingManagedRepair? = null
    private val navigationCache by lazy { AndroidReaderNavigationCache(applicationContext) }
    private var syncingProgressStore: ReaderProgressSyncingStore? = null
    private var progressCoordinator: ReaderProgressSyncCoordinator? = null
    private var progressQueryPort: ReaderProgressQueryPort? = null
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
        supportFragmentManager.fragmentFactory = readerNavigatorDummyFactory()
        super.onCreate(savedInstanceState)
        removeRestoredNavigator()
        networkAvailable = getSystemService(ConnectivityManager::class.java).activeNetwork != null

        val source = runCatching { intent.readerSourceOrNull() }.getOrNull()
        val managedRequest = runCatching { intent.managedDownloadRequestOrNull() }.getOrNull()
        val serverRequest = runCatching { intent.serverReaderRequestOrNull() }.getOrNull()
        if (source != null) {
            readerTitle = source.displayTitle
            session = createSession(
                source,
                AndroidReaderProgressStore(applicationContext),
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
                } catch (_: RuntimeException) {
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
                } catch (_: RuntimeException) {
                    showOpenError(ReaderErrorCode.ReaderEngineError)
                }
            }
        } else {
            opening = false
            openError = ReaderError(ReaderErrorCode.ResourceMissing)
            readerTitle = getString(com.ermao.library.R.string.app_name)
        }

        onBackPressedDispatcher.addCallback(this) { closeReader() }
        setContent {
            ReaderScreen(
                title = readerTitle,
                controller = controller,
                opening = opening,
                openError = openError,
                controlsVisible = controlsVisible,
                onControlsVisibleChange = { controlsVisible = it },
                onClose = ::closeReader,
                onRetryOpen = when {
                    managedRequest != null -> { { retryManagedDownload(managedRequest) } }
                    serverRequest != null -> { { retryServerReader(serverRequest) } }
                    else -> null
                },
                onReadOnline = managedRequest?.takeIf { networkAvailable }?.let { request ->
                    {
                        startActivity(createServerIntent(this, request.profileId, request.resourceId))
                        finish()
                    }
                },
                onDeleteDownload = managedRequest?.let { request ->
                    {
                        lifecycleScope.launch { deleteManagedDownloadAndClose(request) }
                    }
                },
                onNavigatorContainerReady = {
                    containerReady = true
                    attachNavigatorIfReady()
                },
            )
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

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
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
            KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_PAGE_UP ->
                interaction.keyboardPageTurn && reader.goPrevious()
            KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_PAGE_DOWN, KeyEvent.KEYCODE_SPACE ->
                interaction.keyboardPageTurn && reader.goNext()
            KeyEvent.KEYCODE_VOLUME_UP -> interaction.volumeKeyPageTurn && reader.goPrevious()
            KeyEvent.KEYCODE_VOLUME_DOWN -> interaction.volumeKeyPageTurn && reader.goNext()
            else -> false
        }
        return if (handled) true else super.dispatchKeyEvent(event)
    }

    private fun routeReaderTap(horizontalFraction: Float) {
        val reader = controller ?: return
        when (reader.preferences.value.interaction.tapZones) {
            ReaderTapZones.Disabled -> controlsVisible = true
            ReaderTapZones.Standard -> when {
                horizontalFraction < 0.33f -> reader.goPrevious()
                horizontalFraction > 0.67f -> reader.goNext()
                else -> controlsVisible = true
            }
            ReaderTapZones.Reversed -> when {
                horizontalFraction < 0.33f -> reader.goNext()
                horizontalFraction > 0.67f -> reader.goPrevious()
                else -> controlsVisible = true
            }
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
            is ProgressQueryResult.Current -> {
                progressEtag = result.etag ?: progressEtag
                val snapshot = result.snapshot ?: return
                coordinator.observeRemoteProgress(
                    snapshot,
                    clientId,
                    syncingProgressStore?.load(target.resourceId),
                )
            }
            is ProgressQueryResult.Unchanged -> progressEtag = result.etag ?: progressEtag
            is ProgressQueryResult.Failure -> Unit
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
        openJob?.cancel()
        lifecycleScope.launch { progressCoordinator?.cancelWorker() }
        session?.release()
        session = null
        super.onDestroy()
    }

    private suspend fun openServerReader(
        request: ServerReaderRequest,
        forceCompletePdfDownload: Boolean = false,
    ) {
        val runtime = (application as ErmaoLibraryApplication).mobileRuntime
        if (runtime.currentSession !is AppSession.Authenticated) runtime.start()
        val authenticated = runtime.currentSession as? AppSession.Authenticated
        if (authenticated == null || authenticated.profile.id != request.profileId) {
            showOpenError(ReaderErrorCode.ResourceMissing)
            return
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
        val serverGateway = createAndroidReaderServerGateway(applicationContext)
        val publicationStore = AndroidReaderPublicationStore(applicationContext, namespace)
        val bootstrapper = BootstrapReaderPublication(
            bootstrapGateway = serverGateway,
            downloadPort = serverGateway,
            sinkFactory = publicationStore.downloadSinkFactory(),
            localSourceResolver = publicationStore.localSourceResolver(),
            nativePdfiumRangeV1 = AndroidPdfiumFeatureFlags.NATIVE_PDFIUM_RANGE_V1 &&
                !forceCompletePdfDownload,
        )
        when (val result = bootstrapper.execute(
            ReaderBootstrapRequest(authenticated.profile, namespace, request.resourceId),
        )) {
            is ReaderPublicationBootstrapFailure -> showOpenError(
                if (result.recoverable) ReaderErrorCode.NetworkUnavailable else ReaderErrorCode.ResourceMissing,
            )
            is ReaderPublicationBootstrapContent -> {
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
                var sessionProgressStore: ReaderProgressStore = NonBlockingReaderProgressStore
                var startupRemoteSnapshot = result.bootstrap.remoteSnapshot
                var sessionCoordinator: ReaderProgressSyncCoordinator? = null
                try {
                    val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
                    val database = AndroidReaderProgressDatabase(
                        applicationContext,
                        ReaderLocalProgressIdentity(
                            namespace = namespace,
                            clientId = clientId,
                            bookId = result.bootstrap.target.bookId,
                            resourceId = source.resourceId,
                        ),
                    )
                    val startupDecision = decidePendingVsServerStartup(
                        database.load(source.resourceId),
                        database.loadSyncState(),
                        result.bootstrap.remoteSnapshot,
                        source,
                    )
                    val progressServer = createAndroidReaderProgressSyncPort(
                        applicationContext,
                        authenticated.profile,
                    )
                    val coordinator = ReaderProgressSyncCoordinator(database, progressServer, lifecycleScope)
                    val syncingStore = LocalFirstReaderProgressStore(
                        database,
                        result.bootstrap.target,
                        coordinator,
                    )
                    progressCoordinator = coordinator
                    sessionCoordinator = coordinator
                    coordinator.beginSession(result.bootstrap.remoteSnapshot)
                    progressQueryPort = progressServer
                    progressSyncTarget = result.bootstrap.target
                    progressClientId = clientId
                    progressEtag = result.bootstrap.remoteSnapshot?.revision?.let { "\"reader-progress-$it\"" }
                        ?: "\"reader-progress-0\""
                    when (startupDecision) {
                        is PendingVsServerDecision.UseServer -> if (startupDecision.discardPending) {
                            database.loadSyncState().pending?.let {
                                coordinator.discardStartupPending(
                                    it.mutationId,
                                    startupDecision.snapshot?.revision ?: 0,
                                )
                            }
                        }
                        is PendingVsServerDecision.UseLocalPending -> {
                            startupRemoteSnapshot = null
                            coordinator.retryPending(result.bootstrap.target)
                        }
                    }
                    syncingProgressStore = syncingStore
                    sessionProgressStore = syncingStore
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
                } catch (failure: Exception) {
                    LOGGER.log(Level.WARNING, "reader_progress_startup_ignored", failure)
                    clearProgressRuntime()
                    startupRemoteSnapshot = null
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
                    navigationUnits = result.bootstrap.units,
                    comicPages = result.bootstrap.comicPages,
                    pdfPages = result.bootstrap.pdfPages,
                    pageCount = result.bootstrap.pageCount,
                    namespace = namespace,
                    comicPageServer = (source as? RemoteComicReaderSource)?.let {
                        createAndroidComicPageServerPort(applicationContext, authenticated.profile)
                    },
                    remotePdfium = (source as? RemoteByteRangeReaderSource)?.let {
                        val rangeCache = AndroidPdfRangeCache(File(cacheDir, "reader/pdf-range-v3"))
                        rangeCache.activateNamespace(it.namespace)
                        AndroidRemotePdfiumSessionConfiguration(
                            scope = lifecycleScope,
                            cache = rangeCache,
                            server = createAndroidPdfRangeServerPort(applicationContext, authenticated.profile),
                        )
                    },
                )
                val prepared = prepareSession(checkNotNull(session))
                if (!prepared && source is RemoteByteRangeReaderSource && !forceCompletePdfDownload) {
                    clearProgressRuntime()
                    session = null
                    openError = null
                    opening = true
                    openServerReader(request, forceCompletePdfDownload = true)
                }
            }
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
        val readerNamespace = activeSession.identity.namespace
        val preferencesStore = AndroidReaderPreferencesStore(
            applicationContext,
            readerNamespace.serverIdentity,
            readerNamespace.userId,
        )
        val localFile = application.downloadFiles.resolveLocalReference(request.localReference)
        if (localFile == null || !localFile.isFile) {
            showOpenError(ReaderErrorCode.ResourceMissing)
            return
        }
        val publicationStore = AndroidReaderPublicationStore(
            applicationContext,
            ReaderSyncNamespace(
                readerNamespace.serverIdentity,
                readerNamespace.userId,
                readerNamespace.authorizationVersion,
            ),
        )
        val exactSourceFormat = ReaderSourceFormat.fromWireValue(request.sourceFormat)
        if (exactSourceFormat == null) {
            showOpenError(ReaderErrorCode.UnsupportedFormat)
            return
        }
        val source = localFile.inputStream().use { input ->
            publicationStore.publishLocalPublication(
                resourceId = request.resourceId,
                displayTitle = request.displayTitle,
                input = input,
                sourceFormat = exactSourceFormat,
                bookId = request.bookId,
                assetId = request.assetId,
            )
        }
        val authenticated = activeSession.authenticated
        var progressStore: ReaderProgressStore = NonBlockingReaderProgressStore
        var bookmarkSyncPort: ReaderBookmarkSyncPort? = null
        var remoteSnapshot: com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4? = null
        val cachedNavigation = navigationCache.load(
            ReaderSyncNamespace(
                readerNamespace.serverIdentity,
                readerNamespace.userId,
                readerNamespace.authorizationVersion,
            ),
            request.resourceId,
        )
        var comicPages: List<ReaderComicPage> = cachedNavigation?.comicPages.orEmpty()
        var pdfPages: List<ReaderPdfPage> = cachedNavigation?.pdfPages.orEmpty()
        var navigationUnits: List<ReaderNavigationUnit> = cachedNavigation?.units.orEmpty()
        var pageCount: Int? = cachedNavigation?.pageCount
        if (authenticated != null) {
            val namespace = ReaderSyncNamespace(
                activeSession.identity.namespace.serverIdentity,
                activeSession.identity.namespace.userId,
                activeSession.identity.namespace.authorizationVersion,
            )
            when (val bootstrap = createAndroidReaderServerGateway(applicationContext).load(
                ReaderBootstrapRequest(activeSession.profile, namespace, request.resourceId),
            )) {
                is ReaderBootstrapContent -> {
                    navigationCache.save(
                        namespace,
                        request.resourceId,
                        bootstrap.value,
                    )
                    comicPages = bootstrap.value.comicPages
                    pdfPages = bootstrap.value.pdfPages
                    navigationUnits = bootstrap.value.units
                    pageCount = bootstrap.value.pageCount
                    bookmarkSyncPort = createAndroidReaderBookmarkSyncPort(applicationContext, activeSession.profile)
                    try {
                        val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
                        val database = AndroidReaderProgressDatabase(
                            applicationContext,
                            ReaderLocalProgressIdentity(
                                namespace,
                                clientId,
                                bootstrap.value.target.bookId,
                                source.resourceId,
                            ),
                        )
                        val startupDecision = decidePendingVsServerStartup(
                            database.load(source.resourceId),
                            database.loadSyncState(),
                            bootstrap.value.remoteSnapshot,
                            source,
                        )
                        val progressServer = createAndroidReaderProgressSyncPort(
                            applicationContext,
                            activeSession.profile,
                        )
                        val coordinator = ReaderProgressSyncCoordinator(
                            stateStore = database,
                            server = progressServer,
                            scope = lifecycleScope,
                        )
                        val syncingStore = LocalFirstReaderProgressStore(
                            database,
                            bootstrap.value.target,
                            coordinator,
                        )
                        progressCoordinator = coordinator
                        coordinator.beginSession(bootstrap.value.remoteSnapshot)
                        progressQueryPort = progressServer
                        progressSyncTarget = bootstrap.value.target
                        progressClientId = clientId
                        progressEtag = bootstrap.value.remoteSnapshot?.revision?.let { "\"reader-progress-$it\"" }
                            ?: "\"reader-progress-0\""
                        when (startupDecision) {
                            is PendingVsServerDecision.UseServer -> if (startupDecision.discardPending) {
                                database.loadSyncState().pending?.let {
                                    coordinator.discardStartupPending(
                                        it.mutationId,
                                        startupDecision.snapshot?.revision ?: 0,
                                    )
                                }
                            }
                            is PendingVsServerDecision.UseLocalPending -> {
                                remoteSnapshot = null
                                coordinator.retryPending(bootstrap.value.target)
                            }
                        }
                        syncingProgressStore = syncingStore
                        progressStore = syncingStore
                        if (startupDecision !is PendingVsServerDecision.UseLocalPending) {
                            remoteSnapshot = bootstrap.value.remoteSnapshot
                        }
                    } catch (cancelled: kotlinx.coroutines.CancellationException) {
                        throw cancelled
                    } catch (failure: Exception) {
                        LOGGER.log(Level.WARNING, "reader_progress_startup_ignored", failure)
                        clearProgressRuntime()
                        remoteSnapshot = null
                    }
                }
                is ReaderBootstrapFailure -> {
                    progressStore = createBestEffortManagedProgressStore(
                        activeSession,
                        request,
                        source,
                        exactSourceFormat,
                    )
                }
            }
        } else {
            progressStore = createBestEffortManagedProgressStore(
                activeSession,
                request,
                source,
                exactSourceFormat,
            )
        }
        readerTitle = source.displayTitle
        session = createSession(
            source,
            progressStore,
            remoteSnapshot,
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
            bookmarkSyncPort,
            ReaderBookmarkSyncTarget(
                readerNamespace.serverIdentity,
                source.resourceId,
            ),
            namespaceKey = readerNamespace.presentationKey(),
            navigationUnits = navigationUnits,
            comicPages = comicPages,
            pdfPages = pdfPages,
            pageCount = pageCount,
            namespace = ReaderSyncNamespace(
                readerNamespace.serverIdentity,
                readerNamespace.userId,
                readerNamespace.authorizationVersion,
            ),
        )
        prepareSession(checkNotNull(session))
    }

    private fun retryManagedDownload(request: ManagedDownloadReaderRequest) {
        if (openJob?.isActive == true) return
        openError = null
        opening = true
        controller = null
        pendingNavigator = null
        navigatorBound = false
        session?.release()
        session = null
        openJob = lifecycleScope.launch {
            try {
                val runtime = (application as ErmaoLibraryApplication).mobileRuntime
                if (runtime.currentSession !is AppSession.Authenticated) runtime.start()
                val authenticated = runtime.currentSession as? AppSession.Authenticated
                    ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.NetworkUnavailable))
                if (authenticated.profile.id != request.profileId) {
                    throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ResourceMissing))
                }
                val privateNamespace = authenticated.identity.namespace
                val namespace = ReaderSyncNamespace(
                    privateNamespace.serverIdentity,
                    privateNamespace.userId,
                    privateNamespace.authorizationVersion,
                )
                val gateway = createAndroidReaderServerGateway(applicationContext)
                val bootstrap = when (val result = gateway.load(
                    ReaderBootstrapRequest(authenticated.profile, namespace, request.resourceId),
                )) {
                    is ReaderBootstrapContent -> result.value
                    is ReaderBootstrapFailure -> throw ReaderOpenFailure(
                        ReaderError(
                            if (result.recoverable) ReaderErrorCode.NetworkUnavailable
                            else ReaderErrorCode.ResourceMissing,
                        ),
                    )
                }
                val publicationStore = AndroidReaderPublicationStore(applicationContext, namespace)
                val refreshed = when (val result = gateway.download(
                    bootstrap.publication,
                    publicationStore.downloadSinkFactory(),
                )) {
                    is PublicationDownloadContent -> result.source as? LocalReaderSource
                        ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.ReaderEngineError))
                    is PublicationDownloadFailure -> throw ReaderOpenFailure(
                        ReaderError(
                            if (result.recoverable) ReaderErrorCode.NetworkUnavailable
                            else ReaderErrorCode.ParseFailed,
                        ),
                    )
                }
                if (refreshed.sourceFormat?.wireValue.equals(request.sourceFormat, ignoreCase = true)) {
                    pendingManagedRepair = PendingManagedRepair(
                        localReference = request.localReference,
                        parsedSource = publicationStore.resolve(refreshed),
                    )
                }
                openServerReader(ServerReaderRequest(request.profileId, request.resourceId))
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (failure: ReaderOpenFailure) {
                pendingManagedRepair = null
                showOpenError(failure.readerError.code)
            } catch (failure: Exception) {
                pendingManagedRepair = null
                LOGGER.log(Level.WARNING, "reader_managed_repair_failed", failure)
                showOpenError(ReaderErrorCode.ReaderEngineError)
            }
        }
    }

    private fun retryServerReader(request: ServerReaderRequest) {
        if (openJob?.isActive == true) return
        openError = null
        opening = true
        controller = null
        pendingNavigator = null
        navigatorBound = false
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

    private suspend fun deleteManagedDownloadAndClose(request: ManagedDownloadReaderRequest) {
        val runtime = (application as ErmaoLibraryApplication).mobileRuntime
        val namespace = when (val current = runtime.currentSession) {
            is AppSession.Authenticated -> current.identity.namespace
            else -> return
        }
        (application as ErmaoLibraryApplication).sharedDownloadCatalog.deleteArtifact(
            namespace.toDownloadNamespace(),
            com.ermao.library.shared.modules.downloads.DownloadIdentity(
                namespace = namespace.toDownloadNamespace(),
                bookId = request.bookId,
                resourceId = request.resourceId,
                assetId = request.assetId,
            ),
        )
        closeReader()
    }

    private suspend fun createOfflineManagedProgressStore(
        activeSession: ActiveReaderSession,
        request: ManagedDownloadReaderRequest,
        source: LocalReaderSource,
        sourceFormat: ReaderSourceFormat,
    ): ReaderProgressStore {
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
        val database = AndroidReaderProgressDatabase(
            applicationContext,
            ReaderLocalProgressIdentity(namespace, clientId, request.bookId, source.resourceId),
        )
        val progressServer = createAndroidReaderProgressSyncPort(applicationContext, activeSession.profile)
        val coordinator = ReaderProgressSyncCoordinator(database, progressServer, lifecycleScope)
        val syncingStore = LocalFirstReaderProgressStore(database, target, coordinator)
        val durableState = database.loadSyncState()
        val startupDecision = decidePendingVsServerStartup(
            database.load(source.resourceId),
            durableState,
            remoteSnapshot = null,
            openedSource = source,
        )

        coordinator.beginSession(snapshot = null)
        progressCoordinator = coordinator
        progressQueryPort = progressServer
        progressSyncTarget = target
        progressClientId = clientId
        progressEtag = "\"reader-progress-${durableState.confirmedRevision}\""
        syncingProgressStore = syncingStore

        when (startupDecision) {
            is PendingVsServerDecision.UseServer -> if (startupDecision.discardPending) {
                durableState.pending?.let { pending ->
                    coordinator.discardStartupPending(
                        pending.mutationId,
                        startupDecision.snapshot?.revision ?: durableState.confirmedRevision,
                    )
                }
            }
            is PendingVsServerDecision.UseLocalPending -> coordinator.retryPending(target)
        }
        return syncingStore
    }

    private suspend fun createBestEffortManagedProgressStore(
        activeSession: ActiveReaderSession,
        request: ManagedDownloadReaderRequest,
        source: LocalReaderSource,
        sourceFormat: ReaderSourceFormat,
    ): ReaderProgressStore = try {
        createOfflineManagedProgressStore(activeSession, request, source, sourceFormat)
    } catch (cancelled: kotlinx.coroutines.CancellationException) {
        throw cancelled
    } catch (failure: Exception) {
        LOGGER.log(Level.WARNING, "reader_progress_store_unavailable", failure)
        clearProgressRuntime()
        NonBlockingReaderProgressStore
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
            pendingNavigator = readerSession.prepare(classLoader)
            attachNavigatorIfReady()
            return true
        } catch (failure: ReaderOpenFailure) {
            readerSession.release()
            pendingManagedRepair = null
            opening = false
            openError = failure.readerError
            LOGGER.log(Level.SEVERE, "reader_open_failed code={0}", failure.readerError.code.wireValue)
            return false
        } catch (_: RuntimeException) {
            readerSession.release()
            pendingManagedRepair = null
            showOpenError(ReaderErrorCode.ReaderEngineError)
            return false
        }
    }

    private fun showOpenError(code: ReaderErrorCode) {
        opening = false
        openError = ReaderError(code)
        LOGGER.log(Level.SEVERE, "reader_open_failed code={0}", code.wireValue)
    }

    private suspend fun retryPendingUploadWithinLifecycleBudget() {
        withTimeoutOrNull(SYNC_FLUSH_TIMEOUT_MILLIS) {
            syncingProgressStore?.retryPendingUpload()
            syncingProgressStore?.awaitPendingUpload()
        }
    }

    private fun createSession(
        source: ReaderSource,
        progressStore: ReaderProgressStore,
        remoteSnapshot: com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4? = null,
        progressCoordinator: ReaderProgressSyncCoordinator? = null,
        preferencesStore: AndroidReaderPreferencesStore? = null,
        bookmarkStore: AndroidReaderBookmarkStore? = null,
        bookmarkSyncPort: ReaderBookmarkSyncPort? = null,
        bookmarkSyncTarget: ReaderBookmarkSyncTarget? = null,
        namespaceKey: String? = null,
        navigationUnits: List<ReaderNavigationUnit> = emptyList(),
        comicPages: List<ReaderComicPage> = emptyList(),
        pdfPages: List<ReaderPdfPage> = emptyList(),
        pageCount: Int? = null,
        comicPageServer: ComicPageServerPort? = null,
        remotePdfium: AndroidRemotePdfiumSessionConfiguration? = null,
        namespace: ReaderSyncNamespace? = null,
    ): AndroidReaderNavigatorSession {
        val sourceFormat = requireNotNull(source.sourceFormat) { "Reader source format is missing" }
        if (!sourceFormat.isComic) {
            try {
                AndroidReaderCapabilities.registry.requireOpenable(sourceFormat)
            } catch (error: IllegalArgumentException) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat), cause = error)
            }
        }
        if (sourceFormat.isComic) {
            val publicationStore = AndroidReaderPublicationStore(applicationContext, namespace)
            val readium = AndroidReadiumRuntime(applicationContext)
            val sessionPages = if (source is LocalReaderSource) {
                val file = publicationStore.resolve(source)
                com.ermao.library.features.reader.infrastructure.CbzReadiumPublicationFactory(
                    readium.assetRetriever,
                ).indexPages(file, comicPages)
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
                progressStore = progressStore,
                deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
                readium = readium,
                comicPageServer = comicPageServer,
                remoteSnapshot = remoteSnapshot,
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
                publicationStore = AndroidReaderPublicationStore(applicationContext, namespace),
                progressStore = progressStore,
                deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
                readium = AndroidReadiumRuntime(applicationContext),
                remotePdfium = remotePdfium,
                remoteSnapshot = remoteSnapshot,
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
        return ReadiumReflowableSession(
            source = localSource,
            canonicalUnits = navigationUnits,
            publicationStore = AndroidReaderPublicationStore(applicationContext, namespace),
            progressStore = progressStore,
            deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
            readium = AndroidReadiumRuntime(applicationContext),
            locatorMapper = ReadiumLocatorMapper(),
            preferencesMapper = ReadiumPreferencesMapper(resources),
            remoteSnapshot = remoteSnapshot,
            progressCoordinator = progressCoordinator,
            initialPreferences = runCatching { preferencesStore?.load() }.getOrNull()
                ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
            persistPreferences = { preferences -> preferencesStore?.save(preferences) },
            bookmarkStore = bookmarkStore,
            bookmarkSyncPort = bookmarkSyncPort,
            bookmarkSyncTarget = bookmarkSyncTarget,
            externalLinkHandler = ::openExternalLink,
            presentationNamespaceKey = namespaceKey,
            publishProgressUpdate = (application as ErmaoLibraryApplication)
                .readerProgressPresentationCenter::publish,
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

    private fun removeRestoredNavigator() {
        val restored = supportFragmentManager.fragments.toList()
        if (restored.isEmpty()) return
        supportFragmentManager.commitNow(allowStateLoss = true) {
            restored.forEach(::remove)
        }
    }

    private fun attachNavigatorIfReady() {
        if (!containerReady || navigatorBound || supportFragmentManager.isStateSaved) return
        val navigator = pendingNavigator ?: return
        supportFragmentManager.commitNow {
            replace(READER_NAVIGATOR_CONTAINER_ID, navigator, NAVIGATOR_FRAGMENT_TAG)
        }
        session?.bind(lifecycleScope)
        navigatorBound = true
        controller = session
        opening = false
        pendingManagedRepair?.let { repair ->
            pendingManagedRepair = null
            lifecycleScope.launch {
                runCatching {
                    (application as ErmaoLibraryApplication).downloadFiles.replaceLocalArtifact(
                        repair.localReference,
                        repair.parsedSource,
                    )
                }.onFailure { failure ->
                    LOGGER.log(Level.WARNING, "reader_managed_repair_publish_failed", failure)
                }
            }
        }
        lifecycleScope.launch { recoverPendingProgressAndCheckRemote() }
    }

    private fun closeReader() {
        if (closing) return
        closing = true
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

        fun createServerIntent(context: Context, profileId: String, resourceId: String): Intent {
            require(profileId.isNotBlank() && resourceId.isNotBlank())
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SERVER_PROFILE_ID, profileId)
                .putExtra(EXTRA_SERVER_RESOURCE_ID, resourceId)
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
            return ServerReaderRequest(profileId, resourceId)
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

    private data class ServerReaderRequest(val profileId: String, val resourceId: String)
    private data class ManagedDownloadReaderRequest(
        val profileId: String,
        val bookId: String,
        val resourceId: String,
        val assetId: String,
        val displayTitle: String,
        val localReference: String,
        val sourceFormat: String,
    )
    private data class ActiveReaderSession(
        val profile: com.ermao.library.shared.modules.servers.domain.ServerProfile,
        val identity: com.ermao.library.shared.modules.auth.domain.SessionIdentity,
        val authenticated: AppSession.Authenticated?,
    )
}

private data class PendingManagedRepair(val localReference: String, val parsedSource: File)

private fun String.isSupportedManagedSourceFormat(): Boolean =
    trim().uppercase() in setOf("EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT", "CBZ", "ZIP", "CBR", "RAR", "PDF")

private object NonBlockingReaderProgressStore : ReaderProgressStore {
    override suspend fun load(resourceId: String): ReaderProgress? = null
    override suspend fun save(progress: ReaderProgress) = Unit
    override suspend fun delete(resourceId: String) = Unit
}

@OptIn(ExperimentalReadiumApi::class)
private fun readerNavigatorDummyFactory(): FragmentFactory {
    val epubFactory = EpubNavigatorFragment.createDummyFactory()
    val imageFactory = ImageNavigatorFragment.createDummyFactory()
    val pdfFactory = PdfiumNavigatorFragment.createDummyFactory(PdfiumEngineProvider())
    return object : FragmentFactory() {
        override fun instantiate(classLoader: ClassLoader, className: String): Fragment =
            if (className == ImageNavigatorFragment::class.java.name) {
                imageFactory.instantiate(classLoader, className)
            } else if (className == PdfiumNavigatorFragment::class.java.name) {
                pdfFactory.instantiate(classLoader, className)
            } else {
                epubFactory.instantiate(classLoader, className)
            }
    }
}
