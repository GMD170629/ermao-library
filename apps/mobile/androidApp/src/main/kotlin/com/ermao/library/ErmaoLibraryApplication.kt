package com.ermao.library

import android.app.Application
import com.ermao.library.platform.persistence.AndroidServerProfileStore
import com.ermao.library.platform.persistence.AndroidLoginCredentialStore
import com.ermao.library.platform.persistence.LoginCredentialStore
import com.ermao.library.shared.createAndroidContentRepository
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.createAndroidMobileRuntime
import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.createAndroidPersonalSettingsRepository
import com.ermao.library.shared.createAndroidAdministrativeSettingsRepository
import com.ermao.library.shared.createAndroidWorkManagementRepository
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.infrastructure.SharedDownloadCatalogAdapter
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.application.ReaderProgressPresentationCenter
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.platform.persistence.AndroidMobileStorageContract
import com.ermao.library.features.audio.application.AndroidAudioPlaybackRuntime
import com.ermao.library.features.audio.infrastructure.AndroidAudioTransportRegistry
import com.ermao.library.features.audio.infrastructure.AuthenticatedAudioDataSourceProvider
import com.ermao.library.features.audio.infrastructure.RegisteredAuthenticatedAudioDataSourceProvider

class ErmaoLibraryApplication : Application() {
    private val downloadsViewModelStore = androidx.lifecycle.ViewModelStore()
    private var downloadsNamespace: String? = null
    private var downloadsInstance: com.ermao.library.features.downloads.AccountDownloads? = null
    private var downloadsObservation: com.ermao.library.shared.modules.auth.Observation? = null
    private val lifecycleHandler = android.os.Handler(android.os.Looper.getMainLooper())

    fun accountDownloads(session: com.ermao.library.shared.modules.auth.domain.AppSession.Authenticated):
        com.ermao.library.features.downloads.AccountDownloads {
        val namespace = session.identity.namespace
        val key = "${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}"
        if (downloadsNamespace == key) downloadsInstance?.let { return it }
        if (downloadsNamespace != key) {
            downloadsViewModelStore.clear()
            downloadsInstance = null
            downloadsNamespace = key
        }
        val factory = com.ermao.library.features.downloads.AccountDownloads.factory(
            downloadCatalog, sharedDownloadCatalog, downloadFiles,
            com.ermao.library.shared.modules.downloads.createDownloadsGateway(
                com.ermao.library.shared.core.network.ApiClientFactory(
                    com.ermao.library.shared.core.network.AndroidEncryptedCookieVault(this),
                    requestTimeoutMillis = 30L * 60L * 1000L,
                ), session.profile,
            ),
            com.ermao.library.shared.modules.downloads.DownloadRequestContext(
                session.profile,
                com.ermao.library.shared.modules.downloads.DownloadNamespace(namespace.serverIdentity, namespace.userId, namespace.authorizationVersion),
            ),
        )
        return androidx.lifecycle.ViewModelProvider(downloadsViewModelStore, factory)[com.ermao.library.features.downloads.AccountDownloads::class.java]
            .also { downloadsInstance = it }
    }

    private fun releaseAccountDownloads(downloads: com.ermao.library.features.downloads.AccountDownloads) {
        if (downloadsInstance !== downloads) return
        downloadsViewModelStore.clear()
        downloadsInstance = null
        downloadsNamespace = null
    }
    lateinit var mobileRuntime: MobileRuntime
        private set
    lateinit var loginCredentialStore: LoginCredentialStore
        private set
    lateinit var contentRepository: ContentRepository
        private set
    lateinit var personalSettingsRepository: PersonalSettingsRepository
        private set
    lateinit var administrativeSettingsRepository: AdministrativeSettingsRepository
        private set
    lateinit var workManagementRepository: WorkManagementRepository
        private set
    lateinit var downloadCatalog: AndroidDownloadCatalog
        private set
    lateinit var downloadFiles: AtomicDownloadFileSink
        private set
    lateinit var sharedDownloadCatalog: DownloadCatalogRepository
        private set
    lateinit var readerProgressPresentationCenter: ReaderProgressPresentationCenter
        private set
    /**
     * Supplied by the shared Audio composition when that capability is available. The default
     * fails closed for remote media and never bypasses the shared Cookie/TLS transport policy.
     */
    lateinit var audioTransportProvider: AuthenticatedAudioDataSourceProvider
        private set
    lateinit var audioTransportRegistry: AndroidAudioTransportRegistry
        private set
    lateinit var audioPlaybackRuntime: AndroidAudioPlaybackRuntime
        private set

    override fun onCreate() {
        super.onCreate()
        AndroidMobileStorageContract.initialize(this)
        val mobileStore = AndroidServerProfileStore(this)
        loginCredentialStore = AndroidLoginCredentialStore(this)
        contentRepository = createAndroidContentRepository(this)
        personalSettingsRepository = createAndroidPersonalSettingsRepository(this)
        administrativeSettingsRepository = createAndroidAdministrativeSettingsRepository(this)
        workManagementRepository = createAndroidWorkManagementRepository(this)
        val downloadRoot = java.io.File(filesDir, "managed-downloads-v3")
        downloadCatalog = AndroidDownloadCatalog(downloadRoot)
        downloadFiles = AtomicDownloadFileSink(downloadRoot)
        sharedDownloadCatalog = SharedDownloadCatalogAdapter(downloadCatalog, downloadFiles)
        readerProgressPresentationCenter = ReaderProgressPresentationCenter()
        audioTransportRegistry = AndroidAudioTransportRegistry()
        audioTransportProvider = RegisteredAuthenticatedAudioDataSourceProvider(audioTransportRegistry)
        audioPlaybackRuntime = AndroidAudioPlaybackRuntime(
            context = this,
            transportRegistry = audioTransportRegistry,
            publishProgressUpdate = readerProgressPresentationCenter::publish,
        )
        mobileRuntime = createAndroidMobileRuntime(
            context = this,
            profileRepository = mobileStore,
            verifiedSessionRepository = mobileStore,
        )
        downloadsObservation = mobileRuntime.observeSession {
            lifecycleHandler.post {
                val current = mobileRuntime.currentSession as? com.ermao.library.shared.modules.auth.domain.AppSession.Authenticated
                val key = current?.identity?.namespace?.let { "${it.serverIdentity}|${it.userId}|${it.authorizationVersion}" }
                if (key != downloadsNamespace) downloadsInstance?.let(::releaseAccountDownloads)
            }
        }
    }

    override fun onTerminate() {
        downloadsObservation?.cancel()
        lifecycleHandler.removeCallbacksAndMessages(null)
        downloadsViewModelStore.clear()
        audioPlaybackRuntime.close()
        audioTransportRegistry.clear()
        mobileRuntime.close()
        super.onTerminate()
    }
}
