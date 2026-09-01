import Foundation
@preconcurrency import ErmaoShared

/// The authenticated session context used by every iOS audio adapter. Native
/// code may construct this value from the existing session projection, but it
/// cannot construct URLs, cookies, TLS handlers, or local-artifact identities.
struct IosAudioSessionContext: Equatable, Sendable {
    let profile: RuntimeServerProfile
    let userID: String
    let authorizationVersion: Int64

    var namespaceKey: String {
        "\(profile.serverIdentity)|\(userID)|\(authorizationVersion)"
    }

    var sharedNamespace: ErmaoShared.ReaderSyncNamespace {
        ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: profile.serverIdentity,
            userId: userID,
            authorizationVersion: authorizationVersion
        )
    }

    var sharedProfile: ErmaoShared.ServerProfile {
        ErmaoShared.PublicKt.createReaderServerProfile(
            id: profile.id,
            displayName: profile.displayName,
            baseUrl: profile.baseURL,
            serverIdentity: profile.serverIdentity,
            isActive: profile.isActive,
            acceptsInsecureTls: profile.tlsMode == .insecureSkipAllValidation
        )
    }
}

enum AudioCompositionError: Error, Equatable, Sendable {
    case unauthenticated
    case staleNamespace
    case invalidBootstrap
}

private struct AudioBootstrapFailure: Error, Equatable, Sendable {
    let code: String
    let recoverable: Bool
}

/// Shared Reader v4 bootstrap plus the validated audio projection. Keeping
/// both values together lets the progress owner reuse the exact Reader target
/// and remote snapshot instead of inventing a parallel protocol.
@MainActor
final class KmpAudioBootstrapGateway: AudioBootstrapGateway, AudioSessionConfiguring {
    private let gateway: any ErmaoShared.ReaderBootstrapGateway
    private var session: IosAudioSessionContext?

    init(cookieStore: KeychainCookiePayloadStore) {
        gateway = ErmaoShared.IosCompositionKt.createIosReaderBootstrapGateway(
            cookieStore: cookieStore
        )
    }

    func configure(session: IosAudioSessionContext?) {
        self.session = session
    }

    func loadAudioBootstrap(resourceID: String, namespace: String) async throws -> AudioBootstrapEnvelope {
        guard let session, session.namespaceKey == namespace else {
            throw AudioCompositionError.unauthenticated
        }
        let request = ErmaoShared.ReaderBootstrapRequest(
            profile: session.sharedProfile,
            namespace: session.sharedNamespace,
            resourceId: resourceID
        )
        let result = try await ErmaoShared.LoadAudioPublication(gateway: gateway).execute(
            request: request
        )
        guard let content = result as? ErmaoShared.AudioBootstrapResultContent else {
            if let failure = result as? ErmaoShared.AudioBootstrapResultFailure {
                throw AudioBootstrapFailure(code: failure.code, recoverable: failure.recoverable)
            }
            throw AudioCompositionError.invalidBootstrap
        }
        let publication = content.publication
        guard publication.namespace_ == session.sharedNamespace,
              publication.resource.resourceId == resourceID else {
            throw AudioCompositionError.staleNamespace
        }
        return AudioBootstrapEnvelope(
            presentation: Self.presentation(
                publication: publication,
                readerBootstrap: content.bootstrap
            ),
            publication: publication,
            readerBootstrap: content.bootstrap
        )
    }

