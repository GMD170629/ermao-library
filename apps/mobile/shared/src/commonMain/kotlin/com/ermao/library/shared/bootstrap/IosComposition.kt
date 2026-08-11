package com.ermao.library.shared.bootstrap

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.SecureCookiePayloadStore
import com.ermao.library.shared.core.network.SerializedCookieVault
import com.ermao.library.shared.modules.auth.MobileRuntimeBridge
import com.ermao.library.shared.modules.auth.application.DefaultMobileRuntime
import com.ermao.library.shared.modules.auth.application.DefaultMobileRuntimeBridge
import com.ermao.library.shared.modules.auth.infrastructure.KtorAuthGateway
import com.ermao.library.shared.modules.auth.infrastructure.OfflineEntitlementPayloadStore
import com.ermao.library.shared.modules.auth.infrastructure.SerializedOfflineEntitlementRepository
import com.ermao.library.shared.modules.servers.infrastructure.KtorServerProbe
import com.ermao.library.shared.modules.servers.infrastructure.SerializedServerProfileRepository
import com.ermao.library.shared.modules.servers.infrastructure.ServerProfilePayloadStore

/** Composition root for Swift. Cookie payloads must be backed by Keychain in iosApp. */
fun createIosMobileRuntimeBridge(
    cookieStore: SecureCookiePayloadStore,
    profileStore: ServerProfilePayloadStore,
    entitlementStore: OfflineEntitlementPayloadStore,
): MobileRuntimeBridge {
    val cookieVault = SerializedCookieVault(cookieStore)
    val profiles = SerializedServerProfileRepository(profileStore)
    val entitlements = SerializedOfflineEntitlementRepository(entitlementStore)
    val clients = ApiClientFactory(cookieVault)
    val clientProvider = clients::create
    return DefaultMobileRuntimeBridge(
        DefaultMobileRuntime(
            profileRepository = profiles,
            cookieVault = cookieVault,
            entitlementRepository = entitlements,
            serverProbe = KtorServerProbe(clientProvider = clientProvider),
            authGateway = KtorAuthGateway(clients, clientProvider),
        ),
    )
}
