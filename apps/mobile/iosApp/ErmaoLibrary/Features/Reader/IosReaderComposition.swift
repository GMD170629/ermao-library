import Foundation
import SwiftUI
@preconcurrency import ErmaoShared

struct IosReaderLaunchRequest: Identifiable, Equatable, Sendable {
    let context: ContentRequestContext
    let workID: String
    let volumeID: String
    let displayTitle: String
    let managedDownloadRecordID: String?

    init(
        context: ContentRequestContext,
        workID: String,
        volumeID: String,
        displayTitle: String,
        managedDownloadRecordID: String? = nil
    ) {
        self.context = context
        self.workID = workID
        self.volumeID = volumeID
        self.displayTitle = displayTitle
        self.managedDownloadRecordID = managedDownloadRecordID
    }

    var id: String { "\(context.namespaceKey)|\(volumeID)" }
}

struct IosReaderDownloadArtifact: Sendable {
    let fileURL: URL
    let sourceID: String
    let displayTitle: String
    let workID: String
    let volumeID: String
    let sourceFormat: String
    let serverContentFingerprint: String
}

protocol IosReaderDownloadArtifactProviding: Sendable {
    func verifiedReaderArtifact(recordID: String, namespace: String) async throws -> IosReaderDownloadArtifact?
}

struct IosReaderStartupConflict {
    let progress: ErmaoShared.ReaderProgress
    let mutation: ErmaoShared.ReaderProgressMutation
    let server: ErmaoShared.ReaderProgressSnapshotV4
}

extension ManagedDownloadStore: IosReaderDownloadArtifactProviding {}

@MainActor
final class IosReaderComposition: ObservableObject {
    private let cookieStore: KeychainCookiePayloadStore
    private let managedStore: IosManagedPublicationStore
    private let deviceIdentity: IosReaderDeviceIdentity
    private let downloadArtifacts: any IosReaderDownloadArtifactProviding
    private let pdfPageCounts = IosPdfPageCountStore()

    init(
        cookieStore: KeychainCookiePayloadStore,
        downloadArtifacts: any IosReaderDownloadArtifactProviding
    ) throws {
        self.cookieStore = cookieStore
        self.downloadArtifacts = downloadArtifacts
        managedStore = try IosManagedPublicationStore()
        deviceIdentity = IosReaderDeviceIdentity()
    }

    func makeHost(request: IosReaderLaunchRequest) -> IosReaderBootstrapHost {
        IosReaderBootstrapHost(request: request, composition: self)
    }

