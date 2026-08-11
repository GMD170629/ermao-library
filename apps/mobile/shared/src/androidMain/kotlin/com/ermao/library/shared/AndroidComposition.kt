package com.ermao.library.shared

import android.content.Context
import com.ermao.library.shared.core.network.AndroidEncryptedCookieVault
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.modules.auth.application.DefaultMobileRuntime
import com.ermao.library.shared.modules.auth.application.OfflineEntitlementRepository
import com.ermao.library.shared.modules.auth.infrastructure.KtorAuthGateway
import com.ermao.library.shared.modules.servers.application.ServerProfileRepository
import com.ermao.library.shared.modules.servers.infrastructure.KtorServerProbe

fun createAndroidMobileRuntime(
    context: Context,
    profileRepository: ServerProfileRepository,
    entitlementRepository: OfflineEntitlementRepository,
): MobileRuntime {
    val applicationContext = context.applicationContext
    val cookieVault = AndroidEncryptedCookieVault(applicationContext)
    val clients = ApiClientFactory(cookieVault)
    val clientProvider = clients::create
    return DefaultMobileRuntime(
        profileRepository = profileRepository,
        cookieVault = cookieVault,
        entitlementRepository = entitlementRepository,
        serverProbe = KtorServerProbe(clientProvider = clientProvider),
        authGateway = KtorAuthGateway(clients, clientProvider),
    )
}
