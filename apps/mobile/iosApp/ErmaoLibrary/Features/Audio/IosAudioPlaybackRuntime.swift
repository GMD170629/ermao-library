import Foundation
import MediaPlayer
import SwiftUI
@preconcurrency import ErmaoShared

/// Single process-wide audio session owner. The instance is created by the App
/// composition root and injected into the authenticated shell; views never own
/// an AVPlayer or a network task.
@MainActor
final class AudioPlaybackRuntime: ObservableObject, AudioSystemMediaDelegate {
    @Published private(set) var snapshot: AudioPlaybackSnapshot

    let bootstrapGateway: any AudioBootstrapGateway
    let mediaAdapter: any AudioMediaStreamAdapter
    let progressAdapter: any AudioProgressAdapter
    let coverAdapter: any AudioCoverAdapter

    private let engine: any AudioPlaybackEngine
    private let systemMedia: any AudioSystemMediaControlling
    private let backgroundPlaybackEnabled: Bool
    /// KMP is the single owner of audio transition semantics. The local
    /// snapshot below is only the SwiftUI projection plus AVFoundation facts.
    private let sharedStateMachine: ErmaoShared.AudioPlaybackStateMachine
    private let sharedSleepTimer: ErmaoShared.AudioSleepTimer
    private var bootstrapTask: Task<Void, Never>?
    private var progressTask: Task<Void, Never>?
    private var sleepTimerTask: Task<Void, Never>?
    private var progressSaveTask: Task<Void, Never>?
    private var pendingProgress: (
        location: AudioLocation,
        namespace: String,
        completed: Bool,
        reason: IosAudioProgressSaveReason,
        durationMillis: Int64?
    )?
    private var lastLaunchIntent: AudioLaunchIntent?
    private var activeNamespace: String?
    private var currentSourceID: UUID?
    private var generation = 0
    private var trackIndex = -1
    private var positionMillis: Int64 = 0
    private var sleepTimerDeadline: ContinuousClock.Instant?
    private var sleepChapterTargetID: String?
    private var sharedSessionID: Int64?
    private var sharedPublication: ErmaoShared.AudioPublication?
    private var sessionContext: IosAudioSessionContext?
    private var isShuttingDown = false

    init(
        bootstrapGateway: any AudioBootstrapGateway,
        mediaAdapter: any AudioMediaStreamAdapter,
        progressAdapter: any AudioProgressAdapter,
        coverAdapter: any AudioCoverAdapter = EmptyAudioCoverAdapter(),
        engine: (any AudioPlaybackEngine)? = nil,
        systemMedia: (any AudioSystemMediaControlling)? = nil,
        backgroundPlaybackEnabled: Bool = true,
        stateMachine: ErmaoShared.AudioPlaybackStateMachine? = nil
    ) {
        self.bootstrapGateway = bootstrapGateway
        self.mediaAdapter = mediaAdapter
        self.progressAdapter = progressAdapter
        self.coverAdapter = coverAdapter
        self.engine = engine ?? IosAVAudioEngine(mediaAdapter: mediaAdapter)
        self.systemMedia = systemMedia ?? IosAudioSystemMediaController()
        self.backgroundPlaybackEnabled = backgroundPlaybackEnabled
        sharedStateMachine = stateMachine ?? ErmaoShared.AudioPlaybackStateMachine(
            initialPlaybackRate: 1
        )
        sharedSleepTimer = ErmaoShared.AudioSleepTimer(
            monotonicMillis: {
                KotlinLong(longLong: Int64(DispatchTime.now().uptimeNanoseconds / 1_000_000))
            }
        )
        snapshot = .idle()
        self.engine.eventHandler = { [weak self] event in
            self?.receive(event)
        }
        self.systemMedia.delegate = self
    }

    deinit {
        bootstrapTask?.cancel()
        progressTask?.cancel()
        sleepTimerTask?.cancel()
        progressSaveTask?.cancel()
    }

    // MARK: Public playback API

