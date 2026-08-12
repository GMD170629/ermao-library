package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.library.domain.WorkDetail
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.library.domain.MediaKind
import com.ermao.library.shared.modules.library.infrastructure.WorkDetailPayloadWire
import com.ermao.library.shared.modules.library.infrastructure.WorkDetailSummaryPayloadWire
import com.ermao.library.shared.modules.library.infrastructure.WorkSummaryWire
import com.ermao.library.shared.modules.library.infrastructure.toDomain
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode

/** Stable capability boundary; platform code does not import library infrastructure mappers directly. */
object LibraryContract {
    fun workSummary(wire: WorkSummaryWire): WorkSummary = wire.toDomain()

    fun workDetailSummary(wire: WorkDetailSummaryPayloadWire): WorkDetailSummary = wire.toDomain()

    fun workDetail(wire: WorkDetailPayloadWire): WorkDetail = wire.toDomain()
}

/** Swift-friendly construction boundary; invalid or mismatched contexts are rejected. */
fun createContentRequestContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
    userId: String,
    authorizationVersion: Long,
): ContentRequestContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return ContentRequestContext(
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

/** Swift cannot safely construct Kotlin inline value classes through erased `Any` collections. */
fun createLibraryFilters(
    mediaKindWireValues: List<String>,
    readingStatuses: Set<ReadingStatus>,
): LibraryFilters = LibraryFilters(
    mediaKinds = mediaKindWireValues.map(::MediaKind).toSet(),
    readingStatuses = readingStatuses,
    downloadedOnly = false,
)
