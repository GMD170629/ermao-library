import AVFoundation
import Foundation

enum AudioEngineFailureCode: String, Equatable, Sendable {
    case codecUnsupported = "ENGINE_CODEC_UNSUPPORTED"
    case network = "AUDIO_NETWORK_FAILURE"
    case authorization = "AUDIO_AUTHORIZATION_FAILURE"
    case unknown = "AUDIO_ENGINE_FAILURE"
}

struct AudioEngineFailure: Error, Equatable, Sendable {
    let code: AudioEngineFailureCode
    let detail: String?
}

/// Facts observed from AVPlayer. Source ids are allocated by the KMP state machine.
enum AudioEngineEvent: Equatable, Sendable {
    case prepared(sourceID: Int64, durationMillis: Int64?)
    case committed(sourceID: Int64)
    case ready(sourceID: Int64, durationMillis: Int64?)
    case playing(sourceID: Int64)
    case paused(sourceID: Int64)
    case buffering(sourceID: Int64)
    case position(sourceID: Int64, positionMillis: Int64, durationMillis: Int64?)
    case seekCompleted(
        sourceID: Int64,
        operationID: Int64,
        positionMillis: Int64,
        durationMillis: Int64?
    )
    case seekFailed(sourceID: Int64, operationID: Int64, failure: AudioEngineFailure)
    case ended(sourceID: Int64)
    case failed(sourceID: Int64, failure: AudioEngineFailure)

    var sourceID: Int64 {
        switch self {
        case .prepared(let sourceID, _), .committed(let sourceID), .ready(let sourceID, _),
             .playing(let sourceID), .paused(let sourceID), .buffering(let sourceID),
             .ended(let sourceID):
            sourceID
        case .position(let sourceID, _, _), .seekCompleted(let sourceID, _, _, _),
             .seekFailed(let sourceID, _, _), .failed(let sourceID, _):
            sourceID
        }
    }
}

@MainActor
protocol AudioPlaybackEngine: AnyObject {
    var eventHandler: ((AudioEngineEvent) -> Void)? { get set }

    /// Builds a paused candidate player and waits for its item to become ready.
    func prepareSource(
        track: AudioTrack,
        resourceID: String,
        namespace: String,
        sourceID: Int64
    )

    /// Seeks the ready candidate, then atomically swaps it in after KMP accepts the fact.
    func commitPreparedSource(
        sourceID: Int64,
        positionMillis: Int64,
        playbackRate: Double,
        autoplay: Bool
    )

    func cancelPreparedSource(sourceID: Int64)
    func play()
    func pause()
    func seek(sourceID: Int64, operationID: Int64, to positionMillis: Int64)
    func setPlaybackRate(_ rate: Double)
    func teardown()
}

@MainActor
final class IosAVAudioEngine: NSObject, AudioPlaybackEngine {
    var eventHandler: ((AudioEngineEvent) -> Void)?

    private final class PreparedSource {
        let sourceID: Int64
        let player: AVPlayer
        let item: AVPlayerItem
        let loader: IosAudioResourceLoader?
        var durationMillis: Int64?
        var statusObservation: NSKeyValueObservation?
        var commitTimeoutTask: Task<Void, Never>?
        var didReportReady = false

        init(
            sourceID: Int64,
            player: AVPlayer,
            item: AVPlayerItem,
            loader: IosAudioResourceLoader?
        ) {
            self.sourceID = sourceID
            self.player = player
            self.item = item
            self.loader = loader
        }
    }

    private let mediaAdapter: any AudioMediaStreamAdapter
    private var player = AVPlayer()
    private var preparedSource: PreparedSource?
    private var currentLoader: IosAudioResourceLoader?
    private var currentItem: AVPlayerItem?
    private var currentSourceID: Int64?
    private var activeSeekOperationID: Int64?
    private var seekTimeoutTask: Task<Void, Never>?
    private var currentRate = 1.0
    private var timeObserver: Any?
    private var observations: [NSKeyValueObservation] = []
    private var endObserver: NSObjectProtocol?
    private var didEmitBuffering = false

    init(mediaAdapter: any AudioMediaStreamAdapter) {
        self.mediaAdapter = mediaAdapter
        super.init()
        configure(player)
    }