    func launch(_ intent: AudioLaunchIntent, namespace: String) {
        let resourceID = intent.resourceID.trimmingCharacters(in: .whitespacesAndNewlines)
        let namespace = namespace.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !resourceID.isEmpty, !namespace.isEmpty, !isShuttingDown else { return }
        let normalizedIntent = AudioLaunchIntent(
            resourceID: resourceID,
            assetID: intent.assetID?.trimmedNonEmpty,
            chapterID: intent.chapterID?.trimmedNonEmpty,
            positionMillis: intent.positionMillis.map { max(0, $0) },
            autoplay: intent.autoplay
        )
        generation += 1
        let requestGeneration = generation
        bootstrapTask?.cancel()
        lastLaunchIntent = normalizedIntent
        activeNamespace = namespace
        let previous = snapshot
        snapshot = AudioPlaybackSnapshot(
            lifecycle: .loading,
            namespace: namespace,
            bootstrap: previous.bootstrap,
            pendingResourceID: resourceID,
            resourceID: previous.resourceID,
            bookID: previous.bookID,
            trackIndex: previous.trackIndex,
            track: previous.track,
            chapter: previous.chapter,
            positionMillis: previous.positionMillis,
            durationMillis: previous.durationMillis,
            absolutePositionMillis: previous.absolutePositionMillis,
            totalDurationMillis: previous.totalDurationMillis,
            playbackRate: previous.playbackRate,
            skipBackwardSeconds: previous.skipBackwardSeconds,
            skipForwardSeconds: previous.skipForwardSeconds,
            syncState: previous.syncState,
            sleepTimerMode: previous.sleepTimerMode,
            sleepTimerEndsAtEpochMillis: previous.sleepTimerEndsAtEpochMillis,
            recoverableError: nil
        )
        bootstrapTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let envelope = try await self.bootstrapGateway.loadAudioBootstrap(
                    resourceID: resourceID,
                    namespace: namespace
                )
                try Task.checkCancellation()
                guard self.generation == requestGeneration,
                      self.activeNamespace == namespace,
                      !self.isShuttingDown else { return }
                if let progressSession = self.progressAdapter as? any AudioProgressSessionConfiguring {
                    await progressSession.configure(bootstrap: envelope)
                }
                guard self.generation == requestGeneration,
                      self.activeNamespace == namespace,
                      !self.isShuttingDown else { return }
                try self.commitBootstrap(
                    envelope.presentation,
                    intent: normalizedIntent,
                    generation: requestGeneration,
                    previous: previous
                )
            } catch is CancellationError {
                return
            } catch {
                guard self.generation == requestGeneration else { return }
                self.restoreAfterBootstrapFailure(
                    previous: previous,
                    requestedResourceID: resourceID,
                    error: self.mapBootstrapError(error)
                )
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
        guard sessionContext?.namespaceKey == namespace,
              fileURL.isFileURL,
              sizeBytes > 0,
              !bookID.isEmpty,
              !resourceID.isEmpty,
              !assetID.isEmpty else { return }
        generation += 1
        let requestGeneration = generation
        bootstrapTask?.cancel()
        let previous = snapshot
        activeNamespace = namespace
        let intent = AudioLaunchIntent(
            resourceID: resourceID,
            assetID: assetID,
            positionMillis: max(0, positionMillis),
            autoplay: autoplay
        )
        lastLaunchIntent = nil
        snapshot = AudioPlaybackSnapshot(
            lifecycle: .loading,
            namespace: namespace,
            bootstrap: previous.bootstrap,
            pendingResourceID: resourceID,
            resourceID: previous.resourceID,
            bookID: previous.bookID,
            trackIndex: previous.trackIndex,
            track: previous.track,
            chapter: previous.chapter,
            positionMillis: previous.positionMillis,
            durationMillis: previous.durationMillis,
            absolutePositionMillis: previous.absolutePositionMillis,
            totalDurationMillis: previous.totalDurationMillis,
            playbackRate: previous.playbackRate,
            skipBackwardSeconds: previous.skipBackwardSeconds,
            skipForwardSeconds: previous.skipForwardSeconds,
            syncState: previous.syncState,
            sleepTimerMode: previous.sleepTimerMode,
            sleepTimerEndsAtEpochMillis: previous.sleepTimerEndsAtEpochMillis,
            recoverableError: nil
        )
        let bootstrap = AudioBootstrap(
            namespace: namespace,
            userID: userID,
            book: AudioBookSummary(
                id: bookID,
                title: bookTitle,
                author: author,
                coverReference: nil
            ),
            resource: AudioResourceSummary(
                id: resourceID,
                bookID: bookID,
                title: resourceTitle,
                sortOrder: 0,
                durationMillis: max(0, durationMillis),
                chapterCount: 0,
                resourceCompleted: false
            ),
            tracks: [
                AudioTrack(
                    assetID: assetID,
                    title: resourceTitle,
                    mediaReference: fileURL.absoluteString,
                    mimeType: mimeType,
                    sizeBytes: sizeBytes,
                    durationMillis: max(0, durationMillis),
                    sortOrder: 0
                )
            ]
        )
        bootstrapTask = Task { @MainActor [weak self] in
            guard let self else { return }
            if let progress = self.progressAdapter as? any AudioLocalProgressSessionConfiguring {
                await progress.configureLocal(bookID: bookID, resourceID: resourceID)
            }
            guard self.generation == requestGeneration,
                  self.activeNamespace == namespace else { return }
            do {
                try self.commitBootstrap(
                    bootstrap,
                    intent: intent,
                    generation: requestGeneration,
                    previous: previous
                )
            } catch {
                self.restoreAfterBootstrapFailure(
                    previous: previous,
                    requestedResourceID: resourceID,
                    error: AudioRecoverableError(code: .localArtifactUnavailable)
                )
            }
        }
    }

