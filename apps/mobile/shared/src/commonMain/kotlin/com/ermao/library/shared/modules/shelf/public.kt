package com.ermao.library.shared.modules.shelf

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext

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
