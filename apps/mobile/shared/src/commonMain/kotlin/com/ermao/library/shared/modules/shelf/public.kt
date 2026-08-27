package com.ermao.library.shared.modules.shelf

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext

typealias ShelfCatalogRepository = com.ermao.library.shared.modules.shelf.application.ShelfCatalogRepository
typealias ShelfCatalogEntry = com.ermao.library.shared.modules.shelf.domain.ShelfCatalogEntry
typealias ShelfCatalogPage = com.ermao.library.shared.modules.shelf.domain.ShelfCatalogPage
typealias ShelfBookPreview = com.ermao.library.shared.modules.shelf.domain.ShelfBookPreview
typealias ShelfCatalogScope = com.ermao.library.shared.modules.shelf.domain.ShelfCatalogScope
typealias CreateShelfInput = com.ermao.library.shared.modules.shelf.domain.CreateShelfInput
typealias ShelfKind = com.ermao.library.shared.modules.shelf.domain.ShelfKind
typealias ShelfErrorKind = com.ermao.library.shared.modules.shelf.domain.ShelfErrorKind
typealias ShelfError = com.ermao.library.shared.modules.shelf.domain.ShelfError

fun catalogEntries(
    entries: List<ShelfCatalogEntry>, scope: ShelfCatalogScope, query: String, collectionId: String? = null,
): List<ShelfCatalogEntry> = com.ermao.library.shared.modules.shelf.domain.filterShelfCatalog(entries, scope, query, collectionId)

fun catalogPreview(entry: ShelfCatalogEntry, entries: List<ShelfCatalogEntry>): List<ShelfBookPreview> =
    com.ermao.library.shared.modules.shelf.domain.shelfPreviewBooks(entry, entries)

fun createShelfRequestContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
    userId: String,
    authorizationVersion: Long,
): ShelfRequestContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return ShelfRequestContext(
        profile = ServerProfile(
            id = profileId,
            displayName = displayName,
            baseUrl = parsed.baseUrl,
            serverIdentity = serverIdentity,
            isActive = true,
            tlsMode = if (acceptsInsecureTls) TlsMode.InsecureSkipAllValidation else TlsMode.SystemTrust,
        ),
        namespace = PrivateDataNamespace(serverIdentity, userId, authorizationVersion),
    )
}