    func retry() {
        guard let intent = lastLaunchIntent, let namespace = activeNamespace else { return }
        launch(
            AudioLaunchIntent(
                resourceID: intent.resourceID,
                assetID: intent.assetID,
                chapterID: intent.chapterID,
                positionMillis: intent.positionMillis,
                autoplay: false
            ),
            namespace: namespace
        )
    }

    func play() {
        guard snapshot.hasSession else { return }
        do {
            try systemMedia.activate()
            engine.play()
        } catch {
            receive(.failed(
                sourceID: currentSourceID ?? UUID(),
                failure: AudioEngineFailure(code: .unknown, detail: nil)
            ))
        }
    }

    func pause() {
        guard snapshot.hasSession else { return }
        engine.pause()
        enqueueProgressSave(completed: false)
    }

    func togglePlayback() {
        if snapshot.lifecycle == .playing || snapshot.lifecycle == .buffering {
            pause()
        } else {
            play()
        }
    }

    func seek(to positionMillis: Int64) {
        guard let track = snapshot.track else { return }
        let target = AudioPlaybackMath.clamp(positionMillis, upper: track.durationMillis)
        self.positionMillis = target
        engine.seek(to: target)
        updatePosition(target, durationMillis: snapshot.durationMillis)
        enqueueProgressSave(completed: false)
    }

    func seekBy(seconds: Int) {
        seek(to: positionMillis + Int64(seconds) * 1_000)
    }

    func seekAbsolute(to absolutePositionMillis: Int64) {
        guard let bootstrap = snapshot.bootstrap,
              let target = AudioPlaybackMath.targetForAbsolutePosition(
                  tracks: bootstrap.tracks,
                  absolutePositionMillis: absolutePositionMillis
              ) else { return }
        if target.trackIndex == trackIndex {
            seek(to: target.positionMillis)
        } else {
            selectTrack(index: target.trackIndex, positionMillis: target.positionMillis, autoplay: snapshot.isPlaying)
        }
    }

    func previousChapter() {
        guard let bootstrap = snapshot.bootstrap, let track = snapshot.track else { return }
        let chapters = bootstrap.chapters.filter { $0.assetID == track.assetID }
        if let chapter = AudioPlaybackMath.chapter(in: chapters, assetID: track.assetID, positionMillis: positionMillis),
           let index = chapters.firstIndex(where: { $0.id == chapter.id }), index > 0 {
            selectChapter(chapters[index - 1].id)
        } else if trackIndex > 0 {
            selectTrack(index: trackIndex - 1, positionMillis: 0, autoplay: snapshot.isPlaying)
        } else {
            seek(to: 0)
        }
    }

    func nextChapter() {
        guard let bootstrap = snapshot.bootstrap, let track = snapshot.track else { return }
        let chapters = bootstrap.chapters.filter { $0.assetID == track.assetID }
        if let chapter = AudioPlaybackMath.chapter(in: chapters, assetID: track.assetID, positionMillis: positionMillis),
           let index = chapters.firstIndex(where: { $0.id == chapter.id }), index + 1 < chapters.count {
            selectChapter(chapters[index + 1].id)
        } else if trackIndex + 1 < bootstrap.tracks.count {
            selectTrack(index: trackIndex + 1, positionMillis: 0, autoplay: snapshot.isPlaying)
        } else {
            seek(to: track.durationMillis)
        }
    }

    func selectTrack(index: Int, autoplay: Bool? = nil) {
        selectTrack(index: index, positionMillis: 0, autoplay: autoplay ?? snapshot.isPlaying)
    }

    func selectChapter(_ chapterID: String, autoplay: Bool? = nil) {
        guard let bootstrap = snapshot.bootstrap,
              let chapter = bootstrap.chapters.first(where: { $0.id == chapterID }),
              let trackIndex = bootstrap.tracks.firstIndex(where: { $0.assetID == chapter.assetID }) else { return }
        selectTrack(
            index: trackIndex,
            positionMillis: chapter.startMillis,
            autoplay: autoplay ?? snapshot.isPlaying
        )
    }

    func setPlaybackRate(_ rate: Double) {
        let normalized = AudioBootstrap.normalizedRate(rate)
        engine.setPlaybackRate(normalized)
        snapshot = snapshot.replacing(playbackRate: normalized)
        updateNowPlaying()
    }

