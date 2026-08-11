package com.ermao.library

import android.app.Application
import com.ermao.library.platform.persistence.AndroidServerProfileStore
import com.ermao.library.shared.createAndroidMobileRuntime
import com.ermao.library.shared.modules.auth.MobileRuntime

class ErmaoLibraryApplication : Application() {
    lateinit var mobileRuntime: MobileRuntime
        private set

    override fun onCreate() {
        super.onCreate()
        val mobileStore = AndroidServerProfileStore(this)
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
