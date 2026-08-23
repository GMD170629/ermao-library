package com.ermao.library.shared.modules.workmanagement

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode

typealias WorkManagementRepository =
    com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
typealias BookManagementRepository =
    com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
typealias KtorWorkManagementRepository =
    com.ermao.library.shared.modules.workmanagement.infrastructure.KtorWorkManagementRepository
typealias KtorBookManagementRepository =
    com.ermao.library.shared.modules.workmanagement.infrastructure.KtorWorkManagementRepository
typealias BookManagementContext =
    com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
typealias WorkManagementResult<T> =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult<T>
typealias WorkManagementError =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
typealias WorkManagementErrorKind =
    com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
typealias BookMetadataDraft =
    com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
typealias ResourceMetadataDraft =
    com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
typealias ManagedMediaKind =
    com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
typealias ManagedReadingStatus =
    com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
typealias BookMutationOutcome =
    com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
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
): BookManagementContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return BookManagementContext(
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
