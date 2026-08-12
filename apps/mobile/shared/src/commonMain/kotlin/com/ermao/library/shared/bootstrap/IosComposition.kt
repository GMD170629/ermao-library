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
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.InMemoryLibraryCacheRepository
import com.ermao.library.shared.modules.library.infrastructure.KtorContentRepository
import com.ermao.library.shared.modules.library.application.LibrarySnapshotPayloadStore
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.shared.modules.personalsettings.infrastructure.KtorPersonalSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.infrastructure.KtorAdministrativeSettingsRepository
import com.ermao.library.shared.core.time.currentEpochMillis

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

/** Independent content composition; it shares the persisted authenticated Cookie vault. */
fun createIosContentRepository(
    cookieStore: SecureCookiePayloadStore,
    snapshotStore: LibrarySnapshotPayloadStore,
): ContentRepository =
    KtorContentRepository(
        clients = ApiClientFactory(SerializedCookieVault(cookieStore)),
        cache = InMemoryLibraryCacheRepository(),
        nowEpochMillis = ::currentEpochMillis,
        snapshots = snapshotStore,
    )

/** Independent personal-settings composition; cookie payloads stay behind the Keychain adapter. */
fun createIosPersonalSettingsRepository(
    cookieStore: SecureCookiePayloadStore,
): PersonalSettingsRepository =
    KtorPersonalSettingsRepository(
        ApiClientFactory(SerializedCookieVault(cookieStore)),
    )

/** Native administrative settings share Keychain-backed cookies and do not expose Web routes. */
fun createIosAdministrativeSettingsRepository(
    cookieStore: SecureCookiePayloadStore,
): AdministrativeSettingsRepository =
    KtorAdministrativeSettingsRepository(
        ApiClientFactory(SerializedCookieVault(cookieStore)),
    )
