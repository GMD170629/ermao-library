package com.ermao.library.shared.modules.downloads

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.downloads.infrastructure.parseDownloadReaderType
import com.ermao.library.shared.modules.downloads.infrastructure.parseDownloadMediaKind
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
typealias DownloadCatalogRepository = com.ermao.library.shared.modules.downloads.application.DownloadCatalogRepository
typealias CompletedTransfer = com.ermao.library.shared.modules.downloads.application.CompletedTransfer
typealias DownloadDescriptor = com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
typealias DownloadIdentity = com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
typealias DownloadMediaKind = com.ermao.library.shared.modules.downloads.domain.DownloadMediaKind
typealias DownloadNamespace = com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
typealias DownloadProgressObserver = com.ermao.library.shared.modules.downloads.application.DownloadProgressObserver
typealias DownloadRequestContext = com.ermao.library.shared.modules.downloads.application.DownloadRequestContext
typealias DownloadReaderType = com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
typealias DownloadSinkRequest = com.ermao.library.shared.modules.downloads.application.DownloadSinkRequest
typealias DownloadSource = com.ermao.library.shared.modules.downloads.domain.DownloadSource
typealias DownloadTask = com.ermao.library.shared.modules.downloads.domain.DownloadTask
typealias DownloadTaskEvent = com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent
typealias DownloadTaskStatus = com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
typealias DownloadTransferGateway = com.ermao.library.shared.modules.downloads.application.DownloadTransferGateway
typealias DownloadTransferRequest = com.ermao.library.shared.modules.downloads.application.DownloadTransferRequest
typealias DownloadTransferResult = com.ermao.library.shared.modules.downloads.application.DownloadTransferResult
typealias DownloadTransferSuccess = com.ermao.library.shared.modules.downloads.application.DownloadTransferResult.Success
typealias DownloadTransferFailure = com.ermao.library.shared.modules.downloads.application.DownloadTransferResult.Failure
typealias DownloadsGateway = com.ermao.library.shared.modules.downloads.application.DownloadsGateway
typealias DownloadVolumeObservation = com.ermao.library.shared.modules.downloads.application.DownloadVolumeObservation
typealias DownloadVolumeObservationKind = com.ermao.library.shared.modules.downloads.application.DownloadVolumeObservationKind
typealias DownloadVolumeObserver = com.ermao.library.shared.modules.downloads.application.DownloadVolumeObserver
typealias DownloadVolumeResult = com.ermao.library.shared.modules.downloads.application.DownloadVolumeResult
typealias DownloadVolumeReadyToOpen = com.ermao.library.shared.modules.downloads.application.DownloadVolumeResult.ReadyToOpen
typealias DownloadVolumeFailure = com.ermao.library.shared.modules.downloads.application.DownloadVolumeResult.Failure
typealias DownloadVolumeRuntime = com.ermao.library.shared.modules.downloads.application.DownloadVolumeRuntime
typealias DownloadedMediaVersion = com.ermao.library.shared.modules.downloads.domain.DownloadedMediaVersion
typealias DownloadedWork = com.ermao.library.shared.modules.downloads.domain.DownloadedWork
typealias DownloadsRuntime = com.ermao.library.shared.modules.downloads.application.DownloadsRuntime
typealias InMemoryDownloadCatalogRepository = com.ermao.library.shared.modules.downloads.application.InMemoryDownloadCatalogRepository
typealias KtorDownloadsGateway = com.ermao.library.shared.modules.downloads.infrastructure.KtorDownloadsGateway
typealias ReaderAccessDecision = com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision
typealias ReaderLocalArtifact = com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision.LocalArtifact
typealias ReaderNeedsDownload = com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision.NeedsDownload
typealias ReaderRemoteStream = com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision.RemoteStream
typealias ReaderUnavailable = com.ermao.library.shared.modules.downloads.domain.ReaderAccessDecision.Unavailable
typealias ReaderAccessPolicy = com.ermao.library.shared.modules.downloads.domain.ReaderAccessPolicy
typealias ReaderAccessRequest = com.ermao.library.shared.modules.downloads.domain.ReaderAccessRequest

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

fun downloadMediaKind(value: String): DownloadMediaKind = parseDownloadMediaKind(value)

fun downloadStartEvent(): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.Start

fun downloadBytesTransferredEvent(totalTransferredBytes: Long): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.BytesTransferred(totalTransferredBytes)

fun downloadPauseEvent(): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.Pause

fun downloadResumeEvent(): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.Resume

fun downloadWaitForWifiEvent(): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.WaitForWifi

fun downloadInsufficientSpaceEvent(): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.ReportInsufficientSpace

fun downloadFailEvent(code: String, retryable: Boolean): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.Fail(code, retryable)

fun downloadCompleteEvent(artifact: CompletedDownloadArtifact): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.Complete(artifact)

fun downloadCancelEvent(): DownloadTaskEvent =
    com.ermao.library.shared.modules.downloads.domain.DownloadTaskEvent.Cancel

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

fun createDownloadVolumeRuntime(
    catalog: DownloadCatalogRepository,
    gateway: DownloadsGateway,
): DownloadVolumeRuntime = DownloadVolumeRuntime(catalog, gateway)
