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
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository

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

    override fun onCreate() {
        super.onCreate()
        val mobileStore = AndroidServerProfileStore(this)
        loginCredentialStore = AndroidLoginCredentialStore(this)
        contentRepository = createAndroidContentRepository(this)
        personalSettingsRepository = createAndroidPersonalSettingsRepository(this)
        administrativeSettingsRepository = createAndroidAdministrativeSettingsRepository(this)
        mobileRuntime = createAndroidMobileRuntime(
            context = this,
            profileRepository = mobileStore,
            entitlementRepository = mobileStore,
        )
    }

    override fun onTerminate() {
        mobileRuntime.close()
        super.onTerminate()
    }
}