    func setSleepTimer(minutes: Int?) {
        guard let minutes, minutes > 0 else {
            sleepTimerTask?.cancel()
            sleepTimerTask = nil
            sleepTimerDeadline = nil
            sleepChapterTargetID = nil
            snapshot = snapshot.clearingSleepTimer()
            updateNowPlaying()
            return
        }
        let deadline = ContinuousClock.now.advanced(by: .seconds(minutes * 60))
        sleepTimerDeadline = deadline
        sleepChapterTargetID = nil
        sleepTimerTask?.cancel()
        sleepTimerTask = Task { @MainActor [weak self] in
            do {
                try await ContinuousClock().sleep(until: deadline)
                guard !Task.isCancelled else { return }
                self?.sleepTimerFired()
            } catch is CancellationError {
                return
            } catch {
                return
            }
        }
        snapshot = snapshotWithSleepTimer(mode: .timer, deadline: deadline)
        updateNowPlaying()
    }

    func setSleepUntilChapterOrTrackEnd() {
        guard let track = snapshot.track else { return }
        sleepTimerTask?.cancel()
        sleepTimerTask = nil
        sleepTimerDeadline = nil
        sleepChapterTargetID = snapshot.chapter?.id ?? "track:\(track.assetID)"
        snapshot = snapshotWithSleepTimer(mode: .chapter, deadline: nil)
        updateNowPlaying()
    }

    /// System stop means pause + progress save. Only the app's explicit Stop
    /// action (in the Now Playing overflow menu) calls `stopAndClear`.
    func stopAndClear() {
        let namespace = activeNamespace
        enqueueProgressSave(completed: false)
        let saveTask = progressSaveTask
        generation += 1
        bootstrapTask?.cancel()
        currentSourceID = nil
        engine.teardown()
        progressTask?.cancel()
        progressTask = nil
        sleepTimerTask?.cancel()
        sleepTimerTask = nil
        sleepTimerDeadline = nil
        sleepChapterTargetID = nil
        activeNamespace = nil
        lastLaunchIntent = nil
        trackIndex = -1
        positionMillis = 0
        snapshot = .idle(namespace: namespace)
        systemMedia.clearNowPlaying()
        systemMedia.deactivate()
        // Keep the save Task alive through its owning property; awaiting is
        // intentionally left to the adapter's durable outbox.
        _ = saveTask
    }

    func prepareForNamespaceTransition() async {
        guard activeNamespace != nil else { return }
        enqueueProgressSave(completed: false)
        await progressSaveTask?.value
        if let namespace = activeNamespace { await progressAdapter.flush(namespace: namespace) }
        stopAndClear()
    }

    func sessionDidChange(isAuthenticated: Bool, session: IosAudioSessionContext?) {
        guard isAuthenticated, let session else {
            stopAndClear()
            sessionContext = nil
            configureSessionAdapters(nil)
            return
        }
        if let activeNamespace, activeNamespace != session.namespaceKey {
            stopAndClear()
        }
        sessionContext = session
        configureSessionAdapters(session)
    }

    private func configureSessionAdapters(_ session: IosAudioSessionContext?) {
        (bootstrapGateway as? any AudioSessionConfiguring)?.configure(session: session)
        (mediaAdapter as? any AudioSessionConfiguring)?.configure(session: session)
        (progressAdapter as? any AudioSessionConfiguring)?.configure(session: session)
    }

    func handleScenePhase(_ phase: ScenePhase) {
        switch phase {
        case .active:
            if snapshot.isPlaying { try? systemMedia.activate() }
        case .inactive, .background:
            enqueueProgressSave(completed: false)
            if phase == .background && !backgroundPlaybackEnabled {
                pause()
            }
        @unknown default:
            enqueueProgressSave(completed: false)
        }
    }

    func shutdown() {
        isShuttingDown = true
        stopAndClear()
    }

    // MARK: Shared engine/system callbacks

    func audioSystemDidBeginInterruption() {
        if snapshot.isPlaying { engine.pause() }
        enqueueProgressSave(completed: false)
    }

    func audioSystemDidEndInterruption(shouldResume: Bool) {
        if shouldResume, snapshot.lifecycle == .paused { play() }
        else { enqueueProgressSave(completed: false) }
    }

    func audioSystemDidLoseRoute() {
        if snapshot.isPlaying { engine.pause() }
        enqueueProgressSave(completed: false)
    }

