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
typealias ManagedReadingStatus =
    com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
typealias BookMutationOutcome =
    com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
typealias BookDeletionOutcome =
    com.ermao.library.shared.modules.workmanagement.domain.BookDeletionOutcome
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
typealias CoverMutationOutcome =
    com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome
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

/** Stable Swift bridge; avoids relying on erased Kotlin generic casts for Unit results. */
fun workManagementResultSucceeded(result: WorkManagementResult<*>): Boolean =
    result is com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content

fun workManagementResultErrorCode(result: WorkManagementResult<*>): String? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Failure)?.error?.code

fun workManagementBookDeletionOutcome(
    result: WorkManagementResult<BookDeletionOutcome>,
): BookDeletionOutcome? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

fun workManagementBooleanValue(result: WorkManagementResult<Boolean>): Boolean? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

fun workManagementMetadataProviders(
    result: WorkManagementResult<List<MetadataProvider>>,
): List<MetadataProvider>? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

fun workManagementMetadataSearchResult(
    result: WorkManagementResult<MetadataSearchResult>,
): MetadataSearchResult? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

fun workManagementKindleSettings(
    result: WorkManagementResult<KindleSettings>,
): KindleSettings? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

fun workManagementBookMutationOutcome(
    result: WorkManagementResult<BookMutationOutcome>,
): BookMutationOutcome? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

fun workManagementCoverMutationOutcome(
    result: WorkManagementResult<CoverMutationOutcome>,
): CoverMutationOutcome? =
    (result as? com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult.Content)?.value

typealias ManagementObject = com.ermao.library.shared.modules.workmanagement.domain.ManagementObject

typealias ManagementTarget = com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget

typealias ManagementAction = com.ermao.library.shared.modules.workmanagement.domain.ManagementAction

typealias ManagementMenuItem = com.ermao.library.shared.modules.workmanagement.domain.ManagementMenuItem

typealias ManagementField = com.ermao.library.shared.modules.workmanagement.domain.ManagementField

typealias ManagementFieldValue = com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue

typealias ManagedBook = com.ermao.library.shared.modules.workmanagement.domain.ManagedBook

typealias ManagedAsset = com.ermao.library.shared.modules.workmanagement.domain.ManagedAsset

typealias ManagedResource = com.ermao.library.shared.modules.workmanagement.domain.ManagedResource

typealias ManagedDirectory = com.ermao.library.shared.modules.workmanagement.domain.ManagedDirectory

typealias ManagementSnapshot = com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot

typealias CoverEdit = com.ermao.library.shared.modules.workmanagement.domain.CoverEdit

typealias RecognizedField = com.ermao.library.shared.modules.workmanagement.domain.RecognizedField

typealias MetadataApplyOutcome = com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome

typealias ManagementSaveStage = com.ermao.library.shared.modules.workmanagement.domain.ManagementSaveStage

typealias ManagementChange = com.ermao.library.shared.modules.workmanagement.domain.ManagementChange

typealias BookManagementSession = com.ermao.library.shared.modules.workmanagement.application.BookManagementSession

typealias ManagementSessionState = com.ermao.library.shared.modules.workmanagement.application.ManagementSessionState

typealias ManagementPhase = com.ermao.library.shared.modules.workmanagement.application.ManagementPhase

typealias ManagementOperation = com.ermao.library.shared.modules.workmanagement.application.ManagementOperation

fun managementCandidateValue(candidate: MetadataCandidate, field: ManagementField): String =
    com.ermao.library.shared.modules.workmanagement.application.candidateValue(candidate, field)

fun managementMenuItems(kind: ManagementObject, canManage: Boolean, kindleSendAvailable: Boolean, hasRepresentativeResource: Boolean): List<ManagementMenuItem> =
    com.ermao.library.shared.modules.workmanagement.domain.managementActions(kind, canManage, kindleSendAvailable, hasRepresentativeResource)

typealias ManagementMenuContext = com.ermao.library.shared.modules.workmanagement.domain.ManagementMenuContext
