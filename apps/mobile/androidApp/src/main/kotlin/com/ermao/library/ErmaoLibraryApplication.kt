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

class ErmaoLibraryApplication : Application() {
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
        mobileRuntime = createAndroidMobileRuntime(
            context = this,
            profileRepository = mobileStore,
            verifiedSessionRepository = mobileStore,
        )
    }

    override fun onTerminate() {
        mobileRuntime.close()
        super.onTerminate()
    }
}