    func audioSystemDidResetMediaServices() {
        guard let track = snapshot.track, let namespace = activeNamespace else { return }
        let wasPlaying = snapshot.isPlaying
        let sourceID = UUID()
        currentSourceID = sourceID
        engine.replaceCurrentSource(
            track: track,
            resourceID: snapshot.resourceID ?? "",
            namespace: namespace,
            sourceID: sourceID,
            autoplay: wasPlaying
        )
    }

    func audioSystemPlayRequested() -> MPRemoteCommandHandlerStatus {
        play(); return .success
    }

    func audioSystemPauseRequested() -> MPRemoteCommandHandlerStatus {
        pause(); return .success
    }

    func audioSystemStopRequested() -> MPRemoteCommandHandlerStatus {
        pause(); return .success
    }

    func audioSystemSeekRequested(positionSeconds: Double) -> MPRemoteCommandHandlerStatus {
        guard positionSeconds.isFinite else { return .commandFailed }
        seekAbsolute(to: Int64(max(0, positionSeconds) * 1_000))
        return .success
    }

    func audioSystemSkipBackwardRequested() -> MPRemoteCommandHandlerStatus {
        seekBy(seconds: -snapshot.skipBackwardSeconds); return .success
    }

    func audioSystemSkipForwardRequested() -> MPRemoteCommandHandlerStatus {
        seekBy(seconds: snapshot.skipForwardSeconds); return .success
    }

    func audioSystemPreviousRequested() -> MPRemoteCommandHandlerStatus {
        previousChapter(); return .success
    }

    func audioSystemNextRequested() -> MPRemoteCommandHandlerStatus {
        nextChapter(); return .success
    }

    // MARK: Bootstrap and engine state

    private func commitBootstrap(
        _ bootstrap: AudioBootstrap,
        intent: AudioLaunchIntent,
        generation: Int,
        previous: AudioPlaybackSnapshot
    ) throws {
        guard bootstrap.schemaVersion == 4,
              !bootstrap.namespace.isEmpty,
              bootstrap.namespace == activeNamespace,
              !bootstrap.tracks.isEmpty else {
            throw AudioAdapterError.invalidResponse
        }
        let tracks = bootstrap.tracks
        let target = target(for: bootstrap, intent: intent)
        guard target.trackIndex >= 0, target.trackIndex < tracks.count else {
            throw AudioAdapterError.resourceUnavailable
        }
        let targetTrack = tracks[target.trackIndex]
        let sourceID = UUID()
        currentSourceID = sourceID
        trackIndex = target.trackIndex
        positionMillis = AudioPlaybackMath.clamp(target.positionMillis, upper: targetTrack.durationMillis)
        activeNamespace = bootstrap.namespace
        currentSourceID = sourceID
        do {
            try systemMedia.activate()
        } catch {
            throw AudioAdapterError.resourceUnavailable
        }
        engine.setPlaybackRate(bootstrap.playbackRate)
        engine.replaceCurrentSource(
            track: targetTrack,
            resourceID: bootstrap.resource.id,
            namespace: bootstrap.namespace,
            sourceID: sourceID,
            autoplay: intent.autoplay
        )
        engine.seek(to: positionMillis)
        snapshot = makeSnapshot(
            bootstrap: bootstrap,
            lifecycle: .ready,
            pendingResourceID: nil,
            syncState: previous.syncState,
            recoverableError: nil
        )
        updateNowPlaying()
        if intent.autoplay {
            engine.play()
        }
        startProgressTimer()
        _ = generation
    }

    private func restoreAfterBootstrapFailure(
        previous: AudioPlaybackSnapshot,
        requestedResourceID: String,
        error: AudioRecoverableError
    ) {
        if previous.hasSession {
            snapshot = AudioPlaybackSnapshot(
                lifecycle: previous.lifecycle == .playing ? .playing : .paused,
                namespace: previous.namespace,
                bootstrap: previous.bootstrap,
                pendingResourceID: requestedResourceID,
                resourceID: previous.resourceID,
                bookID: previous.bookID,
                trackIndex: previous.trackIndex,
                track: previous.track,
                chapter: previous.chapter,
                positionMillis: previous.positionMillis,
                durationMillis: previous.durationMillis,
                absolutePositionMillis: previous.absolutePositionMillis,
                totalDurationMillis: previous.totalDurationMillis,
                playbackRate: previous.playbackRate,
                skipBackwardSeconds: previous.skipBackwardSeconds,
                skipForwardSeconds: previous.skipForwardSeconds,
                syncState: previous.syncState,
                sleepTimerMode: previous.sleepTimerMode,
                sleepTimerEndsAtEpochMillis: previous.sleepTimerEndsAtEpochMillis,
                recoverableError: error
            )
        } else {
            snapshot = AudioPlaybackSnapshot(
                lifecycle: .error,
                namespace: activeNamespace,
                bootstrap: nil,
                pendingResourceID: requestedResourceID,
                resourceID: nil,
                bookID: nil,
                trackIndex: -1,
                track: nil,
                chapter: nil,
                positionMillis: 0,
                durationMillis: 0,
                absolutePositionMillis: 0,
                totalDurationMillis: 0,
                playbackRate: 1,
                skipBackwardSeconds: 15,
                skipForwardSeconds: 30,
                syncState: .failed,
                sleepTimerMode: nil,
                sleepTimerEndsAtEpochMillis: nil,
                recoverableError: error
            )
        }
        updateNowPlaying()
    }