    fileprivate func bootstrap(_ request: IosReaderLaunchRequest) async throws -> IosReaderSession {
        let namespace = ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: request.context.serverIdentity,
            userId: request.context.userID,
            authorizationVersion: request.context.authorizationVersion
        )
        let profile = ErmaoShared.PublicKt.createReaderServerProfile(
            id: request.context.profileID,
            displayName: request.context.profileDisplayName,
            baseUrl: request.context.baseURL,
            serverIdentity: request.context.serverIdentity,
            isActive: true,
            acceptsInsecureTls: request.context.acceptsInsecureTLS
        )
        let gateway = IosCompositionKt.createIosReaderBootstrapGateway(cookieStore: cookieStore)
        let launchArtifact: IosReaderDownloadArtifact?
        if let recordID = request.managedDownloadRecordID {
            guard let artifact = try await downloadArtifacts.verifiedReaderArtifact(
                recordID: recordID,
                namespace: request.context.namespaceKey
            ), artifact.sourceID == request.volumeID else {
                throw IosReaderFailure(code: .resourceMissing)
            }
            launchArtifact = artifact
        } else {
            launchArtifact = nil
        }
        let bootstrapRequest = ErmaoShared.ReaderBootstrapRequest(
            profile: profile,
            namespace: namespace,
            volumeId: request.volumeID
        )
        let result: ErmaoShared.ReaderBootstrapResult?
        do {
            result = try await gateway.load(request: bootstrapRequest)
        } catch {
            result = nil
        }
        if let failure = result as? ErmaoShared.ReaderBootstrapResultFailure,
           !failure.recoverable {
            throw IosReaderFailure(code: .resourceMissing)
        }
        let onlineBootstrap = (result as? ErmaoShared.ReaderBootstrapResultContent)?.value
        let target: ErmaoShared.ReaderProgressSyncTarget
        let exactSourceFormat: ErmaoShared.ReaderSourceFormat
        let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
        let source: ErmaoShared.ReaderSource
        let bookmarkContentFingerprint: String
        if let onlineBootstrap {
            target = onlineBootstrap.target
            exactSourceFormat = onlineBootstrap.publication.sourceFormat
            guard Self.hasCompleteReaderEngine(for: exactSourceFormat) else {
                throw IosReaderFailure(code: .unsupportedFormat)
            }
            remoteSnapshot = onlineBootstrap.remoteSnapshot
            bookmarkContentFingerprint = onlineBootstrap.artifactVersion
            if let launchArtifact {
                if launchArtifact.serverContentFingerprint == onlineBootstrap.artifactVersion,
                   let artifactFormat = IosManagedPublicationStore.sourceFormat(
                       launchArtifact.sourceFormat
                   ),
                   artifactFormat == onlineBootstrap.publication.sourceFormat {
                    _ = try await managedStore.importPublication(
                        from: launchArtifact.fileURL,
                        sourceID: launchArtifact.sourceID,
                        displayTitle: launchArtifact.displayTitle,
                        sourceFormat: artifactFormat,
                        workID: launchArtifact.workID,
                        volumeID: launchArtifact.volumeID,
                        expectedOriginalFileHash: onlineBootstrap.publication.publicationFingerprint.originalFileHash,
                        parserVersion: onlineBootstrap.publication.publicationFingerprint.parser,
                        normalizationVersion: onlineBootstrap.publication.publicationFingerprint.normalization
                    )
                    try await managedStore.bindServerContentFingerprint(
                        sourceID: launchArtifact.sourceID,
                        value: launchArtifact.serverContentFingerprint
                    )
                }
            }
            let existing = try? await managedStore.resolve(sourceID: request.volumeID)
            if let existing,
               existing.serverContentFingerprint == onlineBootstrap.artifactVersion,
               existing.sourceFormat == onlineBootstrap.publication.sourceFormat,
               existing.fingerprint.originalFileHash.caseInsensitiveCompare(
                   onlineBootstrap.publication.publicationFingerprint.originalFileHash
               ) == .orderedSame,
               existing.fingerprint.parserVersion == onlineBootstrap.publication.publicationFingerprint.parser,
               existing.fingerprint.normalizationVersion == onlineBootstrap.publication.publicationFingerprint.normalization {
                source = Self.sharedSource(existing)
            } else {
                source = try await download(bootstrap: onlineBootstrap, gateway: gateway)
            }
            try await managedStore.bindServerContentFingerprint(
                sourceID: request.volumeID,
                value: onlineBootstrap.artifactVersion
            )
        } else {
            // Offline opening is allowed only for a previously verified managed
            // publication whose server version was durably bound at bootstrap.
            let existing = try await managedStore.resolve(sourceID: request.volumeID)
            guard existing.serverContentFingerprint != nil else {
                throw IosReaderFailure(code: .networkUnavailable)
            }
            target = ErmaoShared.ReaderProgressSyncTarget(
                namespace: namespace,
                workId: request.workID,
                volumeId: request.volumeID,
                sourceFormat: existing.sourceFormat.readerFormat
            )
            exactSourceFormat = existing.sourceFormat
            guard Self.hasCompleteReaderEngine(for: exactSourceFormat) else {
                throw IosReaderFailure(code: .unsupportedFormat)
            }
            remoteSnapshot = nil
            bookmarkContentFingerprint = existing.serverContentFingerprint!
            source = Self.sharedSource(existing)
        }