    func prepareSource(
        track: AudioTrack,
        resourceID: String,
        namespace: String,
        sourceID: Int64
    ) {
        cancelAnyPreparedSource()

        let asset: AVURLAsset
        var loader: IosAudioResourceLoader?
        if let localURL = URL(string: track.mediaReference), localURL.isFileURL {
            guard FileManager.default.fileExists(atPath: localURL.path) else {
                eventHandler?(.failed(
                    sourceID: sourceID,
                    failure: AudioEngineFailure(
                        code: .unknown,
                        detail: "AUDIO_LOCAL_ARTIFACT_UNAVAILABLE"
                    )
                ))
                return
            }
            asset = AVURLAsset(
                url: localURL,
                options: [AVURLAssetPreferPreciseDurationAndTimingKey: true]
            )
        } else {
            let request = AudioMediaStreamRequest(
                namespace: namespace,
                resourceID: resourceID,
                assetID: track.assetID,
                mediaReference: track.mediaReference,
                mimeType: track.mimeType,
                sizeBytes: track.sizeBytes,
                durationMillis: track.durationMillis,
                codec: track.codec,
                byteRange: nil
            )
            let sourceLoader = IosAudioResourceLoader(adapter: mediaAdapter, request: request)
            asset = AVURLAsset(
                url: IosAudioResourceLoader.url(
                    assetID: track.assetID,
                    mimeType: track.mimeType,
                    sourceID: sourceID
                ),
                options: [
                    AVURLAssetPreferPreciseDurationAndTimingKey: false,
                    AVURLAssetOverrideMIMETypeKey: IosAudioMediaType.avFoundationMIMEType(
                        for: track.mimeType
                    )
                ]
            )
            asset.resourceLoader.setDelegate(sourceLoader, queue: .main)
            loader = sourceLoader
        }

        let item = AVPlayerItem(asset: asset, automaticallyLoadedAssetKeys: ["playable"])
        item.preferredForwardBufferDuration = 0
        let candidatePlayer = AVPlayer(playerItem: item)
        configure(candidatePlayer)
        let prepared = PreparedSource(
            sourceID: sourceID,
            player: candidatePlayer,
            item: item,
            loader: loader
        )
        preparedSource = prepared
        prepared.statusObservation = item.observe(\.status, options: [.new]) { [weak self] item, _ in
            Task { @MainActor in
                self?.handlePreparedStatus(item.status, sourceID: sourceID, error: item.error)
            }
        }
        handlePreparedStatus(item.status, sourceID: sourceID, error: item.error)
    }

    func commitPreparedSource(
        sourceID: Int64,
        positionMillis: Int64,
        playbackRate: Double,
        autoplay: Bool
    ) {
        guard let prepared = preparedSource,
              prepared.sourceID == sourceID,
              prepared.didReportReady else { return }

        let target = CMTime(
            seconds: max(0, Double(positionMillis) / 1_000),
            preferredTimescale: 1_000
        )
        prepared.commitTimeoutTask?.cancel()
        prepared.commitTimeoutTask = Task { [weak self] in
            do {
                try await Task.sleep(for: .seconds(15))
            } catch {
                return
            }
            guard let self,
                  let active = self.preparedSource,
                  active === prepared,
                  active.sourceID == sourceID else { return }
            active.commitTimeoutTask = nil
            self.failPreparation(
                sourceID: sourceID,
                failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_SEEK_TIMEOUT")
            )
        }
        prepared.item.seek(
            to: target,
            toleranceBefore: .zero,
            toleranceAfter: .zero
        ) { [weak self] finished in
            Task { @MainActor in
                guard let self,
                      let prepared = self.preparedSource,
                      prepared.sourceID == sourceID else { return }
                prepared.commitTimeoutTask?.cancel()
                prepared.commitTimeoutTask = nil
                guard finished else {
                    self.failPreparation(
                        sourceID: sourceID,
                        failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_SEEK_FAILED")
                    )
                    return
                }
                self.finishCommit(
                    prepared,
                    target: target,
                    playbackRate: playbackRate,
                    autoplay: autoplay
                )
            }
        }
    }

    func cancelPreparedSource(sourceID: Int64) {
        guard preparedSource?.sourceID == sourceID else { return }
        cancelAnyPreparedSource()
    }

    func play() {
        guard currentItem != nil else { return }
        player.playImmediately(atRate: Float(currentRate))
    }

    func pause() {
        guard currentItem != nil else { return }
        player.pause()
    }

