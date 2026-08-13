package com.ermao.library.features.reader.presentation

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.os.Bundle
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
import com.ermao.library.features.reader.infrastructure.AndroidReadiumRuntime
import com.ermao.library.features.reader.infrastructure.ReaderOpenFailure
import com.ermao.library.features.reader.infrastructure.ReadiumEpubSession
import com.ermao.library.features.reader.infrastructure.ReadiumLocatorMapper
import com.ermao.library.features.reader.infrastructure.ReadiumPreferencesMapper
import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.BootstrapReaderPublication
import com.ermao.library.shared.modules.reader.LocalFirstReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.ReaderBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderBootstrapFailure
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore
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
import org.readium.r2.navigator.epub.EpubNavigatorFragment
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

    private var session: ReadiumEpubSession? = null
    private var pendingNavigator: EpubNavigatorFragment? = null
    private var containerReady = false
    private var navigatorBound = false
    private var closing = false
    private var openJob: Job? = null
    private var syncingProgressStore: ReaderProgressSyncingStore? = null
    private var progressCoordinator: ReaderProgressSyncCoordinator? = null

    internal val controllerForTesting: ReaderScreenController?
        get() = controller
    internal val controlsVisibleForTesting: Boolean
        get() = controlsVisible

    override fun onCreate(savedInstanceState: Bundle?) {
        supportFragmentManager.fragmentFactory = EpubNavigatorFragment.createDummyFactory()
        super.onCreate(savedInstanceState)
        removeRestoredNavigator()

        val source = runCatching { intent.readerSourceOrNull() }.getOrNull()
        val managedRequest = runCatching { intent.managedDownloadRequestOrNull() }.getOrNull()
        val serverRequest = runCatching { intent.serverReaderRequestOrNull() }.getOrNull()
        if (source != null) {
            readerTitle = source.displayTitle
            session = createSession(source, AndroidReaderProgressStore(applicationContext))
        } else if (managedRequest != null) {
            openJob = lifecycleScope.launch {
                try {
                    openManagedDownload(managedRequest)
                } catch (cancelled: kotlinx.coroutines.CancellationException) {
                    throw cancelled
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
        }

        if (source != null) {
            openJob = lifecycleScope.launch { prepareSession(checkNotNull(session)) }
        }
    }

    override fun onResumeFragments() {
        super.onResumeFragments()
        attachNavigatorIfReady()
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
        if (!closing) session?.let { readerSession ->
            lifecycleScope.launch {
                readerSession.flush()
                awaitPendingUploadWithinLifecycleBudget()
            }
        }
        super.onStop()
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
                        volumeId = source.sourceId,
                        localContentFingerprint = source.contentFingerprint,
                    ),
                )
                val coordinator = ReaderProgressSyncCoordinator(
                    stateStore = database,
                    server = createAndroidReaderProgressSyncPort(applicationContext, authenticated.profile),
                    scope = lifecycleScope,
                )
                val syncingStore = LocalFirstReaderProgressStore(
                    stateStore = database,
                    target = result.bootstrap.target,
                    coordinator = coordinator,
                )
                progressCoordinator = coordinator
                syncingProgressStore = syncingStore
                readerTitle = source.displayTitle
                session = createSession(
                    source,
                    syncingStore,
                    result.bootstrap.remoteSnapshot,
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
        val source = localFile.inputStream().use { input ->
            publicationStore.publishLocalEpub(
                sourceId = request.volumeId,
                displayTitle = request.displayTitle,
                input = input,
                workId = request.workId,
                volumeId = request.volumeId,
            )
        }
        val authenticated = activeSession.authenticated
        val progressStore: ReaderProgressStore
        var bookmarkSyncPort: ReaderBookmarkSyncPort? = null
        var remoteSnapshot: com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4? = null
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
                    val clientId = AndroidReaderDeviceIdentity(applicationContext).stableDeviceId()
                    val database = AndroidReaderProgressDatabase(
                        applicationContext,
                        ReaderLocalProgressIdentity(namespace, clientId, source.sourceId, source.contentFingerprint),
                    )
                    val coordinator = ReaderProgressSyncCoordinator(
                        stateStore = database,
                        server = createAndroidReaderProgressSyncPort(applicationContext, activeSession.profile),
                        scope = lifecycleScope,
                    )
                    val syncingStore = LocalFirstReaderProgressStore(database, bootstrap.value.target, coordinator)
                    progressCoordinator = coordinator
                    syncingProgressStore = syncingStore
                    progressStore = syncingStore
                    remoteSnapshot = bootstrap.value.remoteSnapshot
                    bookmarkSyncPort = createAndroidReaderBookmarkSyncPort(applicationContext, activeSession.profile)
                }
                is ReaderBootstrapFailure -> {
                    if (!bootstrap.recoverable) {
                        showOpenError(ReaderErrorCode.ResourceMissing)
                        return
                    }
                    progressStore = AndroidReaderProgressStore(applicationContext)
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
        )
        prepareSession(checkNotNull(session))
    }

    private suspend fun prepareSession(readerSession: ReadiumEpubSession) {
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
        preferencesStore: AndroidReaderPreferencesStore? = null,
        bookmarkStore: AndroidReaderBookmarkStore? = null,
        bookmarkSyncPort: ReaderBookmarkSyncPort? = null,
        bookmarkSyncTarget: ReaderBookmarkSyncTarget? = null,
        namespaceKey: String? = null,
    ): ReadiumEpubSession = ReadiumEpubSession(
        source = source,
        publicationStore = AndroidReaderPublicationStore(applicationContext),
        progressStore = progressStore,
        deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
        readium = AndroidReadiumRuntime(applicationContext),
        locatorMapper = ReadiumLocatorMapper(),
        preferencesMapper = ReadiumPreferencesMapper(resources),
        remoteSnapshot = remoteSnapshot,
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
        private const val EXTRA_WORK_ID = "reader.work-id"
        private const val EXTRA_VOLUME_ID = "reader.volume-id"
        private const val EXTRA_SERVER_PROFILE_ID = "reader.server-profile-id"
        private const val EXTRA_SERVER_VOLUME_ID = "reader.server-volume-id"
        private const val EXTRA_MANAGED_LOCAL_REFERENCE = "reader.managed-local-reference"
        private const val EXTRA_MANAGED_SERVER_FINGERPRINT = "reader.managed-server-fingerprint"
        private const val EXTRA_MANAGED_EXPECTED_BYTES = "reader.managed-expected-bytes"
        private const val SYNC_FLUSH_TIMEOUT_MILLIS = 2_500L

        fun createIntent(context: Context, source: LocalReaderSource): Intent {
            require(source.format == ReaderFormat.Epub) { "Reader R2 accepts EPUB sources only" }
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SOURCE_ID, source.sourceId)
                .putExtra(EXTRA_TITLE, source.displayTitle)
                .putExtra(EXTRA_FILE_HASH, source.contentFingerprint.originalFileHash)
                .putExtra(EXTRA_WORK_ID, source.workId)
                .putExtra(EXTRA_VOLUME_ID, source.volumeId)
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
        ): Intent {
            require(
                profileId.isNotBlank() && workId.isNotBlank() && volumeId.isNotBlank() &&
                    displayTitle.isNotBlank() && localReference.isNotBlank() &&
                    serverContentFingerprint.isNotBlank() && expectedBytes > 0,
            )
            return Intent(context, ReaderActivity::class.java)
                .putExtra(EXTRA_SERVER_PROFILE_ID, profileId)
                .putExtra(EXTRA_WORK_ID, workId)
                .putExtra(EXTRA_VOLUME_ID, volumeId)
                .putExtra(EXTRA_TITLE, displayTitle)
                .putExtra(EXTRA_MANAGED_LOCAL_REFERENCE, localReference)
                .putExtra(EXTRA_MANAGED_SERVER_FINGERPRINT, serverContentFingerprint)
                .putExtra(EXTRA_MANAGED_EXPECTED_BYTES, expectedBytes)
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        private fun Intent.readerSourceOrNull(): LocalReaderSource? {
            val sourceId = getStringExtra(EXTRA_SOURCE_ID) ?: return null
            return LocalReaderSource(
            sourceId = sourceId,
            displayTitle = checkNotNull(getStringExtra(EXTRA_TITLE)),
            format = ReaderFormat.Epub,
            contentFingerprint = ContentFingerprint(
                originalFileHash = checkNotNull(getStringExtra(EXTRA_FILE_HASH)),
                parserVersion = AndroidReaderPublicationStore.READIUM_PARSER_VERSION,
                normalizationVersion = AndroidReaderPublicationStore.EPUB_NORMALIZATION_VERSION,
            ),
            workId = getStringExtra(EXTRA_WORK_ID),
            volumeId = getStringExtra(EXTRA_VOLUME_ID),
        )
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
    )
    private data class ActiveReaderSession(
        val profile: com.ermao.library.shared.modules.servers.domain.ServerProfile,
        val identity: com.ermao.library.shared.modules.auth.domain.SessionIdentity,
        val authenticated: AppSession.Authenticated?,
    )
}