        guard source.sourceId == target.volumeId,
              source.sourceFormat == exactSourceFormat,
              source.format == target.sourceFormat,
              exactSourceFormat.readerFormat == target.sourceFormat
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let localIdentity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: deviceIdentity.stableDeviceId(),
            workId: target.workId,
            volumeId: target.volumeId
        )
        let database = try IosReaderLocalDatabase(
            identity: localIdentity
        )
        let serverPort = IosCompositionKt.createIosReaderProgressSyncPort(
            cookieStore: cookieStore,
            profile: profile
        )
        let progressRuntime = ErmaoShared.PublicKt.createReaderProgressSyncRuntime(
            stateStore: database,
            target: target,
            server: serverPort
        )
        let progressStore = progressRuntime.store
        let localProgress = try await database.load(sourceId: source.sourceId)
        let durableState = try await database.loadSyncState()
        let startupDecision = ErmaoShared.PublicKt.decidePendingVsServerStartup(
            localProgress: localProgress,
            durableState: durableState,
            remoteSnapshot: remoteSnapshot,
            openedSource: source
        )
        var sessionRemoteSnapshot = remoteSnapshot
        var startupConflict: IosReaderStartupConflict?
        var shouldRetryStartupPending = false
        if let useServer = startupDecision as? ErmaoShared.PendingVsServerDecisionUseServer,
           useServer.discardPending,
           let pending = durableState.pending {
            try await database.discardPendingAfterConflict(
                mutationId: pending.mutationId,
                serverRevision: useServer.snapshot?.revision ?? durableState.confirmedRevision
            )
        } else if startupDecision is ErmaoShared.PendingVsServerDecisionUseLocalPending {
            sessionRemoteSnapshot = nil
            shouldRetryStartupPending = true
        } else if let choice = startupDecision as? ErmaoShared.PendingVsServerDecisionRequiresChoice {
            startupConflict = IosReaderStartupConflict(
                progress: choice.progress,
                mutation: choice.mutation,
                server: choice.server
            )
        }
        let progressCoordination = IosReaderProgressSessionCoordination(
            runtime: progressRuntime,
            database: database,
            target: target,
            server: serverPort,
            clientID: localIdentity.clientId,
            bootstrapSnapshot: remoteSnapshot
        )
        if shouldRetryStartupPending {
            try? await progressStore.retryPendingUpload()
        }
        let preferencesStore = IosReaderPreferencesStore(
            serverIdentity: request.context.serverIdentity,
            userID: request.context.userID
        )
        let bookmarkStore = IosReaderBookmarkStore(
            serverIdentity: request.context.serverIdentity,
            userID: request.context.userID,
            volumeID: source.sourceId,
            contentFingerprint: bookmarkContentFingerprint
        )
        let bookmarkSyncPort = IosCompositionKt.createIosReaderBookmarkSyncPort(
            cookieStore: cookieStore,
            profile: profile
        )
        if exactSourceFormat == .cbz {
            let pages: [IosCbzPage]
            if let onlineBootstrap {
                guard !onlineBootstrap.comicPages.isEmpty else {
                    throw IosReaderFailure(code: .corruptFile)
                }
                pages = onlineBootstrap.comicPages.map {
                    IosCbzPage(
                        pageIndex: Int($0.pageIndex),
                        resourceHref: $0.resourceHref,
                        mediaType: $0.mediaType,
                        width: $0.width.map { Int($0.intValue) },
                        height: $0.height.map { Int($0.intValue) }
                    )
                }
            } else {
                let managed = try await managedStore.resolve(sourceID: source.sourceId)
                pages = try IosCbzArchiveIndex(fileURL: managed.fileURL).pages
            }
            return .comic(IosComicReaderSession(
                sourceID: source.sourceId,
                displayTitle: source.displayTitle,
                pages: pages,
                managedStore: managedStore,
                progressStore: progressStore,
                progressCoordination: progressCoordination,
                remoteSnapshot: sessionRemoteSnapshot,
                startupConflict: startupConflict,
                namespaceKey: request.context.namespaceKey,
                workID: request.workID,
                publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
                deviceIdentity: deviceIdentity
            ))
        }
        if exactSourceFormat == .pdf {
            let canonicalPageCount: Int
            if let onlineBootstrap {
                guard let value = onlineBootstrap.pageCount?.intValue, value > 0 else {
                    throw IosReaderFailure(code: .corruptFile)
                }
                canonicalPageCount = value
                pdfPageCounts.save(
                    pageCount: value,
                    sourceID: source.sourceId,
                    fingerprint: IosContentFingerprint(shared: source.contentFingerprint)
                )
            } else {
                guard let value = pdfPageCounts.load(
                    sourceID: source.sourceId,
                    fingerprint: IosContentFingerprint(shared: source.contentFingerprint)
                ) else {
                    throw IosReaderFailure(code: .resourceMissing)
                }
                canonicalPageCount = value
            }
            return .pdf(IosPdfReaderSession(
                sourceID: source.sourceId,
                displayTitle: source.displayTitle,
                canonicalPageCount: canonicalPageCount,
                managedStore: managedStore,
                progressStore: progressStore,
                progressCoordination: progressCoordination,
                remoteSnapshot: sessionRemoteSnapshot,
                startupConflict: startupConflict,
                namespaceKey: request.context.namespaceKey,
                workID: request.workID,
                publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
                deviceIdentity: deviceIdentity
            ))
        }
        return .reflowable(IosReflowableReaderSession(
            sourceID: source.sourceId,
            displayTitle: source.displayTitle,
            sourceFormat: exactSourceFormat,
            preferences: preferencesStore.load(),
            managedStore: managedStore,
            progressStore: progressStore,
            progressCoordination: progressCoordination,
            preferencesStore: preferencesStore,
            bookmarkStore: bookmarkStore,
            bookmarkSyncPort: bookmarkSyncPort,
            bookmarkSyncTarget: ErmaoShared.ReaderBookmarkSyncTarget(
                serverIdentity: request.context.serverIdentity,
                volumeId: source.sourceId,
                contentFingerprint: bookmarkContentFingerprint
            ),
            remoteSnapshot: sessionRemoteSnapshot,
            startupConflict: startupConflict,
            namespaceKey: request.context.namespaceKey,
            workID: request.workID,
            publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
            deviceIdentity: deviceIdentity
        ))
    }

    private static func sharedSource(_ existing: IosManagedPublication) -> ErmaoShared.ReaderSource {
        ErmaoShared.LocalReaderSource(
            sourceId: existing.sourceID,
            displayTitle: existing.displayTitle,
            format: existing.sourceFormat.readerFormat,
            contentFingerprint: ErmaoShared.ContentFingerprint(
                originalFileHash: existing.fingerprint.originalFileHash,
                parserVersion: existing.fingerprint.parserVersion,
                normalizationVersion: existing.fingerprint.normalizationVersion
            ),
            workId: existing.workID,
            volumeId: existing.volumeID,
            sourceFormat: existing.sourceFormat
        )
    }

    /// Keep download/validation capability separate from actual reader capability.
    private static func hasCompleteReaderEngine(for sourceFormat: ErmaoShared.ReaderSourceFormat) -> Bool {
        switch sourceFormat {
        case .epub, .mobi, .azw, .azw3, .prc, .txt, .cbz, .pdf:
            true
        default:
            false
        }
    }

    private func download(
        bootstrap: ErmaoShared.ReaderBootstrap,
        gateway: ErmaoShared.ReaderServerGateway
    ) async throws -> ErmaoShared.ReaderSource {
        let result = try await gateway.download(
            download: bootstrap.publication,
            sinkFactory: IosPublicationDownloadSinkFactory(store: managedStore)
        )
        guard let content = result as? ErmaoShared.PublicationDownloadResultContent else {
            let failure = result as? ErmaoShared.PublicationDownloadResultFailure
            throw IosReaderFailure(code: failure?.recoverable == true ? .networkUnavailable : .resourceMissing)
        }
        return content.source
    }
}

