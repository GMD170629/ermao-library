package com.ermao.library.features.reader.presentation

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.os.Bundle
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
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderProgressSyncCoordinator
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderPublicationBootstrapFailure
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.shared.createAndroidReaderProgressSyncPort
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

    override fun onCreate(savedInstanceState: Bundle?) {
        supportFragmentManager.fragmentFactory = EpubNavigatorFragment.createDummyFactory()
        super.onCreate(savedInstanceState)
        removeRestoredNavigator()

        val source = runCatching { intent.readerSourceOrNull() }.getOrNull()
        val serverRequest = runCatching { intent.serverReaderRequestOrNull() }.getOrNull()
        if (source != null) {
            readerTitle = source.displayTitle
            session = createSession(source, AndroidReaderProgressStore(applicationContext))
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
        lifecycleScope.launch { progressCoordinator?.cancel() }
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
                    localStore = database,
                    server = createAndroidReaderProgressSyncPort(applicationContext, authenticated.profile),
                    scope = lifecycleScope,
                )
                val syncingStore = LocalFirstReaderProgressStore(
                    localStore = database,
                    target = result.bootstrap.target,
                    coordinator = coordinator,
                )
                progressCoordinator = coordinator
                syncingProgressStore = syncingStore
                readerTitle = source.displayTitle
                session = createSession(source, syncingStore, result.bootstrap.remoteSnapshot)
                prepareSession(checkNotNull(session))
            }
        }
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
    ): ReadiumEpubSession = ReadiumEpubSession(
        source = source,
        publicationStore = AndroidReaderPublicationStore(applicationContext),
        progressStore = progressStore,
        deviceIdentity = AndroidReaderDeviceIdentity(applicationContext),
        readium = AndroidReadiumRuntime(applicationContext),
        locatorMapper = ReadiumLocatorMapper(),
        preferencesMapper = ReadiumPreferencesMapper(resources),
        remoteSnapshot = remoteSnapshot,
        externalLinkHandler = ::openExternalLink,
    )

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
    }

    private data class ServerReaderRequest(val profileId: String, val volumeId: String)
}