    func seek(sourceID: Int64, operationID: Int64, to positionMillis: Int64) {
        guard let currentItem, currentSourceID == sourceID else {
            eventHandler?(.seekFailed(
                sourceID: sourceID,
                operationID: operationID,
                failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_SEEK_SOURCE_UNAVAILABLE")
            ))
            return
        }
        let time = CMTime(
            seconds: max(0, Double(positionMillis) / 1_000),
            preferredTimescale: 1_000
        )
        invalidateActiveSeek(on: currentItem)
        activeSeekOperationID = operationID
        seekTimeoutTask = Task { [weak self] in
            do {
                try await Task.sleep(for: .seconds(15))
            } catch {
                return
            }
            guard let self,
                  self.currentSourceID == sourceID,
                  self.currentItem === currentItem,
                  self.activeSeekOperationID == operationID else { return }
            self.activeSeekOperationID = nil
            self.seekTimeoutTask = nil
            currentItem.cancelPendingSeeks()
            self.eventHandler?(.seekFailed(
                sourceID: sourceID,
                operationID: operationID,
                failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_SEEK_TIMEOUT")
            ))
        }
        currentItem.seek(
            to: time,
            toleranceBefore: .zero,
            toleranceAfter: .zero
        ) { [weak self] finished in
            Task { @MainActor in
                guard let self,
                      self.currentSourceID == sourceID,
                      self.currentItem === currentItem,
                      self.activeSeekOperationID == operationID else { return }
                self.activeSeekOperationID = nil
                self.seekTimeoutTask?.cancel()
                self.seekTimeoutTask = nil
                guard finished else {
                    self.eventHandler?(.seekFailed(
                        sourceID: sourceID,
                        operationID: operationID,
                        failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_SEEK_FAILED")
                    ))
                    return
                }
                let actualTime = currentItem.currentTime()
                let actualPosition = Self.milliseconds(from: actualTime) ?? positionMillis
                self.eventHandler?(.seekCompleted(
                    sourceID: sourceID,
                    operationID: operationID,
                    positionMillis: actualPosition,
                    durationMillis: self.durationMillis()
                ))
            }
        }
    }

    func setPlaybackRate(_ rate: Double) {
        guard rate.isFinite, rate > 0 else { return }
        currentRate = rate
        player.defaultRate = Float(rate)
        if player.timeControlStatus == .playing { player.rate = Float(rate) }
    }

    func teardown() {
        cancelAnyPreparedSource()
        invalidateActiveSeek(on: currentItem)
        removeCurrentObservers()
        if let timeObserver {
            player.removeTimeObserver(timeObserver)
            self.timeObserver = nil
        }
        player.pause()
        player.replaceCurrentItem(with: nil)
        currentLoader?.cancelAllRequests()
        currentLoader = nil
        currentItem = nil
        currentSourceID = nil
    }

