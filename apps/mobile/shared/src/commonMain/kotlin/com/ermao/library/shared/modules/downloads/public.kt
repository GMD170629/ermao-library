package com.ermao.library.shared.modules.downloads

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.downloads.infrastructure.parseDownloadReaderType
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.TlsMode

typealias CompletedDownloadArtifact = com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
typealias DownloadBootstrap = com.ermao.library.shared.modules.downloads.application.DownloadBootstrap
typealias DownloadBootstrapGateway = com.ermao.library.shared.modules.downloads.application.DownloadBootstrapGateway
typealias DownloadBootstrapResult = com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult
typealias DownloadBootstrapSuccess = com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult.Success
typealias DownloadBootstrapFailure = com.ermao.library.shared.modules.downloads.application.DownloadBootstrapResult.Failure
typealias DownloadByteSink = com.ermao.library.shared.modules.downloads.application.DownloadByteSink
typealias DownloadByteSinkSession = com.ermao.library.shared.modules.downloads.application.DownloadByteSinkSession
typealias DownloadBundleByteSink = com.ermao.library.shared.modules.downloads.application.DownloadBundleByteSink
typealias DownloadBundleByteSinkSession = com.ermao.library.shared.modules.downloads.application.DownloadBundleByteSinkSession
typealias DownloadBundleSinkRequest = com.ermao.library.shared.modules.downloads.application.DownloadBundleSinkRequest
typealias DownloadBundleMemberSinkRequest = com.ermao.library.shared.modules.downloads.application.DownloadBundleMemberSinkRequest
typealias DownloadCatalogCodec = com.ermao.library.shared.modules.downloads.infrastructure.DownloadCatalogCodec
typealias DownloadCatalogRepository = com.ermao.library.shared.modules.downloads.application.DownloadCatalogRepository
typealias CompletedTransfer = com.ermao.library.shared.modules.downloads.application.CompletedTransfer
typealias DownloadDescriptor = com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
typealias DownloadArtifactKind = com.ermao.library.shared.modules.downloads.domain.DownloadArtifactKind
typealias DownloadBundleMember = com.ermao.library.shared.modules.downloads.domain.DownloadBundleMember
typealias DownloadIdentity = com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
typealias DownloadNamespace = com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
typealias DownloadProgressObserver = com.ermao.library.shared.modules.downloads.application.DownloadProgressObserver
typealias DownloadRequestContext = com.ermao.library.shared.modules.downloads.application.DownloadRequestContext
typealias DownloadReaderType = com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
typealias DownloadSinkRequest = com.ermao.library.shared.modules.downloads.application.DownloadSinkRequest
typealias DownloadSource = com.ermao.library.shared.modules.downloads.domain.DownloadSource
typealias DownloadTask = com.ermao.library.shared.modules.downloads.domain.DownloadTask
typealias DownloadTaskEvent = com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
typealias DownloadTaskStatus = com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
typealias MultiDownloadEligibility = com.ermao.library.shared.modules.downloads.domain.MultiDownloadEligibility
typealias MultiDownloadResourceState = com.ermao.library.shared.modules.downloads.domain.MultiDownloadResourceState
typealias MultiDownloadSelectionMark = com.ermao.library.shared.modules.downloads.domain.MultiDownloadSelectionMark
typealias MultiDownloadSelectionState = com.ermao.library.shared.modules.downloads.domain.MultiDownloadSelectionState
typealias DownloadBatchPolicy = com.ermao.library.shared.modules.downloads.domain.DownloadBatchPolicy
typealias DownloadBatchCommand = com.ermao.library.shared.modules.downloads.domain.DownloadBatchCommand
typealias DownloadBatchOutcomeKind = com.ermao.library.shared.modules.downloads.domain.DownloadBatchOutcomeKind
typealias DownloadBatchResourceResult = com.ermao.library.shared.modules.downloads.domain.DownloadBatchResourceResult
typealias DownloadBatchResult = com.ermao.library.shared.modules.downloads.domain.DownloadBatchResult
typealias DownloadBatchSummary = com.ermao.library.shared.modules.downloads.domain.DownloadBatchSummary
typealias DownloadTransferGateway = com.ermao.library.shared.modules.downloads.application.DownloadTransferGateway
typealias DownloadTransferRequest = com.ermao.library.shared.modules.downloads.application.DownloadTransferRequest
typealias DownloadTransferResult = com.ermao.library.shared.modules.downloads.application.DownloadTransferResult
typealias DownloadTransferSuccess = com.ermao.library.shared.modules.downloads.application.DownloadTransferResult.Success
typealias DownloadTransferFailure = com.ermao.library.shared.modules.downloads.application.DownloadTransferResult.Failure
typealias DownloadsGateway = com.ermao.library.shared.modules.downloads.application.DownloadsGateway
typealias DownloadResourceObservation = com.ermao.library.shared.modules.downloads.application.DownloadResourceObservation
typealias DownloadResourceObservationKind = com.ermao.library.shared.modules.downloads.application.DownloadResourceObservationKind
typealias DownloadCancellation = com.ermao.library.shared.modules.downloads.application.DownloadCancellation
typealias DownloadResourceObserver = com.ermao.library.shared.modules.downloads.application.DownloadResourceObserver
typealias DownloadResourceResult = com.ermao.library.shared.modules.downloads.application.DownloadResourceResult
typealias DownloadResourceCompleted = com.ermao.library.shared.modules.downloads.application.DownloadResourceResult.Completed
typealias DownloadResourceFailure = com.ermao.library.shared.modules.downloads.application.DownloadResourceResult.Failure
typealias DownloadResourceRuntime = com.ermao.library.shared.modules.downloads.application.DownloadResourceRuntime
typealias DownloadedResource = com.ermao.library.shared.modules.downloads.domain.DownloadedResource
typealias DownloadedBook = com.ermao.library.shared.modules.downloads.domain.DownloadedBook
typealias DownloadsRuntime = com.ermao.library.shared.modules.downloads.application.DownloadsRuntime
typealias InMemoryDownloadCatalogRepository = com.ermao.library.shared.modules.downloads.application.InMemoryDownloadCatalogRepository
typealias KtorDownloadsGateway = com.ermao.library.shared.modules.downloads.infrastructure.KtorDownloadsGateway