    private static func presentation(
        publication: ErmaoShared.AudioPublication,
        readerBootstrap: ErmaoShared.ReaderBootstrap
    ) -> AudioBootstrap {
        let tracks = publication.assets.map { asset in
            AudioTrack(
                assetID: asset.assetId,
                title: asset.title,
                mediaReference: asset.apiPath,
                mimeType: asset.mimeType,
                codec: asset.codec,
                sizeBytes: asset.sizeBytes,
                durationMillis: asset.durationMillis?.int64Value ?? 0,
                discNumber: asset.discNumber?.intValue,
                trackNumber: asset.trackNumber?.intValue,
                sortOrder: Int(asset.sortOrder)
            )
        }
        let resources = publication.availableResources.map(Self.presentationResource)
        let resource = Self.presentationResource(publication.resource)
        let chapters = publication.chapters.map { chapter in
            let trackDuration = tracks.first(where: { $0.assetID == chapter.assetId })?.durationMillis ?? 0
            return AudioChapter(
                id: chapter.chapterId,
                title: chapter.title,
                assetID: chapter.assetId,
                startMillis: chapter.startMillis,
                endMillis: chapter.endMillis?.int64Value ?? trackDuration,
                sortOrder: Int(chapter.index)
            )
        }
        let resumeLocation: AudioLocation? = if
            let remote = readerBootstrap.remoteSnapshot?.locator as? ErmaoShared.AudioPublicationLocation
        {
            AudioLocation(
                resourceID: publication.resource.resourceId,
                assetID: remote.assetId,
                chapterID: remote.chapterId,
                positionMillis: remote.positionMillis
            )
        } else {
            nil
        }
        let duration = publication.assets.reduce(into: Int64(0)) { result, asset in
            result += max(0, asset.durationMillis?.int64Value ?? 0)
        }
        let progress = readerBootstrap.remoteSnapshot
        return AudioBootstrap(
            namespace: publication.namespace_.stableKey,
            userID: publication.namespace_.userId,
            book: AudioBookSummary(
                id: publication.bookId,
                title: publication.bookTitle,
                author: publication.author,
                coverReference: publication.coverApiPath
            ),
            resource: resource,
            availableResources: resources,
            tracks: tracks,
            chapters: chapters,
            totalDurationMillis: max(duration, publication.resource.durationMillis?.int64Value ?? 0),
            resumeLocation: resumeLocation,
            progressRevision: progress?.revision ?? 0,
            progressPercent: progress?.displayPercent ?? 0,
            playbackRate: 1,
            skipBackwardSeconds: 15,
            skipForwardSeconds: 30
        )
    }

    private static func presentationResource(
        _ resource: ErmaoShared.AudioResource
    ) -> AudioResourceSummary {
        AudioResourceSummary(
            id: resource.resourceId,
            bookID: "",
            title: resource.title,
            sortOrder: Int(resource.sortOrder),
            durationMillis: resource.durationMillis?.int64Value ?? 0,
            chapterCount: resource.chapterCount?.intValue ?? 0,
            resourceCompleted: false
        )
    }
}

/// A resource loader can outlive a session transition, so the authenticated
/// transport is swapped only at this composition boundary. An old loader
/// cannot obtain a stream after its namespace has been retired.
@MainActor
final class SwitchingKmpAudioMediaStreamAdapter: AudioMediaStreamAdapter, AudioSessionConfiguring {
    private let cookieStore: KeychainCookiePayloadStore
    private var adapter: KmpAudioMediaStreamAdapter?
    private var session: IosAudioSessionContext?

    init(cookieStore: KeychainCookiePayloadStore) {
        self.cookieStore = cookieStore
    }

    func configure(session: IosAudioSessionContext?) {
        self.session = session
        guard let session else {
            adapter = nil
            return
        }
        let transport = ErmaoShared.IosCompositionKt.createIosAudioMediaTransport(
            cookieStore: cookieStore,
            profile: session.sharedProfile
        )
        adapter = KmpAudioMediaStreamAdapter(transport: transport)
    }

    func probe(_ request: AudioMediaStreamRequest) async throws -> AudioMediaProbe {
        guard session?.namespaceKey == request.namespace, let adapter else {
            throw AudioCompositionError.unauthenticated
        }
        return try await adapter.probe(request)
    }

    func open(_ request: AudioMediaStreamRequest) async throws -> any AudioMediaStream {
        guard session?.namespaceKey == request.namespace, let adapter else {
            throw AudioCompositionError.unauthenticated
        }
        return try await adapter.open(request)
    }
}

/// Adapter for the existing Reader v4 local-first progress database and sync
/// outbox. Native code only maps projections; cadence, conflict and retry
/// policy remain owned by KMP.
@MainActor
final class KmpAudioProgressAdapter: AudioProgressAdapter, AudioSessionConfiguring, AudioProgressSessionConfiguring, AudioLocalProgressSessionConfiguring {
    private let cookieStore: KeychainCookiePayloadStore
    private let deviceIdentity = IosReaderDeviceIdentity()
    private var session: IosAudioSessionContext?
    private var progressRuntime: ErmaoShared.ReaderProgressSyncRuntime?
    private var writer: ErmaoShared.AudioProgressWriter?
    private var resourceID: String?

    init(cookieStore: KeychainCookiePayloadStore) {
        self.cookieStore = cookieStore
    }