    private func installTimeObserver(sourceID: Int64) {
        guard timeObserver == nil else { return }
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 1, timescale: 2),
            queue: .main
        ) { [weak self] time in
            Task { @MainActor in self?.emitPosition(time: time, sourceID: sourceID) }
        }
    }

    private func configure(_ player: AVPlayer) {
        player.actionAtItemEnd = .pause
        player.automaticallyWaitsToMinimizeStalling = false
    }

    private func finishCommit(
        _ prepared: PreparedSource,
        target: CMTime,
        playbackRate: Double,
        autoplay: Bool
    ) {
        let sourceID = prepared.sourceID
        prepared.statusObservation?.invalidate()
        prepared.statusObservation = nil
        preparedSource = nil

        invalidateActiveSeek(on: currentItem)
        removeCurrentObservers()
        if let timeObserver {
            player.removeTimeObserver(timeObserver)
            self.timeObserver = nil
        }
        player.pause()
        player.replaceCurrentItem(with: nil)
        currentLoader?.cancelAllRequests()

        player = prepared.player
        currentLoader = prepared.loader
        currentItem = prepared.item
        currentSourceID = sourceID
        didEmitBuffering = false
        installTimeObserver(sourceID: sourceID)
        installEndObserver(item: prepared.item, sourceID: sourceID)
        setPlaybackRate(playbackRate)
        eventHandler?(.committed(sourceID: sourceID))
        observe(item: prepared.item, sourceID: sourceID)
        emitPosition(time: target, sourceID: sourceID)
        if autoplay { play() }
    }

    private func observe(item: AVPlayerItem, sourceID: Int64) {
        observations = [
            item.observe(\.status, options: [.initial, .new]) { [weak self] item, _ in
                Task { @MainActor in
                    self?.handleStatus(item.status, sourceID: sourceID, error: item.error)
                }
            },
            item.observe(\.isPlaybackBufferEmpty, options: [.new]) { [weak self] item, _ in
                Task { @MainActor in
                    guard let self, self.currentSourceID == sourceID, item.isPlaybackBufferEmpty else {
                        return
                    }
                    self.didEmitBuffering = true
                    self.eventHandler?(.buffering(sourceID: sourceID))
                }
            },
            item.observe(\.isPlaybackLikelyToKeepUp, options: [.new]) { [weak self] item, _ in
                Task { @MainActor in
                    guard let self, self.currentSourceID == sourceID, item.isPlaybackLikelyToKeepUp else {
                        return
                    }
                    self.didEmitBuffering = false
                    self.eventHandler?(.ready(
                        sourceID: sourceID,
                        durationMillis: self.durationMillis()
                    ))
                }
            },
            player.observe(\.timeControlStatus, options: [.new]) { [weak self] player, _ in
                Task { @MainActor in
                    guard let self, self.currentSourceID == sourceID else { return }
                    switch player.timeControlStatus {
                    case .playing:
                        self.didEmitBuffering = false
                        self.eventHandler?(.playing(sourceID: sourceID))
                    case .waitingToPlayAtSpecifiedRate:
                        self.didEmitBuffering = true
                        self.eventHandler?(.buffering(sourceID: sourceID))
                    case .paused:
                        if !self.didEmitBuffering {
                            self.eventHandler?(.paused(sourceID: sourceID))
                        }
                    @unknown default:
                        break
                    }
                }
            }
        ]
    }

    private func installEndObserver(item: AVPlayerItem, sourceID: Int64) {
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.currentSourceID == sourceID else { return }
                self.eventHandler?(.ended(sourceID: sourceID))
            }
        }
    }

    private func removeCurrentObservers() {
        observations.forEach { $0.invalidate() }
        observations.removeAll()
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
            self.endObserver = nil
        }
    }

    private func invalidateActiveSeek(on item: AVPlayerItem?) {
        activeSeekOperationID = nil
        seekTimeoutTask?.cancel()
        seekTimeoutTask = nil
        item?.cancelPendingSeeks()
    }

    private func cancelAnyPreparedSource() {
        preparedSource?.statusObservation?.invalidate()
        preparedSource?.statusObservation = nil
        preparedSource?.commitTimeoutTask?.cancel()
        preparedSource?.commitTimeoutTask = nil
        preparedSource?.item.cancelPendingSeeks()
        preparedSource?.player.pause()
        preparedSource?.player.replaceCurrentItem(with: nil)
        preparedSource?.loader?.cancelAllRequests()
        preparedSource = nil
    }

    private func failPreparation(sourceID: Int64, failure: AudioEngineFailure) {
        guard preparedSource?.sourceID == sourceID else { return }
        cancelAnyPreparedSource()
        eventHandler?(.failed(sourceID: sourceID, failure: failure))
    }

    private func handleStatus(_ status: AVPlayerItem.Status, sourceID: Int64, error: Error?) {
        guard currentSourceID == sourceID else { return }
        switch status {
        case .readyToPlay:
            eventHandler?(.ready(sourceID: sourceID, durationMillis: durationMillis()))
        case .failed:
            invalidateActiveSeek(on: currentItem)
            eventHandler?(.failed(sourceID: sourceID, failure: mapFailure(error)))
        case .unknown:
            break
        @unknown default:
            break
        }
    }

    private func handlePreparedStatus(
        _ status: AVPlayerItem.Status,
        sourceID: Int64,
        error: Error?
    ) {
        guard let prepared = preparedSource,
              prepared.sourceID == sourceID else { return }
        switch status {
        case .readyToPlay:
            guard !prepared.didReportReady else { return }
            prepared.didReportReady = true
            prepared.durationMillis = Self.milliseconds(from: prepared.item.duration)
            eventHandler?(.prepared(
                sourceID: sourceID,
                durationMillis: prepared.durationMillis
            ))
        case .failed:
            failPreparation(sourceID: sourceID, failure: mapFailure(error))
        case .unknown:
            break
        @unknown default:
            break
        }
    }

    private func emitPosition(time: CMTime, sourceID: Int64) {
        guard currentSourceID == sourceID,
              currentItem != nil,
              activeSeekOperationID == nil,
              time.seconds.isFinite else { return }
        eventHandler?(.position(
            sourceID: sourceID,
            positionMillis: max(0, Int64((time.seconds * 1_000).rounded())),
            durationMillis: durationMillis()
        ))
    }

    private func durationMillis() -> Int64? {
        guard let seconds = currentItem?.duration.seconds, seconds.isFinite, seconds >= 0 else {
            return nil
        }
        return Int64((seconds * 1_000).rounded())
    }

    private static func milliseconds(from time: CMTime) -> Int64? {
        guard time.seconds.isFinite, time.seconds >= 0 else { return nil }
        return Int64((time.seconds * 1_000).rounded())
    }

    private func mapFailure(_ error: Error?) -> AudioEngineFailure {
        guard let error else { return AudioEngineFailure(code: .unknown, detail: nil) }
        let nsError = error as NSError
        let code = AVError.Code(rawValue: nsError.code)
        if code == .contentIsNotAuthorized {
            return AudioEngineFailure(code: .authorization, detail: nil)
        }
        let codecCodes: Set<AVError.Code> = [
            .decoderNotFound,
            .fileFormatNotRecognized
        ]
        if let code, codecCodes.contains(code) {
            return AudioEngineFailure(code: .codecUnsupported, detail: nil)
        }
        if nsError.domain == NSURLErrorDomain {
            return AudioEngineFailure(code: .network, detail: nil)
        }
        return AudioEngineFailure(code: .unknown, detail: nil)
    }
}
