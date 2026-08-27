package com.ermao.library.shared.bootstrap

import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.SecureCookiePayloadStore
import com.ermao.library.shared.core.network.SerializedCookieVault
import com.ermao.library.shared.modules.auth.MobileRuntimeBridge
import com.ermao.library.shared.modules.auth.application.DefaultMobileRuntime
import com.ermao.library.shared.modules.auth.application.DefaultMobileRuntimeBridge
import com.ermao.library.shared.modules.auth.infrastructure.KtorAuthGateway
import com.ermao.library.shared.modules.auth.infrastructure.SerializedVerifiedSessionRepository
import com.ermao.library.shared.modules.auth.infrastructure.VerifiedSessionPayloadStore
import com.ermao.library.shared.modules.servers.infrastructure.KtorServerProbe
import com.ermao.library.shared.modules.servers.infrastructure.SerializedServerProfileRepository
import com.ermao.library.shared.modules.servers.infrastructure.ServerProfilePayloadStore
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.infrastructure.KtorContentRepository
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.shared.modules.personalsettings.infrastructure.KtorPersonalSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.infrastructure.KtorAdministrativeSettingsRepository
import com.ermao.library.shared.modules.downloads.KtorDownloadsGateway
import com.ermao.library.shared.modules.downloads.createDownloadsGateway
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.shelf.infrastructure.KtorShelfRepository
import com.ermao.library.shared.modules.workmanagement.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.KtorWorkManagementRepository
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.reader.application.ReaderProgressServerPort
import com.ermao.library.shared.modules.reader.application.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.application.PdfRangeServerPort
import com.ermao.library.shared.modules.reader.application.ComicPageServerPort
import com.ermao.library.shared.modules.reader.application.ReaderServerGateway
import com.ermao.library.shared.modules.reader.infrastructure.KtorPdfRangeServerPort
import com.ermao.library.shared.modules.reader.infrastructure.KtorComicPageServerPort
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderProgressSyncPort
import com.ermao.library.shared.modules.reader.infrastructure.KtorReaderBookmarkSyncPort
import com.ermao.library.shared.modules.servers.domain.ServerProfile

/** Composition root for Swift. Cookie payloads must be backed by Keychain in iosApp. */
fun createIosMobileRuntimeBridge(
    cookieStore: SecureCookiePayloadStore,
    profileStore: ServerProfilePayloadStore,
    verifiedSessionStore: VerifiedSessionPayloadStore,
): MobileRuntimeBridge {
    val cookieVault = SerializedCookieVault(cookieStore)
    val profiles = SerializedServerProfileRepository(profileStore)
    val verifiedSessions = SerializedVerifiedSessionRepository(verifiedSessionStore)
    val clients = ApiClientFactory(cookieVault)
    val clientProvider = clients::create
    return DefaultMobileRuntimeBridge(
        DefaultMobileRuntime(
            profileRepository = profiles,
            cookieVault = cookieVault,
            verifiedSessionRepository = verifiedSessions,
            serverProbe = KtorServerProbe(clientProvider = clientProvider),
            authGateway = KtorAuthGateway(clients, clientProvider),
        ),
    )
}

/** Independent content composition; it shares the persisted authenticated Cookie vault. */
fun createIosContentRepository(
    cookieStore: SecureCookiePayloadStore,
): ContentRepository =
    KtorContentRepository(
        clients = ApiClientFactory(SerializedCookieVault(cookieStore)),
    )

fun createIosShelfRepository(
    cookieStore: SecureCookiePayloadStore,
): ShelfRepository = KtorShelfRepository(
    ApiClientFactory(SerializedCookieVault(cookieStore)),
)

fun createIosShelfCatalogRepository(
    cookieStore: SecureCookiePayloadStore,
): com.ermao.library.shared.modules.shelf.ShelfCatalogRepository =
    com.ermao.library.shared.modules.shelf.infrastructure.KtorShelfCatalogRepository(
        ApiClientFactory(SerializedCookieVault(cookieStore)),
    )

fun createIosWorkManagementRepository(
    cookieStore: SecureCookiePayloadStore,
): WorkManagementRepository = KtorWorkManagementRepository(
    ApiClientFactory(SerializedCookieVault(cookieStore)),
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

/** Shared Reader v4 bootstrap/download mapper; publication bytes still terminate in a native sink. */
fun createIosReaderBootstrapGateway(
    cookieStore: SecureCookiePayloadStore,
): ReaderServerGateway =
    KtorReaderBootstrapGateway(
        ApiClientFactory(SerializedCookieVault(cookieStore)),
    )

fun createIosPdfRangeServerPort(
    cookieStore: SecureCookiePayloadStore,
    profile: ServerProfile,
): PdfRangeServerPort = KtorPdfRangeServerPort(
    profile,
    ApiClientFactory(SerializedCookieVault(cookieStore)),
)

fun createIosComicPageServerPort(
    cookieStore: SecureCookiePayloadStore,
    profile: ServerProfile,
): ComicPageServerPort = KtorComicPageServerPort(
    profile,
    ApiClientFactory(SerializedCookieVault(cookieStore)),
)

/** Shared Reader v4 best-effort progress wire; exact local storage remains native. */
fun createIosReaderProgressSyncPort(
    cookieStore: SecureCookiePayloadStore,
    profile: ServerProfile,
): ReaderProgressServerPort =
    KtorReaderProgressSyncPort(
        clients = ApiClientFactory(SerializedCookieVault(cookieStore)),
        profile = profile,
    )

fun createIosReaderBookmarkSyncPort(
    cookieStore: SecureCookiePayloadStore,
    profile: ServerProfile,
): ReaderBookmarkSyncPort =
    KtorReaderBookmarkSyncPort(
        clients = ApiClientFactory(SerializedCookieVault(cookieStore)),
        profile = profile,
    )

/** Download bootstrap and streaming transfer reuse the Keychain-backed authenticated Cookie jar. */
fun createIosDownloadsGateway(
    cookieStore: SecureCookiePayloadStore,
    profile: ServerProfile,
): KtorDownloadsGateway = createDownloadsGateway(
    ApiClientFactory(SerializedCookieVault(cookieStore)),
    profile,
)

/** Flat Swift boundary; native code never needs to construct ServerBaseUrl. */
fun createIosDownloadsGateway(
    cookieStore: SecureCookiePayloadStore,
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
): KtorDownloadsGateway {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return createIosDownloadsGateway(
        cookieStore = cookieStore,
        profile = ServerProfile(
            id = profileId,
            displayName = displayName,
            baseUrl = parsed.baseUrl,
            serverIdentity = serverIdentity,
            isActive = true,
            tlsMode = if (acceptsInsecureTls) {
                TlsMode.InsecureSkipAllValidation
            } else {
                TlsMode.SystemTrust
            },
        ),
    )
}