@MainActor
enum IosReaderSession {
    case reflowable(IosReflowableReaderSession)
    case comic(IosComicReaderSession)
    case pdf(IosPdfReaderSession)
}

@MainActor
final class IosReaderBootstrapHost: ObservableObject {
    enum State {
        case loading
        case ready(IosReaderSession)
        case failure(IosReaderFailureCode)
    }

    @Published private(set) var state: State = .loading
    private let request: IosReaderLaunchRequest
    private unowned let composition: IosReaderComposition
    private var started = false

    init(request: IosReaderLaunchRequest, composition: IosReaderComposition) {
        self.request = request
        self.composition = composition
    }

    func start() async {
        guard !started else { return }
        started = true
        do {
            state = .ready(try await composition.bootstrap(request))
        } catch let failure as IosReaderFailure {
            state = .failure(failure.code)
        } catch {
            state = .failure(.networkUnavailable)
        }
    }
}

struct IosReaderBootstrapView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var host: IosReaderBootstrapHost

    init(request: IosReaderLaunchRequest, composition: IosReaderComposition) {
        _host = StateObject(wrappedValue: composition.makeHost(request: request))
    }

    var body: some View {
        Group {
            switch host.state {
            case .loading:
                ProgressView("reader.download.preparing")
            case .ready(let session):
                switch session {
                case .reflowable(let value): IosReflowableReaderView(session: value)
                case .comic(let value): IosComicReaderView(session: value)
                case .pdf(let value): IosPdfReaderView(session: value)
                }
            case .failure(let code):
                VStack(spacing: 16) {
                    Image(systemName: "exclamationmark.triangle").font(.largeTitle)
                    Text("reader.error.title").font(.headline)
                    Text(code.localizedDescription).multilineTextAlignment(.center)
                    Button("common.close") { dismiss() }
                }
                .padding(24)
            }
        }
        .task { await host.start() }
    }
}
