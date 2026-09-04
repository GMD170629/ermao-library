import Foundation
import MediaPlayer
import SwiftUI
@preconcurrency import ErmaoShared

/// Process-wide platform adapter for the KMP audio state machine.
///
/// It loads bootstrap data, executes typed effects against AVPlayer, reports engine facts, and
/// renders the shared snapshot. Chapter, track, timer, completion and progress rules live in KMP.
@MainActor
final class AudioPlaybackRuntime: ObservableObject, AudioSystemMediaDelegate {
    @Published private(set) var snapshot: AudioPlaybackSnapshot
    @Published private(set) var nowPlayingPresentationRequestID: UUID?
    @Published private(set) var remoteProgressSnapshot: ErmaoShared.ReaderProgressSnapshotV5?
    @Published private(set) var remoteProgressActionFailed = false

    let bootstrapGateway: any AudioBootstrapGateway
    let mediaAdapter: any AudioMediaStreamAdapter
    let progressAdapter: any AudioProgressAdapter

    private let engine: any AudioPlaybackEngine
    private let systemMedia: any AudioSystemMediaControlling
    private let backgroundPlaybackEnabled: Bool
    private let stateMachine: ErmaoShared.AudioPlaybackStateMachine
    private var sharedSnapshot: ErmaoShared.AudioPlaybackSnapshot
    private var bootstrapTask: Task<Void, Never>?
    private var sleepWakeTask: Task<Void, Never>?
    private var progressOperationTask: Task<Void, Never>?
    private var stopTask: Task<Void, Never>?
    private var sessionConfigurationTask: Task<Void, Never>?
    private var scheduledSleepDeadline: Int64?
    private var lastLaunch: (intent: AudioLaunchIntent, namespace: String)?
    private var sessionContext: IosAudioSessionContext?
    private var localMediaReferences: [String: String] = [:]
    private var isShuttingDown = false
    private var isStopping = false
    private var pendingRemoteAcceptance: ErmaoShared.ReaderProgressSnapshotV5?

    init(
        bootstrapGateway: any AudioBootstrapGateway,
        mediaAdapter: any AudioMediaStreamAdapter,
        progressAdapter: any AudioProgressAdapter,
        engine: (any AudioPlaybackEngine)? = nil,
        systemMedia: (any AudioSystemMediaControlling)? = nil,
        backgroundPlaybackEnabled: Bool = true,
        stateMachine: ErmaoShared.AudioPlaybackStateMachine? = nil
    ) {
        self.bootstrapGateway = bootstrapGateway
        self.mediaAdapter = mediaAdapter
        self.progressAdapter = progressAdapter
        self.engine = engine ?? IosAVAudioEngine(mediaAdapter: mediaAdapter)
        self.systemMedia = systemMedia ?? IosAudioSystemMediaController()
        self.backgroundPlaybackEnabled = backgroundPlaybackEnabled
        let resolvedStateMachine = stateMachine ?? ErmaoShared.AudioPlaybackStateMachine(
            initialPlaybackRate: 1,
            nowEpochMillis: {
                KotlinLong(longLong: Int64(Date().timeIntervalSince1970 * 1_000))
            },
            nowMonotonicMillis: {
                KotlinLong(longLong: Int64(ProcessInfo.processInfo.systemUptime * 1_000))
            }
        )
        self.stateMachine = resolvedStateMachine
        sharedSnapshot = resolvedStateMachine.snapshot()
        snapshot = .idle()
        nowPlayingPresentationRequestID = nil
        remoteProgressSnapshot = nil
        render(sharedSnapshot)
        self.engine.eventHandler = { [weak self] event in
            self?.receive(event)
        }
        self.systemMedia.delegate = self
        (self.progressAdapter as? any AudioRemoteProgressAdapter)?.remoteSnapshotHandler = { [weak self] snapshot in
            self?.remoteProgressSnapshot = snapshot
            self?.remoteProgressActionFailed = false
        }
    }

    deinit {
        bootstrapTask?.cancel()
        sleepWakeTask?.cancel()
        progressOperationTask?.cancel()
        stopTask?.cancel()
        sessionConfigurationTask?.cancel()
    }