fun createDownloadNamespace(
    serverIdentity: String,
    userId: String,
    authorizationVersion: Long,
): DownloadNamespace = DownloadNamespace(serverIdentity, userId, authorizationVersion)

fun PrivateDataNamespace.toDownloadNamespace(): DownloadNamespace = DownloadNamespace(
    serverIdentity = serverIdentity,
    userId = userId,
    authorizationVersion = authorizationVersion,
)

fun downloadReaderType(value: String): DownloadReaderType = parseDownloadReaderType(value)

fun summarizeDownloadBatch(
    selectedResourceIds: Set<String>,
    resourcesById: Map<String, MultiDownloadResourceState>,
): DownloadBatchSummary = com.ermao.library.shared.modules.downloads.domain.summarizeDownloadBatch(
    selectedResourceIds,
    resourcesById,
)

/** Swift-friendly request context; rejects invalid server identities and namespaces. */
fun createDownloadRequestContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
    userId: String,
    authorizationVersion: Long,
): DownloadRequestContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return DownloadRequestContext(
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
        namespace = createDownloadNamespace(serverIdentity, userId, authorizationVersion),
    )
}

fun createDownloadsGateway(
    apiClientFactory: ApiClientFactory,
    profile: ServerProfile,
): KtorDownloadsGateway = KtorDownloadsGateway(apiClientFactory.create(profile))

fun createDownloadResourceRuntime(
    catalog: DownloadCatalogRepository,
    gateway: DownloadsGateway,
): DownloadResourceRuntime = DownloadResourceRuntime(catalog, gateway)

typealias DownloadStoredBytes = com.ermao.library.shared.modules.downloads.application.DownloadStoredBytes
