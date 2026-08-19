package com.ermao.library.shared.modules.workmanagement

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode

typealias WorkManagementRepository =
    com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
typealias KtorWorkManagementRepository =
    com.ermao.library.shared.modules.workmanagement.infrastructure.KtorWorkManagementRepository
typealias WorkManagementContext =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementContext
typealias WorkManagementResult<T> =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult<T>
typealias WorkManagementError =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
typealias WorkManagementErrorKind =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
typealias WorkMetadataDraft =
    com.ermao.library.shared.modules.workmanagement.domain.WorkMetadataDraft
typealias VolumeMetadataDraft =
    com.ermao.library.shared.modules.workmanagement.domain.VolumeMetadataDraft
typealias ManagedMediaKind =
    com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
typealias ManagedReadingStatus =
    com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
typealias WorkMutationOutcome =
    com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome
typealias MetadataProvider =
    com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
typealias MetadataField =
    com.ermao.library.shared.modules.workmanagement.domain.MetadataField
typealias MetadataCandidate =
    com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
typealias MetadataSearchResult =
    com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
typealias CoverUpload =
    com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
typealias KindleSettings =
    com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
typealias KindleSendOutcome =
    com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome

/** Swift-friendly construction boundary matching the authenticated content context. */
fun createWorkManagementContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
    userId: String,
    authorizationVersion: Long,
): WorkManagementContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return WorkManagementContext(
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