    // MARK: Small Runtime command surface

    func launch(_ intent: AudioLaunchIntent, namespace: String) {
        guard !isShuttingDown, !isStopping,
              !userCommandsLocked,
              let sessionContext,
              sessionContext.namespaceKey == namespace else { return }
        let resourceID = intent.resourceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !resourceID.isEmpty else { return }
        let normalized = AudioLaunchIntent(
            resourceID: resourceID,
            assetID: intent.assetID?.trimmedNonEmpty,
            chapterID: intent.chapterID?.trimmedNonEmpty,
            positionMillis: intent.positionMillis.map { max(0, $0) },
            autoplay: intent.autoplay
        )
        lastLaunch = (normalized, namespace)
        if normalized.autoplay { nowPlayingPresentationRequestID = UUID() }
        bootstrapTask?.cancel()
        let request = stateMachine.beginLaunch(
            namespace: sessionContext.sharedNamespace,
            namespaceKey: namespace,
            intent: normalized.shared
        )
        apply(request.transition)
        bootstrapTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let envelope = try await self.bootstrapGateway.loadAudioBootstrap(
                    resourceID: resourceID,
                    namespace: namespace
                )
                try Task.checkCancellation()
                let restored: ErmaoShared.AudioReaderLocation?
                do {
                    restored = try await self.enqueueProgressRestore { runtime in
                        try await runtime.progressAdapter.configure(bootstrap: envelope)
                    }
                } catch is CancellationError {
                    return
                } catch {
                    restored = nil
                }
                try Task.checkCancellation()
                self.apply(self.stateMachine.publicationLoaded(
                    token: request.token,
                    publication: envelope.publication,
                    restoredLocation: restored
                ))
            } catch is CancellationError {
                return
            } catch {
                self.apply(self.stateMachine.launchFailed(
                    token: request.token,
                    error: self.sharedError(for: error)
                ))
            }
        }
    }

    func launchVerifiedLocalArtifact(
        namespace: String,
        userID: String,
        bookID: String,
        bookTitle: String,
        author: String?,
        resourceID: String,
        resourceTitle: String,
        assetID: String,
        fileURL: URL,
        mimeType: String,
        sizeBytes: Int64,
        positionMillis: Int64 = 0,
        durationMillis: Int64 = 0,
        autoplay: Bool = true
    ) {
        guard !isShuttingDown, !isStopping,
              !userCommandsLocked,
              let sessionContext,
              sessionContext.namespaceKey == namespace,
              fileURL.isFileURL,
              FileManager.default.fileExists(atPath: fileURL.path),
              sizeBytes > 0 else { return }
        let publication = ErmaoShared.LocalAudioPublicationFactory().create(
            namespace: sessionContext.sharedNamespace,
            bookId: bookID,
            bookTitle: bookTitle,
            author: author,
            resourceId: resourceID,
            resourceTitle: resourceTitle,
            assetId: assetID,
            mimeType: mimeType,
            sizeBytes: sizeBytes,
            durationMillis: max(0, durationMillis)
        )
        localMediaReferences[mediaKey(resourceID: resourceID, assetID: assetID)] = fileURL.absoluteString
        let intent = AudioLaunchIntent(
            resourceID: resourceID,
            assetID: assetID,
            positionMillis: max(0, positionMillis),
            autoplay: autoplay
        )
        lastLaunch = nil
        if autoplay { nowPlayingPresentationRequestID = UUID() }
        bootstrapTask?.cancel()
        let request = stateMachine.beginLaunch(
            namespace: sessionContext.sharedNamespace,
            namespaceKey: namespace,
            intent: intent.shared
        )
        apply(request.transition)
        bootstrapTask = Task { @MainActor [weak self] in
            guard let self else { return }
            let restored: ErmaoShared.AudioReaderLocation?
            do {
                do {
                    restored = try await self.enqueueProgressRestore { runtime in
                        try await runtime.progressAdapter.configureLocal(publication: publication)
                    }
                } catch is CancellationError {
                    return
                } catch {
                    restored = nil
                }
                try Task.checkCancellation()
                self.apply(self.stateMachine.publicationLoaded(
                    token: request.token,
                    publication: publication,
                    restoredLocation: restored
                ))
            } catch is CancellationError {
                return
            } catch {
                self.apply(self.stateMachine.launchFailed(
                    token: request.token,
                    error: self.sharedError(for: error)
                ))
            }
        }
        _ = userID // Identity is already carried by ReaderSyncNamespace.
    }

    func play() { applyUserCommand { stateMachine.play() } }
    func pause() { applyUserCommand { stateMachine.pause() } }
    func togglePlayback() { applyUserCommand { stateMachine.togglePlayback() } }
    func seekAbsolute(to positionMillis: Int64) {
        applyUserCommand {
            stateMachine.seekAbsolute(positionMillis: max(0, positionMillis))
        }
    }
    func beginScrubbing() {
        guard !isShuttingDown, !isStopping, !userCommandsLocked else { return }
        apply(stateMachine.beginScrubbing())
    }
    func updateScrubbing(to positionMillis: Int64) {
        guard !isShuttingDown, !isStopping else { return }
        apply(stateMachine.updateScrubbingPosition(positionMillis: max(0, positionMillis)))
    }
    func finishScrubbing(at positionMillis: Int64) {
        guard !isShuttingDown, !isStopping else { return }
        apply(stateMachine.finishScrubbing(positionMillis: max(0, positionMillis)))
    }
    func cancelScrubbing() {
        guard !isShuttingDown, !isStopping else { return }
        apply(stateMachine.cancelScrubbing())
    }
    func seekBy(milliseconds: Int64) {
        applyUserCommand { stateMachine.seekBy(deltaMillis: milliseconds) }
    }
    func skipBackward() { applyUserCommand { stateMachine.skipBackward() } }
    func skipForward() { applyUserCommand { stateMachine.skipForward() } }
    func previousChapter() { applyUserCommand { stateMachine.previousChapter() } }
    func nextChapter() { applyUserCommand { stateMachine.nextChapter() } }
    func selectAsset(_ assetID: String) {
        applyUserCommand { stateMachine.selectAsset(assetId: assetID) }
    }
    func selectChapter(_ chapterID: String) {
        applyUserCommand { stateMachine.selectChapter(chapterId: chapterID) }
    }
    func setPlaybackRate(_ rate: Double) {
        applyUserCommand { stateMachine.setPlaybackRate(rate: rate) }
    }
    func setSleepTimer(_ mode: ErmaoShared.AudioSleepTimerMode) {
        applyUserCommand { stateMachine.setSleepTimer(mode: mode) }
    }

    func dismissRemoteProgress() {
        (progressAdapter as? any AudioRemoteProgressAdapter)?.dismissRemoteProgress()
        remoteProgressSnapshot = nil
        remoteProgressActionFailed = false
    }

    func goToRemoteProgress() {
        guard let snapshot = remoteProgressSnapshot,
              let adapter = progressAdapter as? any AudioRemoteProgressAdapter else { return }
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let location = try await adapter.remoteLocation(for: snapshot)
                guard self.snapshot.bootstrap?.tracks.contains(where: { $0.assetID == location.assetId }) == true else {
                    throw AudioAdapterError.locationRestoreFailed
                }
                guard !self.userCommandsLocked else { throw AudioAdapterError.locationRestoreFailed }
                let transition = self.stateMachine.goToReaderLocation(location: location)
                guard !transition.effects.isEmpty else { throw AudioAdapterError.locationRestoreFailed }
                self.pendingRemoteAcceptance = snapshot
                self.apply(transition)
            } catch {
                self.remoteProgressActionFailed = true
            }
        }
    }

    func stopAndClear() {
        bootstrapTask?.cancel()
        bootstrapTask = nil
        lastLaunch = nil
        apply(stateMachine.stop())
    }

    func retry() {
        guard let lastLaunch else { return }
        launch(lastLaunch.intent, namespace: lastLaunch.namespace)
    }

    // MARK: App/session lifecycle facts

    func prepareForNamespaceTransition() async {
        let namespace = snapshot.namespace
        stopAndClear()
        await stopTask?.value
        if let namespace {
            await progressAdapter.flush(namespace: namespace)
        }
    }

    func sessionDidChange(isAuthenticated: Bool, session: IosAudioSessionContext?) {
        let nextSession = isAuthenticated ? session : nil
        let mustRetireActiveSession = snapshot.lifecycle != .idle && sessionContext != nextSession
        sessionContext = nextSession
        sessionConfigurationTask?.cancel()
        sessionConfigurationTask = nil
        guard mustRetireActiveSession || isStopping else {
            configureSessionAdapters(nextSession)
            return
        }
        if mustRetireActiveSession { stopAndClear() }
        let pendingStop = stopTask
        sessionConfigurationTask = Task { @MainActor [weak self] in
            await pendingStop?.value
            guard let self,
                  !Task.isCancelled,
                  self.sessionContext == nextSession,
                  !self.isShuttingDown else { return }
            self.configureSessionAdapters(nextSession)
            self.sessionConfigurationTask = nil
        }
    }

    func handleScenePhase(_ phase: ScenePhase) {
        switch phase {
        case .active:
            if snapshot.isPlaying { try? systemMedia.activate() }
            Task { await (progressAdapter as? any AudioRemoteProgressAdapter)?.checkForRemoteProgress() }
        case .inactive, .background:
            apply(stateMachine.saveProgress(reason: .background))
            if phase == .background && !backgroundPlaybackEnabled {
                if userCommandsLocked { stopAndClear() } else { pause() }
            }
        @unknown default:
            apply(stateMachine.saveProgress(reason: .background))
        }
    }

    /// Stops the native player, waits for the final local v5 save, then gives
    /// the progress adapter one last retry/await window before the process is
    /// torn down.  The pending mutation remains durable when that window
    /// cannot complete.
    func shutdown() async {
        let namespace = snapshot.namespace
        isShuttingDown = true
        stopAndClear()
        await stopTask?.value
        if let namespace {
            await progressAdapter.flush(namespace: namespace)
        }
    }

    private func configureSessionAdapters(_ session: IosAudioSessionContext?) {
        (bootstrapGateway as? any AudioSessionConfiguring)?.configure(session: session)
        (mediaAdapter as? any AudioSessionConfiguring)?.configure(session: session)
        (progressAdapter as? any AudioSessionConfiguring)?.configure(session: session)
    }

    // MARK: Engine/system facts

    func receive(_ event: AudioEngineEvent) {
        let transition: ErmaoShared.AudioPlaybackTransition
        switch event {
        case .prepared(let sourceID, let duration):
            transition = stateMachine.enginePrepared(
                sourceId: sourceID,
                durationMillis: duration.map(KotlinLong.init(longLong:))
            )
        case .committed(let sourceID):
            transition = stateMachine.engineCommitted(sourceId: sourceID)
        case .ready(let sourceID, let duration):
            transition = stateMachine.engineReady(
                sourceId: sourceID,
                durationMillis: duration.map(KotlinLong.init(longLong:))
            )
        case .playing(let sourceID):
            transition = stateMachine.enginePlaying(sourceId: sourceID)
        case .paused(let sourceID):
            transition = stateMachine.enginePaused(sourceId: sourceID)
        case .buffering(let sourceID):
            transition = stateMachine.engineBuffering(sourceId: sourceID)
        case .position(let sourceID, let position, let duration):
            transition = stateMachine.enginePosition(
                sourceId: sourceID,
                positionMillis: position,
                durationMillis: duration.map(KotlinLong.init(longLong:))
            )
        case .seekCompleted(let sourceID, let operationID, let position, let duration):
            transition = stateMachine.engineSeekCompleted(
                sourceId: sourceID,
                operationId: operationID,
                positionMillis: position,
                durationMillis: duration.map(KotlinLong.init(longLong:))
            )
        case .seekFailed(let sourceID, let operationID, let failure):
            transition = stateMachine.engineSeekFailed(
                sourceId: sourceID,
                operationId: operationID,
                error: sharedError(for: failure)
            )
        case .ended(let sourceID):
            transition = stateMachine.engineEnded(sourceId: sourceID)
        case .failed(let sourceID, let failure):
            transition = stateMachine.engineFailed(
                sourceId: sourceID,
                error: sharedError(for: failure)
            )
        }
        apply(transition)
        switch event {
        case .ready, .seekCompleted:
            if let pending = pendingRemoteAcceptance,
               let adapter = progressAdapter as? any AudioRemoteProgressAdapter {
                pendingRemoteAcceptance = nil
                Task { @MainActor [weak self] in
                    do {
                        try await adapter.acceptRemote(pending)
                        self?.remoteProgressSnapshot = nil
                        self?.remoteProgressActionFailed = false
                    } catch {
                        self?.remoteProgressActionFailed = true
                    }
                }
            }
        case .seekFailed, .failed:
            if pendingRemoteAcceptance != nil {
                pendingRemoteAcceptance = nil
                remoteProgressActionFailed = true
            }
        default:
            break
        }
    }

    func audioSystemDidBeginInterruption() {
        if userCommandsLocked { stopAndClear() } else { apply(stateMachine.pause()) }
    }

    /// The platform reports `shouldResume`; KMP policy intentionally keeps playback paused.
    func audioSystemDidEndInterruption(shouldResume: Bool) {
        apply(stateMachine.saveProgress(reason: .pause))
        _ = shouldResume
    }

    func audioSystemDidLoseRoute() {
        if userCommandsLocked { stopAndClear() } else { apply(stateMachine.pause()) }
    }
    func audioSystemDidResetMediaServices() {
        if userCommandsLocked { stopAndClear() } else { apply(stateMachine.reloadCurrentSource()) }
    }

    func audioSystemPlayRequested() -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked else { return .commandFailed }
        play(); return .success
    }

    func audioSystemPauseRequested() -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked else { return .commandFailed }
        pause(); return .success
    }

    func audioSystemStopRequested() -> MPRemoteCommandHandlerStatus {
        stopAndClear(); return .success
    }

    func audioSystemSeekRequested(positionSeconds: Double) -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked, positionSeconds.isFinite else { return .commandFailed }
        seekAbsolute(to: Int64(max(0, positionSeconds) * 1_000))
        return .success
    }

    func audioSystemSkipBackwardRequested() -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked else { return .commandFailed }
        skipBackward(); return .success
    }

    func audioSystemSkipForwardRequested() -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked else { return .commandFailed }
        skipForward(); return .success
    }

    func audioSystemPreviousRequested() -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked else { return .commandFailed }
        previousChapter(); return .success
    }

    func audioSystemNextRequested() -> MPRemoteCommandHandlerStatus {
        guard !userCommandsLocked else { return .commandFailed }
        nextChapter(); return .success
    }

    // MARK: Effect executor and snapshot renderer

    private var userCommandsLocked: Bool {
        sharedSnapshot.isPreparing || sharedSnapshot.hasPendingSeekInteraction
    }

    private func applyUserCommand(
        _ command: () -> ErmaoShared.AudioPlaybackTransition
    ) {
        guard !userCommandsLocked else { return }
        apply(command())
    }

    private func apply(_ transition: ErmaoShared.AudioPlaybackTransition) {
        let previous = sharedSnapshot
        if transition.snapshot.sourceId?.int64Value != previous.sourceId?.int64Value,
           transition.snapshot.pendingSourceId == nil,
           let publication = transition.snapshot.publication,
           let namespace = transition.snapshot.namespaceKey {
            enqueueProgressOperation { runtime in
                runtime.progressAdapter.commitPrepared(
                    resourceID: publication.resource.resourceId,
                    namespace: namespace
                )
                await (runtime.progressAdapter as? any AudioRemoteProgressAdapter)?
                    .checkForRemoteProgress()
            }
        }
        for effect in transition.effects where effect.type == .cancelpreparedsource {
            guard previous.pendingSourceId?.int64Value == effect.sourceId,
                  let resourceID = previous.pendingResourceId,
                  let namespace = previous.namespaceKey else { continue }
            enqueueProgressOperation { runtime in
                runtime.progressAdapter.discardPrepared(
                    resourceID: resourceID,
                    namespace: namespace
                )
            }
        }
        render(transition.snapshot)
        execute(transition.effects)
    }

    private func execute(_ effects: [ErmaoShared.AudioPlaybackEffect]) {
        if effects.contains(where: { $0.type == .stop }) {
            guard stopTask == nil else { return }
            isStopping = true
            var finalProgressOperation = progressOperationTask
            for effect in effects {
                switch effect.type {
                case .saveprogress:
                    finalProgressOperation = enqueueProgressOperation { runtime in
                        await runtime.persist(effect)
                    }
                case .stop:
                    break
                default:
                    // KMP orders candidate cancellation and pause before the durable save.
                    execute(effect)
                }
            }
            let progressToAwait = finalProgressOperation
            stopTask = Task { @MainActor [weak self] in
                guard let self else { return }
                defer {
                    self.isStopping = false
                    self.stopTask = nil
                }
                await progressToAwait?.value
                self.engine.teardown()
                self.systemMedia.clearNowPlaying()
                self.systemMedia.deactivate()
                self.localMediaReferences.removeAll()
            }
            return
        }
        for effect in effects { execute(effect) }
    }

    private func execute(_ effect: ErmaoShared.AudioPlaybackEffect) {
        switch effect.type {
        case .preparesource:
            guard let asset = effect.asset,
                  let resourceID = effect.resourceId,
                  let namespace = effect.namespaceKey else { return }
            engine.prepareSource(
                track: track(from: asset),
                resourceID: resourceID,
                namespace: namespace,
                sourceID: effect.sourceId
            )
        case .commitpreparedsource:
            if effect.autoplay {
                do {
                    try systemMedia.activate()
                } catch {
                    apply(stateMachine.engineFailed(
                        sourceId: effect.sourceId,
                        error: ErmaoShared.AudioPlaybackError(
                            code: "AUDIO_SESSION_ACTIVATION_FAILED",
                            recoverable: true,
                            requiresReauthentication: false
                        )
                    ))
                    return
                }
            }
            engine.commitPreparedSource(
                sourceID: effect.sourceId,
                positionMillis: effect.positionMillis,
                playbackRate: effect.playbackRate,
                autoplay: effect.autoplay
            )
        case .cancelpreparedsource:
            engine.cancelPreparedSource(sourceID: effect.sourceId)
        case .play:
            do {
                try systemMedia.activate()
                engine.play()
            } catch {
                receive(.failed(
                    sourceID: effect.sourceId,
                    failure: AudioEngineFailure(code: .unknown, detail: nil)
                ))
            }
        case .pause:
            engine.pause()
        case .seek:
            engine.seek(
                sourceID: effect.sourceId,
                operationID: effect.operationId,
                to: effect.positionMillis
            )
        case .setplaybackrate:
            engine.setPlaybackRate(effect.playbackRate)
        case .saveprogress:
            enqueueProgressOperation { runtime in await runtime.persist(effect) }
        case .stop:
            engine.teardown()
        default:
            break
        }
    }

    private func persist(_ effect: ErmaoShared.AudioPlaybackEffect) async {
        do {
            try await progressAdapter.save(effect)
            apply(stateMachine.progressSaved(sourceId: effect.sourceId, failed: false))
        } catch {
            apply(stateMachine.progressSaved(sourceId: effect.sourceId, failed: true))
        }
    }

    @discardableResult
    private func enqueueProgressOperation(
        _ operation: @escaping @MainActor (AudioPlaybackRuntime) async -> Void
    ) -> Task<Void, Never> {
        let previous = progressOperationTask
        let task = Task { @MainActor [weak self] in
            await previous?.value
            guard let self, !Task.isCancelled else { return }
            await operation(self)
        }
        progressOperationTask = task
        return task
    }

    private func enqueueProgressRestore(
        _ operation: @escaping @MainActor (AudioPlaybackRuntime) async throws -> ErmaoShared.AudioReaderLocation?
    ) async throws -> ErmaoShared.AudioReaderLocation? {
        let previous = progressOperationTask
        let restoreTask: Task<ErmaoShared.AudioReaderLocation?, Error> = Task { @MainActor [weak self] in
            await previous?.value
            guard let self else { throw CancellationError() }
            try Task.checkCancellation()
            return try await operation(self)
        }
        progressOperationTask = Task { @MainActor in
            _ = try? await restoreTask.value
        }
        return try await restoreTask.value
    }

    private func render(_ shared: ErmaoShared.AudioPlaybackSnapshot) {
        sharedSnapshot = shared
        snapshot = AudioPlaybackSnapshot(shared: shared) { [localMediaReferences] asset in
            localMediaReferences[mediaKey(resourceID: asset.resourceId, assetID: asset.assetId)]
                ?? asset.apiPath
        }
        scheduleSleepWakeIfNeeded()
        if snapshot.hasSession {
            systemMedia.updateNowPlaying(snapshot: snapshot, artwork: nil)
        }
    }

    private func scheduleSleepWakeIfNeeded() {
        let deadline = snapshot.sleepTimerEndsAtEpochMillis
        guard deadline != scheduledSleepDeadline else { return }
        scheduledSleepDeadline = deadline
        sleepWakeTask?.cancel()
        guard let deadline else {
            sleepWakeTask = nil
            return
        }
        sleepWakeTask = Task { @MainActor [weak self] in
            let now = Int64(Date().timeIntervalSince1970 * 1_000)
            if deadline > now {
                do { try await Task.sleep(for: .milliseconds(deadline - now)) }
                catch { return }
            }
            guard let self, !Task.isCancelled else { return }
            self.apply(self.stateMachine.sleepTimerElapsed(
                observedAtMonotonicMillis: Int64(ProcessInfo.processInfo.systemUptime * 1_000)
            ))
        }
    }

    private func track(from asset: ErmaoShared.AudioAsset) -> AudioTrack {
        AudioTrack(
            assetID: asset.assetId,
            title: asset.title,
            mediaReference: localMediaReferences[
                mediaKey(resourceID: asset.resourceId, assetID: asset.assetId)
            ] ?? asset.apiPath,
            mimeType: asset.mimeType,
            codec: asset.codec,
            sizeBytes: asset.sizeBytes,
            durationMillis: asset.durationMillis?.int64Value ?? 0,
            discNumber: asset.discNumber?.intValue,
            trackNumber: asset.trackNumber?.intValue,
            sortOrder: Int(asset.sortOrder)
        )
    }

    private func sharedError(for error: Error) -> ErmaoShared.AudioPlaybackError {
        let code: String
        let recoverable: Bool
        if let adapter = error as? AudioAdapterError {
            code = adapter.errorCode.rawValue
            recoverable = adapter != .invalidResponse
        } else if (error as NSError).domain == NSURLErrorDomain {
            code = AudioRecoverableErrorCode.networkRetryable.rawValue
            recoverable = true
        } else {
            code = AudioRecoverableErrorCode.unknown.rawValue
            recoverable = true
        }
        return ErmaoShared.AudioPlaybackError(
            code: code,
            recoverable: recoverable,
            requiresReauthentication: code == AudioRecoverableErrorCode.unauthorized.rawValue
        )
    }

    private func sharedError(for failure: AudioEngineFailure) -> ErmaoShared.AudioPlaybackError {
        let code = switch failure.code {
        case .codecUnsupported: AudioRecoverableErrorCode.codecUnsupported.rawValue
        case .authorization: AudioRecoverableErrorCode.unauthorized.rawValue
        case .network: AudioRecoverableErrorCode.networkRetryable.rawValue
        case .unknown:
            failure.detail == AudioRecoverableErrorCode.localArtifactUnavailable.rawValue
                ? AudioRecoverableErrorCode.localArtifactUnavailable.rawValue
                : AudioRecoverableErrorCode.unknown.rawValue
        }
        return ErmaoShared.AudioPlaybackError(
            code: code,
            recoverable: true,
            requiresReauthentication: failure.code == .authorization
        )
    }

    private func mediaKey(resourceID: String, assetID: String) -> String {
        "\(resourceID)\u{1f}\(assetID)"
    }
}

private extension AudioLaunchIntent {
    var shared: ErmaoShared.AudioLaunchIntent {
        ErmaoShared.AudioLaunchIntent(
            resourceId: resourceID,
            assetId: assetID,
            chapterId: chapterID,
            positionMillis: positionMillis.map(KotlinLong.init(longLong:)),
            autoplay: autoplay
        )
    }
}

private extension String {
    var trimmedNonEmpty: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
