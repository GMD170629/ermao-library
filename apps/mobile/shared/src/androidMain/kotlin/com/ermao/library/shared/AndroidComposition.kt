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
import com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.application.ReaderProgressServerPort
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.application.ComicPageServerPort
import com.ermao.library.shared.modules.reader.application.ReaderServerGateway
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderProgressSyncPort
import com.ermao.library.shared.modules.reader.infrastructure.KtorPdfRangeServerPort
import com.ermao.library.shared.modules.reader.infrastructure.KtorComicPageServerPort
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderBookmarkSyncPort
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.shelf.infrastructure.KtorShelfRepository
import com.ermao.library.shared.modules.servers.domain.ServerProfile

fun createAndroidMobileRuntime(
    context: Context,
    profileRepository: ServerProfileRepository,
    entitlementRepository: OfflineEntitlementRepository,
): MobileRuntime {
    val applicationContext = context.applicationContext
    val cookieVault = AndroidEncryptedCookieVault(applicationContext)
    val clients = ApiClientFactory(
        cookieVault = cookieVault,
        requestTimeoutMillis = 15_000,
        connectTimeoutMillis = 5_000,
    )
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

fun createAndroidShelfRepository(context: Context): ShelfRepository =
    KtorShelfRepository(
        ApiClientFactory(AndroidEncryptedCookieVault(context.applicationContext)),
    )

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

fun createAndroidReaderServerGateway(context: Context): ReaderServerGateway =
    KtorReaderBootstrapGateway(
        ApiClientFactory(AndroidEncryptedCookieVault(context.applicationContext)),
    )

fun createAndroidPdfRangeServerPort(
    context: Context,
    profile: ServerProfile,
): PdfRangeServerPort = KtorPdfRangeServerPort(
    profile,
    ApiClientFactory(AndroidEncryptedCookieVault(context.applicationContext)),
)

fun createAndroidComicPageServerPort(
    context: Context,
    profile: ServerProfile,
): ComicPageServerPort = KtorComicPageServerPort(
    profile,
    ApiClientFactory(AndroidEncryptedCookieVault(context.applicationContext)),
)

fun createAndroidReaderProgressSyncPort(
    context: Context,
    profile: ServerProfile,
): ReaderProgressServerPort =
    KtorReaderProgressSyncPort(
        clients = ApiClientFactory(AndroidEncryptedCookieVault(context.applicationContext)),
        profile = profile,
    )

fun createAndroidReaderBookmarkSyncPort(
    context: Context,
    profile: ServerProfile,
): ReaderBookmarkSyncPort =
    KtorReaderBookmarkSyncPort(
        clients = ApiClientFactory(AndroidEncryptedCookieVault(context.applicationContext)),
        profile = profile,
    )