    private func target(
        for bootstrap: AudioBootstrap,
        intent: AudioLaunchIntent
    ) -> (trackIndex: Int, positionMillis: Int64) {
        if let chapterID = intent.chapterID,
           let chapter = bootstrap.chapters.first(where: { $0.id == chapterID }),
           let index = bootstrap.tracks.firstIndex(where: { $0.assetID == chapter.assetID }) {
            return (index, intent.positionMillis ?? chapter.startMillis)
        }
        if let assetID = intent.assetID,
           let index = bootstrap.tracks.firstIndex(where: { $0.assetID == assetID }) {
            return (index, intent.positionMillis ?? 0)
        }
        if let resume = bootstrap.resumeLocation,
           let index = bootstrap.tracks.firstIndex(where: { $0.assetID == resume.assetID }) {
            return (index, intent.positionMillis ?? resume.positionMillis)
        }
        return (0, intent.positionMillis ?? 0)
    }

    private func selectTrack(index: Int, positionMillis: Int64, autoplay: Bool) {
        guard let bootstrap = snapshot.bootstrap,
              index >= 0, index < bootstrap.tracks.count else { return }
        let track = bootstrap.tracks[index]
        let oldPosition = self.positionMillis
        enqueueProgressSave(completed: false, positionOverride: oldPosition)
        trackIndex = index
        self.positionMillis = AudioPlaybackMath.clamp(positionMillis, upper: track.durationMillis)
        let sourceID = UUID()
        currentSourceID = sourceID
        guard let namespace = activeNamespace else { return }
        engine.replaceCurrentSource(
            track: track,
            resourceID: bootstrap.resource.id,
            namespace: namespace,
            sourceID: sourceID,
            autoplay: autoplay
        )
        engine.seek(to: self.positionMillis)
        snapshot = makeSnapshot(
            bootstrap: bootstrap,
            lifecycle: autoplay ? .ready : .paused,
            pendingResourceID: nil,
            syncState: snapshot.syncState,
            recoverableError: nil
        )
        enqueueProgressSave(completed: false)
        updateNowPlaying()
    }

    private func receive(_ event: AudioEngineEvent) {
        guard let currentSourceID, event.sourceID == currentSourceID else { return }
        switch event {
        case .ready(_, let durationMillis):
            let duration = durationMillis ?? snapshot.durationMillis
            snapshot = snapshotWith(lifecycle: snapshot.lifecycle == .buffering ? .ready : nil, durationMillis: duration)
            updateNowPlaying()
        case .playing:
            snapshot = snapshotWith(lifecycle: .playing)
            startProgressTimer()
            updateNowPlaying()
        case .paused:
            if snapshot.lifecycle != .ended {
                snapshot = snapshotWith(lifecycle: .paused)
                enqueueProgressSave(completed: false)
                updateNowPlaying()
            }
        case .buffering:
            snapshot = snapshotWith(lifecycle: .buffering)
            updateNowPlaying()
        case .position(_, let position, let duration):
            updatePosition(position, durationMillis: duration ?? snapshot.durationMillis)
            evaluateSleepTimer()
        case .ended:
            handleEnded()
        case .failed(_, let failure):
            let code: AudioRecoverableErrorCode = switch failure.code {
            case .codecUnsupported: .codecUnsupported
            case .authorization: .unauthorized
            case .network: .networkRetryable
            case .unknown: .unknown
            }
            snapshot = snapshotWith(
                lifecycle: .error,
                recoverableError: AudioRecoverableError(code: code, detail: failure.detail)
            )
            progressTask?.cancel()
            enqueueProgressSave(completed: false)
            updateNowPlaying()
        }
    }

    private func handleEnded() {
        guard let bootstrap = snapshot.bootstrap else { return }
        enqueueProgressSave(completed: false)
        if trackIndex + 1 < bootstrap.tracks.count {
            selectTrack(index: trackIndex + 1, positionMillis: 0, autoplay: true)
        } else {
            positionMillis = snapshot.durationMillis
            snapshot = snapshotWith(lifecycle: .ended)
            progressTask?.cancel()
            enqueueProgressSave(completed: true)
            updateNowPlaying()
        }
    }

