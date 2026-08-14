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
import com.ermao.library.features.reader.infrastructure.AndroidReadiumRuntime
import com.ermao.library.features.reader.infrastructure.ReaderOpenFailure
import com.ermao.library.features.reader.infrastructure.ReadiumReflowableSession
import com.ermao.library.features.reader.infrastructure.ReadiumComicSession
import com.ermao.library.features.reader.infrastructure.ReadiumPdfSession
import com.ermao.library.features.reader.infrastructure.ReadiumLocatorMapper
import com.ermao.library.features.reader.infrastructure.ReadiumPreferencesMapper
import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.BootstrapReaderPublication
import com.ermao.library.shared.modules.reader.LocalFirstReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.ReaderBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderBootstrapFailure
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderComicPage
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
import com.ermao.library.shared.modules.reader.compareExactReaderProgress
import com.ermao.library.shared.modules.reader.ExactLocationMatch
import com.ermao.library.shared.modules.reader.application.PendingVsServerDecision
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.ReaderTapZones
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapFailure
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.shared.createAndroidReaderProgressSyncPort
import com.ermao.library.shared.createAndroidReaderBookmarkSyncPort
import com.ermao.library.shared.createAndroidReaderServerGateway
import com.ermao.library.shared.modules.auth.domain.AppSession
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.delay
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.image.ImageNavigatorFragment
import org.readium.adapter.pdfium.navigator.PdfiumEngineProvider
import org.readium.adapter.pdfium.navigator.PdfiumNavigatorFragment
import androidx.fragment.app.FragmentFactory
import org.readium.r2.shared.ExperimentalReadiumApi
import java.util.logging.Level
import java.util.logging.Logger

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
    private var syncingProgressStore: ReaderProgressSyncingStore? = null
    private var progressCoordinator: ReaderProgressSyncCoordinator? = null
    private var progressQueryPort: ReaderProgressQueryPort? = null
    private var progressSyncTarget: ReaderProgressSyncTarget? = null
    private var progressClientId: String? = null
    private var progressEtag: String? = null
    private var startupConflict by mutableStateOf<AndroidStartupConflict?>(null)
    private var networkCallbackRegistered = false
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            lifecycleScope.launch { checkRemoteProgress() }
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

        val source = runCatching { intent.readerSourceOrNull() }.getOrNull()
        val managedRequest = runCatching { intent.managedDownloadRequestOrNull() }.getOrNull()
        val serverRequest = runCatching { intent.serverReaderRequestOrNull() }.getOrNull()
        if (source != null) {
            readerTitle = source.displayTitle
            session = createSession(
                source,
                AndroidReaderProgressStore(applicationContext),
                comicPages = intent.comicPagesOrEmpty(),
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
                onNavigatorContainerReady = {
                    containerReady = true
                    attachNavigatorIfReady()
                },
            )
            startupConflict?.let { conflict ->
                androidx.compose.material3.AlertDialog(
                    onDismissRequest = {},
                    title = { androidx.compose.material3.Text(getString(com.ermao.library.R.string.reader_startup_conflict_title)) },
                    text = { androidx.compose.material3.Text(getString(com.ermao.library.R.string.reader_startup_conflict_message)) },
                    confirmButton = {
                        androidx.compose.material3.TextButton(onClick = { useStartupLocal(conflict) }) {
                            androidx.compose.material3.Text(getString(com.ermao.library.R.string.reader_startup_use_local))
                        }
                    },
                    dismissButton = {
                        androidx.compose.foundation.layout.Row {
                            androidx.compose.material3.TextButton(onClick = { useStartupCloud(conflict) }) {
                                androidx.compose.material3.Text(getString(com.ermao.library.R.string.reader_startup_use_cloud))
                            }
                            androidx.compose.material3.TextButton(onClick = ::closeReader) {
                                androidx.compose.material3.Text(getString(android.R.string.cancel))
                            }
                        }
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
        lifecycleScope.launch { checkRemoteProgress() }
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
                readerSession.flush()
                awaitPendingUploadWithinLifecycleBudget()
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
                    syncingProgressStore?.load(target.volumeId),
                )
            }
            is ProgressQueryResult.Unchanged -> progressEtag = result.etag ?: progressEtag
            is ProgressQueryResult.Failure -> Unit
        }
    }

    private fun useStartupLocal(conflict: AndroidStartupConflict) {
        lifecycleScope.launch {
            val reader = awaitReaderController() ?: return@launch
            if (!reader.goTo(conflict.localProgress.location)) return@launch
            withTimeoutOrNull(5_000) {
                reader.currentLocation.filterNotNull().first { current ->
                    compareExactReaderProgress(
                        conflict.localProgress,
                        ReaderProgress(
                            conflict.localProgress.sourceId,
                            current,
                            System.currentTimeMillis(),
                            progressClientId ?: return@first false,
                        ),
                    ) == ExactLocationMatch.Exact
                }
            } ?: return@launch
            startupConflict = null
        }
    }

    private fun useStartupCloud(conflict: AndroidStartupConflict) {
        lifecycleScope.launch {
            val reader = awaitReaderController() ?: return@launch
            val current = withTimeoutOrNull(5_000) {
                reader.currentLocation.filterNotNull().first()
            } ?: return@launch
            val verified = ReaderProgress(
                conflict.localProgress.sourceId,
                current,
                System.currentTimeMillis(),
                progressClientId ?: return@launch,
            )
            runCatching {
                conflict.coordinator.acceptVerifiedRemoteProgress(verified, conflict.serverSnapshot)
            }.onSuccess { startupConflict = null }
        }
    }

    private suspend fun awaitReaderController(): ReaderScreenController? = withTimeoutOrNull(5_000) {
        while (controller == null) delay(25)
        controller
    }

    override fun onDestroy() {
        openJob?.cancel()
        lifecycleScope.launch { progressCoordinator?.cancelWorker() }
        session?.release()
        session = null
        super.onDestroy()
    }

    private suspend fun openServerReader(request: ServerReaderRequest) {
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
        val publicationStore = AndroidReaderPublicationStore(applicationContext)
        val bootstrapper = BootstrapReaderPublication(
            bootstrapGateway = serverGateway,
            downloadPort = serverGateway,
            sinkFactory = publicationStore.downloadSinkFactory(),
        )
        when (val result = bootstrapper.execute(
            ReaderBootstrapRequest(authenticated.profile, namespace, request.volumeId),
        )) {
            is ReaderPublicationBootstrapFailure -> showOpenError(
                if (result.recoverable) ReaderErrorCode.NetworkUnavailable else ReaderErrorCode.ResourceMissing,
            )
            is ReaderPublicationBootstrapContent -> {
                val source = result.source as? LocalReaderSource
                if (source == null) {
                    showOpenError(ReaderErrorCode.UnsupportedFormat)
                    return
                }
                val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
                val database = AndroidReaderProgressDatabase(
                    applicationContext,
                    ReaderLocalProgressIdentity(
                        namespace = namespace,
                        clientId = clientId,
                        workId = result.bootstrap.target.workId,
                        volumeId = source.sourceId,
                    ),
                )
                val startupDecision = decidePendingVsServerStartup(
                    database.load(source.sourceId),
                    database.loadSyncState(),
                    result.bootstrap.remoteSnapshot,
                    source,
                )
                val progressServer = createAndroidReaderProgressSyncPort(applicationContext, authenticated.profile)
                val coordinator = ReaderProgressSyncCoordinator(
                    stateStore = database,
                    server = progressServer,
                    scope = lifecycleScope,
                )
                val syncingStore = LocalFirstReaderProgressStore(
                    stateStore = database,
                    target = result.bootstrap.target,
                    coordinator = coordinator,
                )
                progressCoordinator = coordinator
                coordinator.beginSession(result.bootstrap.remoteSnapshot)
                progressQueryPort = progressServer
                progressSyncTarget = result.bootstrap.target
                progressClientId = clientId
                progressEtag = result.bootstrap.remoteSnapshot?.revision?.let { "\"reader-progress-$it\"" }
                    ?: "\"reader-progress-0\""
                var startupRemoteSnapshot = result.bootstrap.remoteSnapshot
                when (startupDecision) {
                    is PendingVsServerDecision.UseServer -> if (startupDecision.discardPending) {
                        database.loadSyncState().pending?.let {
                            coordinator.discardStartupPending(it.mutationId, startupDecision.snapshot?.revision ?: 0)
                        }
                    }
                    is PendingVsServerDecision.UseLocalPending -> {
                        startupRemoteSnapshot = null
                        coordinator.retryPending(result.bootstrap.target)
                    }
                    is PendingVsServerDecision.RequiresChoice -> startupConflict = AndroidStartupConflict(
                        startupDecision.progress,
                        startupDecision.server,
                        coordinator,
                    )
                }
                syncingProgressStore = syncingStore
                readerTitle = source.displayTitle
                session = createSession(
                    source,
                    syncingStore,
                    startupRemoteSnapshot,
                    coordinator,
                    preferencesStore,
                    AndroidReaderBookmarkStore(
                        applicationContext,
                        namespace.serverIdentity,
                        namespace.userId,
                        source.sourceId,
                        result.bootstrap.artifactVersion,
                    ),
                    createAndroidReaderBookmarkSyncPort(applicationContext, authenticated.profile),
                    ReaderBookmarkSyncTarget(
                        namespace.serverIdentity,
                        source.sourceId,
                        result.bootstrap.artifactVersion,
                    ),
                    namespaceKey = namespace.presentationKey(),
                    comicPages = result.bootstrap.comicPages,
                    pageCount = result.bootstrap.pageCount,
                )
                prepareSession(checkNotNull(session))
            }
        }
    }

    private suspend fun openManagedDownload(request: ManagedDownloadReaderRequest) {
        val application = application as ErmaoLibraryApplication
        val runtime = application.mobileRuntime
        if (runtime.currentSession !is AppSession.Authenticated && runtime.currentSession !is AppSession.OfflineGrace) {
            runtime.start()
        }
        val activeSession = when (val current = runtime.currentSession) {
            is AppSession.Authenticated -> ActiveReaderSession(current.profile, current.identity, current)
            is AppSession.OfflineGrace -> ActiveReaderSession(current.profile, current.identity, null)
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
        if (localFile == null || !localFile.isFile || localFile.length() != request.expectedBytes) {
            showOpenError(ReaderErrorCode.ResourceMissing)
            return
        }
        val publicationStore = AndroidReaderPublicationStore(applicationContext)
        val exactSourceFormat = ReaderSourceFormat.fromWireValue(request.sourceFormat)
        if (exactSourceFormat == null) {
            showOpenError(ReaderErrorCode.UnsupportedFormat)
            return
        }
        val source = localFile.inputStream().use { input ->
            publicationStore.publishLocalPublication(
                sourceId = request.volumeId,
                displayTitle = request.displayTitle,
                input = input,
                sourceFormat = exactSourceFormat,
                publicationFingerprint = null,
                workId = request.workId,
                volumeId = request.volumeId,
            )
        }
        val authenticated = activeSession.authenticated
        val progressStore: ReaderProgressStore
        var bookmarkSyncPort: ReaderBookmarkSyncPort? = null
        var remoteSnapshot: com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4? = null
        var comicPages: List<ReaderComicPage> = emptyList()
        var pageCount: Int? = null
        if (authenticated != null) {
            val namespace = ReaderSyncNamespace(
                activeSession.identity.namespace.serverIdentity,
                activeSession.identity.namespace.userId,
                activeSession.identity.namespace.authorizationVersion,
            )
            when (val bootstrap = createAndroidReaderServerGateway(applicationContext).load(
                ReaderBootstrapRequest(activeSession.profile, namespace, request.volumeId),
            )) {
                is ReaderBootstrapContent -> {
                    if (bootstrap.value.artifactVersion != request.serverContentFingerprint) {
                        showOpenError(ReaderErrorCode.ResourceMissing)
                        return
                    }
                    if (source.contentFingerprint != bootstrap.value.publication.publicationFingerprint.toContentFingerprint()) {
                        showOpenError(ReaderErrorCode.CorruptFile)
                        return
                    }
                    val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
                    val database = AndroidReaderProgressDatabase(
                        applicationContext,
                        ReaderLocalProgressIdentity(namespace, clientId, bootstrap.value.target.workId, source.sourceId),
                    )
                    val startupDecision = decidePendingVsServerStartup(
                        database.load(source.sourceId),
                        database.loadSyncState(),
                        bootstrap.value.remoteSnapshot,
                        source,
                    )
                    val progressServer = createAndroidReaderProgressSyncPort(applicationContext, activeSession.profile)
                    val coordinator = ReaderProgressSyncCoordinator(
                        stateStore = database,
                        server = progressServer,
                        scope = lifecycleScope,
                    )
                    val syncingStore = LocalFirstReaderProgressStore(database, bootstrap.value.target, coordinator)
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
                                coordinator.discardStartupPending(it.mutationId, startupDecision.snapshot?.revision ?: 0)
                            }
                        }
                        is PendingVsServerDecision.UseLocalPending -> {
                            remoteSnapshot = null
                            coordinator.retryPending(bootstrap.value.target)
                        }
                        is PendingVsServerDecision.RequiresChoice -> startupConflict = AndroidStartupConflict(
                            startupDecision.progress,
                            startupDecision.server,
                            coordinator,
                        )
                    }
                    syncingProgressStore = syncingStore
                    progressStore = syncingStore
                    if (startupDecision !is PendingVsServerDecision.UseLocalPending) {
                        remoteSnapshot = bootstrap.value.remoteSnapshot
                    }
                    comicPages = bootstrap.value.comicPages
                    pageCount = bootstrap.value.pageCount
                    bookmarkSyncPort = createAndroidReaderBookmarkSyncPort(applicationContext, activeSession.profile)
                }
                is ReaderBootstrapFailure -> {
                    if (!bootstrap.recoverable) {
                        showOpenError(ReaderErrorCode.ResourceMissing)
                        return
                    }
                    progressStore = AndroidReaderProgressDatabase(
                        applicationContext,
                        ReaderLocalProgressIdentity(
                            namespace = ReaderSyncNamespace(
                                activeSession.identity.namespace.serverIdentity,
                                activeSession.identity.namespace.userId,
                                activeSession.identity.namespace.authorizationVersion,
                            ),
                            clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId(),
                            workId = request.workId,
                            volumeId = source.sourceId,
                        ),
                    )
                }
            }
        } else {
            progressStore = AndroidReaderProgressStore(applicationContext)
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
                readerNamespace.serverIdentity,
                readerNamespace.userId,
                source.sourceId,
                request.serverContentFingerprint,
            ),
            bookmarkSyncPort,
            ReaderBookmarkSyncTarget(
                readerNamespace.serverIdentity,
                source.sourceId,
                request.serverContentFingerprint,
            ),
            namespaceKey = readerNamespace.presentationKey(),
            comicPages = comicPages,
            pageCount = pageCount,
        )
        prepareSession(checkNotNull(session))
    }

    private suspend fun prepareSession(readerSession: AndroidReaderNavigatorSession) {
        try {
            pendingNavigator = readerSession.prepare(classLoader)
            attachNavigatorIfReady()
        } catch (failure: ReaderOpenFailure) {
            readerSession.release()
            opening = false
            openError = failure.readerError
            LOGGER.log(Level.SEVERE, "reader_open_failed code={0}", failure.readerError.code.wireValue)
        } catch (_: RuntimeException) {
            readerSession.release()
            showOpenError(ReaderErrorCode.ReaderEngineError)
        }
    }

    private fun showOpenError(code: ReaderErrorCode) {
        opening = false
        openError = ReaderError(code)
        LOGGER.log(Level.SEVERE, "reader_open_failed code={0}", code.wireValue)
    }

    private suspend fun awaitPendingUploadWithinLifecycleBudget() {
        withTimeoutOrNull(SYNC_FLUSH_TIMEOUT_MILLIS) {
            syncingProgressStore?.awaitPendingUpload()
        }
    }

    private fun createSession(
        source: LocalReaderSource,
        progressStore: ReaderProgressStore,
        remoteSnapshot: com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4? = null,
        progressCoordinator: ReaderProgressSyncCoordinator? = null,
        preferencesStore: AndroidReaderPreferencesStore? = null,
        bookmarkStore: AndroidReaderBookmarkStore? = null,
        bookmarkSyncPort: ReaderBookmarkSyncPort? = null,
        bookmarkSyncTarget: ReaderBookmarkSyncTarget? = null,
        namespaceKey: String? = null,
        comicPages: List<ReaderComicPage> = emptyList(),
        pageCount: Int? = null,
    ): AndroidReaderNavigatorSession {
        val sourceFormat = requireNotNull(source.sourceFormat) { "Reader source format is missing" }
        try {
            AndroidReaderCapabilities.registry.requireOpenable(sourceFormat)
        } catch (error: IllegalArgumentException) {
            throw ReaderOpenFailure(ReaderError(ReaderErrorCode.UnsupportedFormat), cause = error)
        }
        if (sourceFormat == ReaderSourceFormat.Cbz) {
            if (comicPages.isEmpty()) {
                throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile))
            }
            return ReadiumComicSession(
                source = source,
                canonicalPages = comicPages,
                publicationStore = AndroidReaderPublicationStore(applicationContext),
                progressStore = progressStore,
                deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
                readium = AndroidReadiumRuntime(applicationContext),
                remoteSnapshot = remoteSnapshot,
                progressCoordinator = progressCoordinator,
                initialPreferences = preferencesStore?.load() ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
                persistPreferences = { preferences -> preferencesStore?.save(preferences) },
                presentationNamespaceKey = namespaceKey,
                publishProgressUpdate = (application as ErmaoLibraryApplication)
                    .readerProgressPresentationCenter::publish,
            )
        }
        if (sourceFormat == ReaderSourceFormat.Pdf) {
            val exactPageCount = pageCount
                ?: throw ReaderOpenFailure(ReaderError(ReaderErrorCode.CorruptFile))
            return ReadiumPdfSession(
                source = source,
                expectedPageCount = exactPageCount,
                publicationStore = AndroidReaderPublicationStore(applicationContext),
                progressStore = progressStore,
                deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
                readium = AndroidReadiumRuntime(applicationContext),
                remoteSnapshot = remoteSnapshot,
                progressCoordinator = progressCoordinator,
                initialPreferences = preferencesStore?.load() ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
                persistPreferences = { preferences -> preferencesStore?.save(preferences) },
                presentationNamespaceKey = namespaceKey,
                publishProgressUpdate = (application as ErmaoLibraryApplication)
                    .readerProgressPresentationCenter::publish,
            )
        }
        return ReadiumReflowableSession(
            source = source,
            publicationStore = AndroidReaderPublicationStore(applicationContext),
            progressStore = progressStore,
            deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
            readium = AndroidReadiumRuntime(applicationContext),
            locatorMapper = ReadiumLocatorMapper(),
            preferencesMapper = ReadiumPreferencesMapper(resources),
            remoteSnapshot = remoteSnapshot,
            progressCoordinator = progressCoordinator,
            initialPreferences = preferencesStore?.load() ?: com.ermao.library.shared.modules.reader.ReaderPreferences(),
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
        lifecycleScope.launch { checkRemoteProgress() }
    }

    private fun closeReader() {
        if (closing) return
        closing = true
        lifecycleScope.launch {
            openJob?.cancel()
            session?.close()
            // Exact progress is already local; closing only waits a short
            // bounded interval for the ephemeral best-effort upload.
            awaitPendingUploadWithinLifecycleBudget()
            finish()
        }
    }

    companion object {
        private val LOGGER = Logger.getLogger("MobileReader")
        private const val NAVIGATOR_FRAGMENT_TAG = "reader-epub-navigator"
        private const val EXTRA_SOURCE_ID = "reader.source-id"
        private const val EXTRA_TITLE = "reader.title"
        private const val EXTRA_FILE_HASH = "reader.file-hash"
        private const val EXTRA_PARSER_VERSION = "reader.parser-version"
        private const val EXTRA_NORMALIZATION_VERSION = "reader.normalization-version"
        private const val EXTRA_SOURCE_FORMAT = "reader.source-format"
        private const val EXTRA_WORK_ID = "reader.work-id"
        private const val EXTRA_VOLUME_ID = "reader.volume-id"
        private const val EXTRA_SERVER_PROFILE_ID = "reader.server-profile-id"
        private const val EXTRA_SERVER_VOLUME_ID = "reader.server-volume-id"
        private const val EXTRA_MANAGED_LOCAL_REFERENCE = "reader.managed-local-reference"
        private const val EXTRA_MANAGED_SERVER_FINGERPRINT = "reader.managed-server-fingerprint"
        private const val EXTRA_MANAGED_EXPECTED_BYTES = "reader.managed-expected-bytes"
        private const val EXTRA_COMIC_PAGE_HREFS = "reader.comic-page-hrefs"
        private const val EXTRA_COMIC_PAGE_MEDIA_TYPES = "reader.comic-page-media-types"
        private const val EXTRA_PAGE_COUNT = "reader.page-count"
        private const val SYNC_FLUSH_TIMEOUT_MILLIS = 2_500L

        fun createIntent(
            context: Context,
            source: LocalReaderSource,
            comicPages: List<ReaderComicPage> = emptyList(),
            pageCount: Int? = null,
        ): Intent {
            require(source.format in setOf(ReaderFormat.Epub, ReaderFormat.Mobi, ReaderFormat.Text, ReaderFormat.Comic, ReaderFormat.Pdf)) {
                "Reader accepts only supported local sources"
            }
            require(source.format == ReaderFormat.Comic || comicPages.isEmpty())
            require(source.format != ReaderFormat.Comic || comicPages.isNotEmpty())
            require(source.format != ReaderFormat.Pdf || pageCount != null && pageCount > 0)
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SOURCE_ID, source.sourceId)
                .putExtra(EXTRA_TITLE, source.displayTitle)
                .putExtra(EXTRA_FILE_HASH, source.contentFingerprint.originalFileHash)
                .putExtra(EXTRA_PARSER_VERSION, source.contentFingerprint.parserVersion)
                .putExtra(EXTRA_NORMALIZATION_VERSION, source.contentFingerprint.normalizationVersion)
                .putExtra(EXTRA_SOURCE_FORMAT, source.sourceFormat?.wireValue ?: source.format.wireValue)
                .putExtra(EXTRA_WORK_ID, source.workId)
                .putExtra(EXTRA_VOLUME_ID, source.volumeId)
                .putStringArrayListExtra(
                    EXTRA_COMIC_PAGE_HREFS,
                    ArrayList(comicPages.map(ReaderComicPage::resourceHref)),
                )
                .putStringArrayListExtra(
                    EXTRA_COMIC_PAGE_MEDIA_TYPES,
                    ArrayList(comicPages.map(ReaderComicPage::mediaType)),
                )
                .putExtra(EXTRA_PAGE_COUNT, pageCount ?: -1)
        }

        fun createServerIntent(context: Context, profileId: String, volumeId: String): Intent {
            require(profileId.isNotBlank() && volumeId.isNotBlank())
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SERVER_PROFILE_ID, profileId)
                .putExtra(EXTRA_SERVER_VOLUME_ID, volumeId)
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        fun createManagedDownloadIntent(
            context: Context,
            profileId: String,
            workId: String,
            volumeId: String,
            displayTitle: String,
            localReference: String,
            serverContentFingerprint: String,
            expectedBytes: Long,
            sourceFormat: String,
        ): Intent {
            require(
                profileId.isNotBlank() && workId.isNotBlank() && volumeId.isNotBlank() &&
                    displayTitle.isNotBlank() && localReference.isNotBlank() &&
                    serverContentFingerprint.isNotBlank() && expectedBytes > 0 &&
                    sourceFormat.isSupportedManagedSourceFormat(),
            )
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SERVER_PROFILE_ID, profileId)
                .putExtra(EXTRA_WORK_ID, workId)
                .putExtra(EXTRA_VOLUME_ID, volumeId)
                .putExtra(EXTRA_TITLE, displayTitle)
                .putExtra(EXTRA_MANAGED_LOCAL_REFERENCE, localReference)
                .putExtra(EXTRA_MANAGED_SERVER_FINGERPRINT, serverContentFingerprint)
                .putExtra(EXTRA_MANAGED_EXPECTED_BYTES, expectedBytes)
                .putExtra(EXTRA_SOURCE_FORMAT, sourceFormat.trim().lowercase())
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        private fun Intent.readerSourceOrNull(): LocalReaderSource? {
            val sourceId = getStringExtra(EXTRA_SOURCE_ID) ?: return null
            val sourceFormatValue = getStringExtra(EXTRA_SOURCE_FORMAT)
            val sourceFormat = if (sourceFormatValue == null) {
                ReaderSourceFormat.Epub
            } else {
                ReaderSourceFormat.fromWireValue(sourceFormatValue) ?: return null
            }
            val format = sourceFormat.readerFormat
            return LocalReaderSource(
                sourceId = sourceId,
                displayTitle = checkNotNull(getStringExtra(EXTRA_TITLE)),
                format = format,
                contentFingerprint = ContentFingerprint(
                    originalFileHash = checkNotNull(getStringExtra(EXTRA_FILE_HASH)),
                    parserVersion = checkNotNull(getStringExtra(EXTRA_PARSER_VERSION)),
                    normalizationVersion = checkNotNull(getStringExtra(EXTRA_NORMALIZATION_VERSION)),
                ),
                workId = getStringExtra(EXTRA_WORK_ID),
                volumeId = getStringExtra(EXTRA_VOLUME_ID),
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

        private fun Intent.serverReaderRequestOrNull(): ServerReaderRequest? {
            val profileId = getStringExtra(EXTRA_SERVER_PROFILE_ID) ?: return null
            val volumeId = getStringExtra(EXTRA_SERVER_VOLUME_ID) ?: return null
            return ServerReaderRequest(profileId, volumeId)
        }


        private fun Intent.managedDownloadRequestOrNull(): ManagedDownloadReaderRequest? {
            val localReference = getStringExtra(EXTRA_MANAGED_LOCAL_REFERENCE) ?: return null
            return ManagedDownloadReaderRequest(
                profileId = checkNotNull(getStringExtra(EXTRA_SERVER_PROFILE_ID)),
                workId = checkNotNull(getStringExtra(EXTRA_WORK_ID)),
                volumeId = checkNotNull(getStringExtra(EXTRA_VOLUME_ID)),
                displayTitle = checkNotNull(getStringExtra(EXTRA_TITLE)),
                localReference = localReference,
                serverContentFingerprint = checkNotNull(getStringExtra(EXTRA_MANAGED_SERVER_FINGERPRINT)),
                expectedBytes = getLongExtra(EXTRA_MANAGED_EXPECTED_BYTES, -1L).also { check(it > 0) },
                sourceFormat = checkNotNull(getStringExtra(EXTRA_SOURCE_FORMAT))
                    .also { check(it.isSupportedManagedSourceFormat()) },
            )
        }
    }

    private data class ServerReaderRequest(val profileId: String, val volumeId: String)
    private data class ManagedDownloadReaderRequest(
        val profileId: String,
        val workId: String,
        val volumeId: String,
        val displayTitle: String,
        val localReference: String,
        val serverContentFingerprint: String,
        val expectedBytes: Long,
        val sourceFormat: String,
    )
    private data class ActiveReaderSession(
        val profile: com.ermao.library.shared.modules.servers.domain.ServerProfile,
        val identity: com.ermao.library.shared.modules.auth.domain.SessionIdentity,
        val authenticated: AppSession.Authenticated?,
    )
}

private data class AndroidStartupConflict(
    val localProgress: ReaderProgress,
    val serverSnapshot: ReaderProgressSnapshotV4,
    val coordinator: ReaderProgressSyncCoordinator,
)

private fun String.isSupportedManagedSourceFormat(): Boolean =
    trim().uppercase() in setOf("EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT", "CBZ", "PDF")

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
