import Foundation
@preconcurrency import ErmaoShared

struct IosReaderLaunchRequest: Identifiable, Equatable, Sendable {
    let context: ContentRequestContext
    let workID: String
    let volumeID: String
    let displayTitle: String

    var id: String { "\(context.namespaceKey)|\(volumeID)" }
}

@MainActor
final class IosReaderComposition: ObservableObject {
    private let cookieStore: KeychainCookiePayloadStore
    private let managedStore: IosManagedPublicationStore
    private let deviceIdentity: IosReaderDeviceIdentity

    init(cookieStore: KeychainCookiePayloadStore) throws {
        self.cookieStore = cookieStore
        managedStore = try IosManagedPublicationStore()
        deviceIdentity = IosReaderDeviceIdentity()
    }

    func makeHost(request: IosReaderLaunchRequest) -> IosReaderBootstrapHost {
        IosReaderBootstrapHost(request: request, composition: self)
    }

    fileprivate func bootstrap(_ request: IosReaderLaunchRequest) async throws -> IosEpubReaderSession {
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
        let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
        let source: ErmaoShared.ReaderSource
        if let onlineBootstrap {
            target = onlineBootstrap.target
            remoteSnapshot = onlineBootstrap.remoteSnapshot
            do {
                let existing = try await managedStore.resolve(sourceID: request.volumeID)
                if existing.serverContentFingerprint == target.serverContentFingerprint.value {
                    source = Self.sharedSource(existing)
                } else {
                    source = try await download(bootstrap: onlineBootstrap, gateway: gateway)
                }
            } catch {
                source = try await download(bootstrap: onlineBootstrap, gateway: gateway)
            }
            try await managedStore.bindServerContentFingerprint(
                sourceID: request.volumeID,
                value: target.serverContentFingerprint.value
            )
        } else {
            // Offline opening is allowed only for a previously verified managed
            // publication whose server version was durably bound at bootstrap.
            let existing = try await managedStore.resolve(sourceID: request.volumeID)
            guard let serverFingerprint = existing.serverContentFingerprint else {
                throw IosReaderFailure(code: .networkUnavailable)
            }
            target = ErmaoShared.ReaderProgressSyncTarget(
                namespace: namespace,
                workId: request.workID,
                volumeId: request.volumeID,
                sourceFormat: .epub,
                serverContentFingerprint: ErmaoShared.ReaderServerContentFingerprint(value: serverFingerprint)
            )
            remoteSnapshot = nil
            source = Self.sharedSource(existing)
        }

        guard source.sourceId == target.volumeId else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let localIdentity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: deviceIdentity.stableDeviceId(),
            volumeId: target.volumeId,
            localContentFingerprint: source.contentFingerprint
        )
        let database = try IosReaderLocalDatabase(
            identity: localIdentity
        )
        let syncPort = IosCompositionKt.createIosReaderProgressSyncPort(
            cookieStore: cookieStore,
            profile: profile
        )
        let progressStore = IosReaderProgressStore(
            database: database,
            target: target,
            syncPort: syncPort
        )
        return IosEpubReaderSession(
            sourceID: source.sourceId,
            displayTitle: source.displayTitle,
            managedStore: managedStore,
            progressStore: progressStore,
            remoteSnapshot: remoteSnapshot,
            deviceIdentity: deviceIdentity
        )
    }

    private static func sharedSource(_ existing: IosManagedPublication) -> ErmaoShared.ReaderSource {
        ErmaoShared.LocalReaderSource(
            sourceId: existing.sourceID,
            displayTitle: existing.displayTitle,
            format: .epub,
            contentFingerprint: ErmaoShared.ContentFingerprint(
                originalFileHash: existing.fingerprint.originalFileHash,
                parserVersion: existing.fingerprint.parserVersion,
                normalizationVersion: existing.fingerprint.normalizationVersion
            ),
            workId: existing.workID,
            volumeId: existing.volumeID
        )
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
final class IosReaderBootstrapHost: ObservableObject {
    enum State {
        case loading
        case ready(IosEpubReaderSession)
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
                IosEpubReaderView(session: session)
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