    private func updatePosition(_ position: Int64, durationMillis: Int64) {
        guard let track = snapshot.track else { return }
        positionMillis = AudioPlaybackMath.clamp(position, upper: max(track.durationMillis, durationMillis))
        let absolute = snapshot.bootstrap.map {
            AudioPlaybackMath.absolutePosition(
                tracks: $0.tracks,
                trackIndex: trackIndex,
                positionMillis: positionMillis
            )
        } ?? positionMillis
        let chapter = snapshot.bootstrap.flatMap {
            AudioPlaybackMath.chapter(in: $0.chapters, assetID: track.assetID, positionMillis: positionMillis)
        }
        snapshot = AudioPlaybackSnapshot(
            lifecycle: snapshot.lifecycle,
            namespace: snapshot.namespace,
            bootstrap: snapshot.bootstrap,
            pendingResourceID: snapshot.pendingResourceID,
            resourceID: snapshot.resourceID,
            bookID: snapshot.bookID,
            trackIndex: trackIndex,
            track: track,
            chapter: chapter,
            positionMillis: positionMillis,
            durationMillis: max(0, durationMillis),
            absolutePositionMillis: absolute,
            totalDurationMillis: snapshot.totalDurationMillis,
            playbackRate: snapshot.playbackRate,
            skipBackwardSeconds: snapshot.skipBackwardSeconds,
            skipForwardSeconds: snapshot.skipForwardSeconds,
            syncState: snapshot.syncState,
            sleepTimerMode: snapshot.sleepTimerMode,
            sleepTimerEndsAtEpochMillis: snapshot.sleepTimerEndsAtEpochMillis,
            recoverableError: snapshot.recoverableError
        )
        updateNowPlaying()
    }

