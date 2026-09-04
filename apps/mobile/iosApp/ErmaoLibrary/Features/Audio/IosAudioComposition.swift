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

/// Shared Reader v5 bootstrap plus the validated audio projection. Keeping
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
        guard let session else {
            throw AudioCompositionError.unauthenticated
        }
        _ = try Self.presentationNamespace(
            session: session,
            requestedNamespace: namespace
        )
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
            publication: publication,
            remoteSnapshot: content.bootstrap.remoteSnapshot
        )
    }

    static func presentationNamespace(
        session: IosAudioSessionContext,
        requestedNamespace: String
    ) throws -> String {
        guard session.namespaceKey == requestedNamespace else {
            throw AudioCompositionError.staleNamespace
        }
        // Native persistence, downloads and adapters already use this key.
        // ReaderSyncNamespace.stableKey is a KMP storage identity and must not
        // replace the active native session namespace at this boundary.
        return requestedNamespace
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

/// Adapter for the Reader v5 local-first position database and latest-only
/// outbox. Cadence, idempotent retry and acknowledgement remain owned by KMP.
@MainActor
final class KmpAudioProgressAdapter: AudioRemoteProgressAdapter, AudioSessionConfiguring {
    private final class ProgressContext {
        let namespace: String
        let bookID: String
        let resourceID: String
        let runtime: ErmaoShared.ReaderPositionSyncRuntime
        let progressSession: ErmaoShared.AudioProgressSession
        let publication: ErmaoShared.AudioPublication
        let target: ErmaoShared.ReaderProgressSyncTarget
        let server: ErmaoShared.ReaderPositionServerPort
        let clientID: String
        var etag: String?

        init(
            namespace: String,
            bookID: String,
            resourceID: String,
            runtime: ErmaoShared.ReaderPositionSyncRuntime,
            progressSession: ErmaoShared.AudioProgressSession,
            publication: ErmaoShared.AudioPublication,
            target: ErmaoShared.ReaderProgressSyncTarget,
            server: ErmaoShared.ReaderPositionServerPort,
            clientID: String
        ) {
            self.namespace = namespace
            self.bookID = bookID
            self.resourceID = resourceID
            self.runtime = runtime
            self.progressSession = progressSession
            self.publication = publication
            self.target = target
            self.server = server
            self.clientID = clientID
        }
    }

    private let cookieStore: KeychainCookiePayloadStore
    private let deviceIdentity = IosReaderDeviceIdentity()
    private var session: IosAudioSessionContext?
    private var activeContext: ProgressContext?
    private var preparedContext: ProgressContext?
    var remoteSnapshotHandler: ((ErmaoShared.ReaderProgressSnapshotV5?) -> Void)?

    init(cookieStore: KeychainCookiePayloadStore) {
        self.cookieStore = cookieStore
    }

    func configure(session: IosAudioSessionContext?) {
        guard self.session != session else { return }
        self.session = session
        closeAllContexts()
    }

    func configure(bootstrap: AudioBootstrapEnvelope) async throws -> ErmaoShared.AudioReaderLocation? {
        guard let context = prepareProgress(
            bookID: bootstrap.publication.bookId,
            resourceID: bootstrap.publication.resource.resourceId,
            publication: bootstrap.publication,
            remoteSnapshot: bootstrap.remoteSnapshot
        ) else { return nil }
        let restored: ErmaoShared.AudioReaderLocation?
        do {
            restored = try await context.progressSession.restore(
                publication: bootstrap.publication,
                remoteSnapshot: bootstrap.remoteSnapshot
            )
        } catch {
            throw AudioAdapterError.locationRestoreFailed
        }
        guard preparedContext === context || activeContext === context else { return nil }
        return restored
    }

    func configureLocal(publication: ErmaoShared.AudioPublication) async throws -> ErmaoShared.AudioReaderLocation? {
        guard let context = prepareProgress(
            bookID: publication.bookId,
            resourceID: publication.resource.resourceId,
            publication: publication,
            remoteSnapshot: nil
        ) else { return nil }
        let restored: ErmaoShared.AudioReaderLocation?
        do {
            restored = try await context.progressSession.restore(
                publication: publication,
                remoteSnapshot: nil
            )
        } catch {
            throw AudioAdapterError.locationRestoreFailed
        }
        guard preparedContext === context || activeContext === context else { return nil }
        return restored
    }

    func commitPrepared(resourceID: String, namespace: String) {
        guard let preparedContext,
              preparedContext.resourceID == resourceID,
              preparedContext.namespace == namespace else { return }
        if let activeContext, activeContext !== preparedContext {
            activeContext.runtime.close()
        }
        activeContext = preparedContext
        self.preparedContext = nil
    }

    func discardPrepared(resourceID: String, namespace: String) {
        guard let preparedContext,
              preparedContext.resourceID == resourceID,
              preparedContext.namespace == namespace else { return }
        if preparedContext !== activeContext {
            preparedContext.runtime.close()
        }
        self.preparedContext = nil
    }

    private func prepareProgress(
        bookID: String,
        resourceID: String,
        publication: ErmaoShared.AudioPublication,
        remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
    ) -> ProgressContext? {
        guard let retainedSession = session else { return nil }
        if let activeContext,
           activeContext.namespace == retainedSession.namespaceKey,
           activeContext.resourceID == resourceID {
            replacePreparedContext(with: activeContext)
            activeContext.runtime.coordinator.beginSession(snapshot: remoteSnapshot)
            return activeContext
        }
        if let preparedContext,
           preparedContext.namespace == retainedSession.namespaceKey,
           preparedContext.resourceID == resourceID {
            preparedContext.runtime.coordinator.beginSession(snapshot: remoteSnapshot)
            return preparedContext
        }
        replacePreparedContext(with: nil)
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
            let server = ErmaoShared.IosCompositionKt.createIosReaderPositionSyncPort(
                cookieStore: cookieStore,
                profile: retainedSession.sharedProfile
            )
            let runtime = ErmaoShared.PublicKt.createReaderPositionSyncRuntime(
                stateStore: database,
                target: target,
                server: server
            )
            runtime.coordinator.beginSession(snapshot: remoteSnapshot)
            let writer = ErmaoShared.AudioProgressWriter(
                store: runtime.store,
                resourceId: resourceID,
                deviceId: deviceIdentity.stableDeviceId(),
                nowEpochMillis: {
                    KotlinLong(longLong: Int64(Date().timeIntervalSince1970 * 1_000))
                }
            )
            let progressSession = ErmaoShared.AudioProgressSession(
                writer: writer,
                syncRuntime: runtime,
                syncTarget: target
            )
            let context = ProgressContext(
                namespace: retainedSession.namespaceKey,
                bookID: bookID,
                resourceID: resourceID,
                runtime: runtime,
                progressSession: progressSession,
                publication: publication,
                target: target,
                server: server,
                clientID: deviceIdentity.stableDeviceId()
            )
            preparedContext = context
            return context
        } catch {
            return nil
        }
    }

    func save(_ effect: ErmaoShared.AudioPlaybackEffect) async throws {
        guard effect.type == .saveprogress,
              effect.asset != nil,
              effect.progressReason != nil else {
            throw AudioCompositionError.invalidBootstrap
        }
        guard let namespace = effect.namespaceKey,
              session?.namespaceKey == namespace,
              let resourceID = effect.resourceId else {
            throw AudioCompositionError.staleNamespace
        }
        let context = matchingContext(namespace: namespace, resourceID: resourceID)
        guard let context else {
            throw AudioCompositionError.unauthenticated
        }
        // Preserve the complete same-event presentation (publication-wide
        // progression, chapter/index and engine href) owned by the shared
        // audio adapter. Reconstructing the call from a subset would reduce
        // every multi-track book to per-track progress.
        try await context.progressSession.save(effect: effect)
        remoteSnapshotHandler?(context.runtime.coordinator.remotePositionNotice()?.snapshot)
        if let local = try await context.runtime.store.load(resourceId: resourceID) {
            ReaderProgressPresentationCenter.shared.publish(
                namespaceKey: namespace,
                bookID: context.bookID,
                resourceID: resourceID,
                position: local.position,
                capturedAtEpochMillis: local.capturedAtEpochMillis
            )
        }
    }

    func flush(namespace: String) async {
        guard session?.namespaceKey == namespace else { return }
        if let activeContext, activeContext.namespace == namespace {
            try? await activeContext.runtime.store.retryPendingUpload()
            try? await activeContext.runtime.store.awaitPendingUpload()
        }
        if let preparedContext,
           preparedContext !== activeContext,
           preparedContext.namespace == namespace {
            try? await preparedContext.runtime.store.retryPendingUpload()
            try? await preparedContext.runtime.store.awaitPendingUpload()
        }
    }

    func checkForRemoteProgress() async {
        guard let context = activeContext else { return }
        let result: ErmaoShared.ReaderPositionQueryResult
        do {
            result = try await context.server.load(target: context.target, etag: context.etag)
        } catch {
            return
        }
        if let current = result as? ErmaoShared.ReaderPositionQueryResultCurrent {
            context.etag = current.etag
            guard let snapshot = current.snapshot else { return }
            _ = try? await context.runtime.coordinator.observeRemotePosition(
                snapshot: snapshot,
                currentClientId: context.clientID
            )
            remoteSnapshotHandler?(context.runtime.coordinator.remotePositionNotice()?.snapshot)
        } else if let unchanged = result as? ErmaoShared.ReaderPositionQueryResultUnchanged {
            context.etag = unchanged.etag ?? context.etag
        }
    }

    func dismissRemoteProgress() {
        activeContext?.runtime.coordinator.dismissRemotePositionNotice()
        remoteSnapshotHandler?(nil)
    }

    func remoteLocation(
        for snapshot: ErmaoShared.ReaderProgressSnapshotV5
    ) async throws -> ErmaoShared.AudioReaderLocation {
        guard let context = activeContext else { throw AudioCompositionError.unauthenticated }
        return try await context.progressSession.remoteLocation(
            publication: context.publication,
            snapshot: snapshot
        )
    }

    func acceptRemote(_ snapshot: ErmaoShared.ReaderProgressSnapshotV5) async throws {
        guard let context = activeContext else { throw AudioCompositionError.unauthenticated }
        try await context.progressSession.acceptRemote(snapshot: snapshot, clientId: context.clientID)
        remoteSnapshotHandler?(nil)
    }

    private func matchingContext(namespace: String, resourceID: String) -> ProgressContext? {
        if let activeContext,
           activeContext.namespace == namespace,
           activeContext.resourceID == resourceID {
            return activeContext
        }
        if let preparedContext,
           preparedContext.namespace == namespace,
           preparedContext.resourceID == resourceID {
            return preparedContext
        }
        return nil
    }

    private func replacePreparedContext(with replacement: ProgressContext?) {
        if let preparedContext,
           preparedContext !== activeContext,
           preparedContext !== replacement {
            preparedContext.runtime.close()
        }
        preparedContext = replacement
    }

    private func closeAllContexts() {
        if let preparedContext, preparedContext !== activeContext {
            preparedContext.runtime.close()
        }
        activeContext?.runtime.close()
        preparedContext = nil
        activeContext = nil
        remoteSnapshotHandler?(nil)
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
            backgroundPlaybackEnabled: backgroundPlaybackEnabled
        )
    }
}
