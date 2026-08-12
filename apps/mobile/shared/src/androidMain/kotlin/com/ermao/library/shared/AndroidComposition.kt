package com.ermao.library.shared

import android.content.Context
import com.ermao.library.shared.core.network.AndroidEncryptedCookieVault
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.auth.MobileRuntime
import com.ermao.library.shared.modules.auth.application.DefaultMobileRuntime
import com.ermao.library.shared.modules.auth.application.OfflineEntitlementRepository
import com.ermao.library.shared.modules.auth.infrastructure.KtorAuthGateway
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.InMemoryLibraryCacheRepository
import com.ermao.library.shared.modules.library.infrastructure.KtorContentRepository
import com.ermao.library.shared.modules.library.infrastructure.AndroidLibrarySnapshotPayloadStore
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.shared.modules.personalsettings.infrastructure.KtorPersonalSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.infrastructure.KtorAdministrativeSettingsRepository
import com.ermao.library.shared.core.time.currentEpochMillis
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

fun createAndroidContentRepository(context: Context): ContentRepository {
    val cookieVault = AndroidEncryptedCookieVault(context.applicationContext)
    return KtorContentRepository(
        clients = ApiClientFactory(cookieVault),
        cache = InMemoryLibraryCacheRepository(),
        nowEpochMillis = ::currentEpochMillis,
        snapshots = AndroidLibrarySnapshotPayloadStore(context.applicationContext),
    )
}

/** Independent personal-settings composition; authenticated cookies remain in encrypted storage. */
fun createAndroidPersonalSettingsRepository(context: Context): PersonalSettingsRepository {
    val cookieVault = AndroidEncryptedCookieVault(context.applicationContext)
    return KtorPersonalSettingsRepository(ApiClientFactory(cookieVault))
}

/** Native administrative settings use the authenticated Cookie vault and never route through Web UI. */
fun createAndroidAdministrativeSettingsRepository(context: Context): AdministrativeSettingsRepository {
    val cookieVault = AndroidEncryptedCookieVault(context.applicationContext)
    return KtorAdministrativeSettingsRepository(ApiClientFactory(cookieVault))
}