    private func startProgressTimer() {
        progressTask?.cancel()
        progressTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(15)) }
                catch { return }
                guard let self, self.snapshot.lifecycle == .playing else { continue }
                self.enqueueProgressSave(completed: false)
            }
        }
    }

    private func enqueueProgressSave(completed: Bool, positionOverride: Int64? = nil) {
        guard let bootstrap = snapshot.bootstrap,
              let track = snapshot.track,
              let namespace = activeNamespace else { return }
        let position = positionOverride ?? positionMillis
        let chapter = AudioPlaybackMath.chapter(
            in: bootstrap.chapters,
            assetID: track.assetID,
            positionMillis: position
        )
        pendingProgress = (
            location: AudioLocation(
                resourceID: bootstrap.resource.id,
                assetID: track.assetID,
                chapterID: chapter?.id,
                positionMillis: position
            ),
            namespace: namespace,
            completed: completed,
            reason: .tick,
            durationMillis: track.durationMillis
        )
        snapshot = snapshotWith(syncState: .pending)
        guard progressSaveTask == nil else { return }
        progressSaveTask = Task { @MainActor [weak self] in
            guard let self else { return }
            while let pending = self.pendingProgress {
                self.pendingProgress = nil
                do {
                    let result = try await self.progressAdapter.saveLocation(
                        pending.location,
                        namespace: pending.namespace,
                        completed: pending.completed,
                        reason: .tick
                    )
                    if self.pendingProgress == nil {
                        self.snapshot = self.snapshotWith(syncState: result == .failed ? .failed : result == .pending ? .pending : .synced)
                    }
                } catch {
                    self.snapshot = self.snapshotWith(syncState: .failed)
                }
            }
            self.progressSaveTask = nil
        }
    }

    private func sleepTimerFired() {
        sleepTimerTask = nil
        sleepTimerDeadline = nil
        engine.pause()
        snapshot = snapshot.clearingSleepTimer()
        enqueueProgressSave(completed: false)
        updateNowPlaying()
    }

    private func evaluateSleepTimer() {
        guard snapshot.sleepTimerMode == .chapter, let target = sleepChapterTargetID else { return }
        let chapterReached = target == snapshot.chapter?.id && snapshot.positionMillis >= (snapshot.chapter?.endMillis ?? .max)
        let trackReached = target == "track:\(snapshot.track?.assetID ?? "")" && snapshot.positionMillis >= snapshot.durationMillis
        if chapterReached || trackReached { sleepTimerFired() }
    }

    private func snapshotWithSleepTimer(mode: AudioSleepTimerMode, deadline: ContinuousClock.Instant?) -> AudioPlaybackSnapshot {
        let epochMillis = deadline.map { Int64(Date().timeIntervalSince1970 * 1_000) + Int64($0.duration(to: ContinuousClock.now).components.seconds * -1_000) }
        return AudioPlaybackSnapshot(
            lifecycle: snapshot.lifecycle,
            namespace: snapshot.namespace,
            bootstrap: snapshot.bootstrap,
            pendingResourceID: snapshot.pendingResourceID,
            resourceID: snapshot.resourceID,
            bookID: snapshot.bookID,
            trackIndex: snapshot.trackIndex,
            track: snapshot.track,
            chapter: snapshot.chapter,
            positionMillis: snapshot.positionMillis,
            durationMillis: snapshot.durationMillis,
            absolutePositionMillis: snapshot.absolutePositionMillis,
            totalDurationMillis: snapshot.totalDurationMillis,
            playbackRate: snapshot.playbackRate,
            skipBackwardSeconds: snapshot.skipBackwardSeconds,
            skipForwardSeconds: snapshot.skipForwardSeconds,
            syncState: snapshot.syncState,
            sleepTimerMode: mode,
            sleepTimerEndsAtEpochMillis: epochMillis,
            recoverableError: snapshot.recoverableError
        )
    }

    private func makeSnapshot(
        bootstrap: AudioBootstrap,
        lifecycle: AudioPlaybackLifecycle,
        pendingResourceID: String?,
        syncState: AudioSyncState,
        recoverableError: AudioRecoverableError?
    ) -> AudioPlaybackSnapshot {
        let track = bootstrap.tracks[trackIndex]
        let chapter = AudioPlaybackMath.chapter(
            in: bootstrap.chapters,
            assetID: track.assetID,
            positionMillis: positionMillis
        )
        return AudioPlaybackSnapshot(
            lifecycle: lifecycle,
            namespace: bootstrap.namespace,
            bootstrap: bootstrap,
            pendingResourceID: pendingResourceID,
            resourceID: bootstrap.resource.id,
            bookID: bootstrap.book.id,
            trackIndex: trackIndex,
            track: track,
            chapter: chapter,
            positionMillis: positionMillis,
            durationMillis: track.durationMillis,
            absolutePositionMillis: AudioPlaybackMath.absolutePosition(
                tracks: bootstrap.tracks,
                trackIndex: trackIndex,
                positionMillis: positionMillis
            ),
            totalDurationMillis: bootstrap.totalDurationMillis,
            playbackRate: bootstrap.playbackRate,
            skipBackwardSeconds: bootstrap.skipBackwardSeconds,
            skipForwardSeconds: bootstrap.skipForwardSeconds,
            syncState: syncState,
            sleepTimerMode: snapshot.sleepTimerMode,
            sleepTimerEndsAtEpochMillis: snapshot.sleepTimerEndsAtEpochMillis,
            recoverableError: recoverableError
        )
    }

    private func snapshotWith(
        lifecycle: AudioPlaybackLifecycle? = nil,
        durationMillis: Int64? = nil,
        syncState: AudioSyncState? = nil,
        recoverableError: AudioRecoverableError?? = nil
    ) -> AudioPlaybackSnapshot {
        AudioPlaybackSnapshot(
            lifecycle: lifecycle ?? snapshot.lifecycle,
            namespace: snapshot.namespace,
            bootstrap: snapshot.bootstrap,
            pendingResourceID: snapshot.pendingResourceID,
            resourceID: snapshot.resourceID,
            bookID: snapshot.bookID,
            trackIndex: trackIndex,
            track: snapshot.track,
            chapter: snapshot.chapter,
            positionMillis: positionMillis,
            durationMillis: durationMillis ?? snapshot.durationMillis,
            absolutePositionMillis: snapshot.absolutePositionMillis,
            totalDurationMillis: snapshot.totalDurationMillis,
            playbackRate: snapshot.playbackRate,
            skipBackwardSeconds: snapshot.skipBackwardSeconds,
            skipForwardSeconds: snapshot.skipForwardSeconds,
            syncState: syncState ?? snapshot.syncState,
            sleepTimerMode: snapshot.sleepTimerMode,
            sleepTimerEndsAtEpochMillis: snapshot.sleepTimerEndsAtEpochMillis,
            recoverableError: recoverableError ?? snapshot.recoverableError
        )
    }

    private func updateNowPlaying() {
        systemMedia.updateNowPlaying(snapshot: snapshot, artwork: nil)
    }

    private func mapBootstrapError(_ error: Error) -> AudioRecoverableError {
        if let adapterError = error as? AudioAdapterError {
            return AudioRecoverableError(code: adapterError.errorCode)
        }
        if (error as NSError).domain == NSURLErrorDomain {
            return AudioRecoverableError(code: .networkRetryable)
        }
        return AudioRecoverableError(code: .unknown)
    }
}

private extension String {
    var trimmedNonEmpty: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