    func configure(session: IosAudioSessionContext?) {
        self.session = session
        writer = nil
        progressRuntime?.close()
        progressRuntime = nil
        resourceID = nil
    }

    func configure(bootstrap: AudioBootstrapEnvelope) async {
        await configureLocal(
            bookID: bootstrap.publication.bookId,
            resourceID: bootstrap.publication.resource.resourceId
        )
    }

    func configureLocal(bookID: String, resourceID: String) async {
        guard let retainedSession = session else { return }
        configure(session: retainedSession)
        let namespace = retainedSession.sharedNamespace
        let target = ErmaoShared.ReaderProgressSyncTarget(
            namespace: namespace,
            bookId: bookID,
            resourceId: resourceID,
            sourceFormat: .audio
        )
        let localIdentity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: deviceIdentity.stableDeviceId(),
            bookId: bookID,
            resourceId: resourceID
        )
        do {
            let database = try IosReaderLocalDatabase(identity: localIdentity)
            let server = ErmaoShared.IosCompositionKt.createIosReaderProgressSyncPort(
                cookieStore: cookieStore,
                profile: retainedSession.sharedProfile
            )
            let runtime = ErmaoShared.PublicKt.createReaderProgressSyncRuntime(
                stateStore: database,
                target: target,
                server: server
            )
            progressRuntime = runtime
            self.resourceID = resourceID
            writer = ErmaoShared.AudioProgressWriter(
                store: runtime.store,
                resourceId: resourceID,
                deviceId: deviceIdentity.stableDeviceId(),
                nowEpochMillis: {
                    KotlinLong(longLong: Int64(Date().timeIntervalSince1970 * 1_000))
                }
            )
        } catch {
            progressRuntime = nil
            writer = nil
            self.resourceID = nil
        }
    }

    func loadLocation(namespace: String, resourceID: String) async throws -> AudioLocation? {
        guard session?.namespaceKey == namespace, self.resourceID == resourceID,
              let writer else { return nil }
        guard let value = try await writer.restore() else { return nil }
        return AudioLocation(
            resourceID: resourceID,
            assetID: value.assetId,
            chapterID: value.chapterId,
            positionMillis: value.positionMillis
        )
    }

    func saveLocation(
        _ location: AudioLocation,
        namespace: String,
        completed: Bool,
        reason: IosAudioProgressSaveReason
    ) async throws -> AudioProgressSaveResult {
        guard session?.namespaceKey == namespace, self.resourceID == location.resourceID,
              let writer else { return .pending }
        let sharedReason: ErmaoShared.AudioProgressSaveReason = switch reason {
        case .tick: .tick
        case .seek: .seek
        case .pause: .pause
        case .chapterChange: .chapterchange
        case .trackChange: .trackchange
        case .stop: .stop
        case .background: .background
        case .completed: .completed
        }
        _ = completed
        _ = try await writer.save(
            assetId: location.assetID,
            chapterId: location.chapterID,
            positionMillis: location.positionMillis,
            durationMillis: nil,
            reason: sharedReason
        )
        // The local-first store accepted the mutation; network acknowledgement
        // is asynchronous and remains pending by design.
        return .pending
    }

    func flush(namespace: String) async {
        guard session?.namespaceKey == namespace, let progressRuntime else { return }
        try? await progressRuntime.store.awaitPendingUpload()
    }
}

/// App-root composition for the shared bootstrap, authenticated stream and
/// local-first progress owners. Verified local artifacts enter through the
/// Download Center boundary and never expose a path to this network adapter.
enum AudioCompositionRoot {
    @MainActor
    static func makeRuntime(
        cookieStore: KeychainCookiePayloadStore = KeychainCookiePayloadStore(),
        backgroundPlaybackEnabled: Bool = true
    ) -> AudioPlaybackRuntime {
        let bootstrap = KmpAudioBootstrapGateway(cookieStore: cookieStore)
        let media = SwitchingKmpAudioMediaStreamAdapter(cookieStore: cookieStore)
        let progress = KmpAudioProgressAdapter(cookieStore: cookieStore)
        return AudioPlaybackRuntime(
            bootstrapGateway: bootstrap,
            mediaAdapter: media,
            progressAdapter: progress,
            coverAdapter: EmptyAudioCoverAdapter(),
            backgroundPlaybackEnabled: backgroundPlaybackEnabled
        )
    }
}
