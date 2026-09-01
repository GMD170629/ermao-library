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

enum AudioEngineEvent: Equatable, Sendable {
    case ready(sourceID: UUID, durationMillis: Int64?)
    case playing(sourceID: UUID)
    case paused(sourceID: UUID)
    case buffering(sourceID: UUID)
    case position(sourceID: UUID, positionMillis: Int64, durationMillis: Int64?)
    case ended(sourceID: UUID)
    case failed(sourceID: UUID, failure: AudioEngineFailure)

    var sourceID: UUID {
        switch self {
        case .ready(let sourceID, _), .playing(let sourceID), .paused(let sourceID),
             .buffering(let sourceID), .ended(let sourceID):
            sourceID
        case .position(let sourceID, _, _), .failed(let sourceID, _):
            sourceID
        }
    }
}

@MainActor
protocol AudioPlaybackEngine: AnyObject {
    var eventHandler: ((AudioEngineEvent) -> Void)? { get set }
    func replaceCurrentSource(
        track: AudioTrack,
        resourceID: String,
        namespace: String,
        sourceID: UUID,
        autoplay: Bool
    )
    func play()
    func pause()
    func seek(to positionMillis: Int64)
    func setPlaybackRate(_ rate: Double)
    func teardown()
}

/// AVQueuePlayer is intentionally owned here, below the runtime and above the
/// SwiftUI views. A single current item is committed at a time so changing a
/// Resource does not create a second business session; the queue API remains
/// available for future bounded next-track metadata prefetch.
@MainActor
final class IosAVAudioEngine: NSObject, AudioPlaybackEngine {
    var eventHandler: ((AudioEngineEvent) -> Void)?

    private let mediaAdapter: any AudioMediaStreamAdapter
    private let player: AVQueuePlayer
    private var resourceLoader: IosAudioResourceLoader?
    private var currentItem: AVPlayerItem?
    private var currentSourceID: UUID?
    private var currentTrack: AudioTrack?
    private var currentNamespace: String?
    private var currentRate = 1.0
    private var timeObserver: Any?
    private var observations: [NSKeyValueObservation] = []
    private var endObserver: NSObjectProtocol?
    private var didEmitBuffering = false

    init(mediaAdapter: any AudioMediaStreamAdapter) {
        self.mediaAdapter = mediaAdapter
        player = AVQueuePlayer()
        super.init()
        player.actionAtItemEnd = .pause
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(value: 1, timescale: 2),
            queue: .main
        ) { [weak self] time in
            guard let self else { return }
            Task { @MainActor in self.emitPosition(time: time) }
        }
    }

    deinit {}

    func replaceCurrentSource(
        track: AudioTrack,
        resourceID: String,
        namespace: String,
        sourceID: UUID,
        autoplay: Bool
    ) {
        removeCurrentObservers()
        player.pause()
        player.removeAllItems()
        resourceLoader?.cancelAllRequests()
        resourceLoader = nil
        currentItem = nil
        currentSourceID = sourceID
        currentTrack = track
        currentNamespace = namespace
        didEmitBuffering = false

        let asset: AVURLAsset
        if let localURL = URL(string: track.mediaReference), localURL.isFileURL {
            guard FileManager.default.fileExists(atPath: localURL.path) else {
                eventHandler?(.failed(
                    sourceID: sourceID,
                    failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_LOCAL_ARTIFACT_UNAVAILABLE")
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
            let loader = IosAudioResourceLoader(adapter: mediaAdapter, request: request)
            asset = AVURLAsset(
                url: IosAudioResourceLoader.url(assetID: track.assetID),
                options: [AVURLAssetPreferPreciseDurationAndTimingKey: true]
            )
            asset.resourceLoader.setDelegate(loader, queue: .main)
            resourceLoader = loader
        }
        let item = AVPlayerItem(asset: asset)
        // The stream is intentionally not buffered into memory. Let AVPlayer
        // maintain its bounded forward buffer while the adapter delivers ranges.
        item.preferredForwardBufferDuration = 0
        player.insert(item, after: nil)
        currentItem = item
        observe(item: item, sourceID: sourceID)
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
        setPlaybackRate(currentRate)
        if autoplay { play() }
    }

    func play() {
        guard currentItem != nil else { return }
        player.playImmediately(atRate: Float(currentRate))
        if let currentSourceID { eventHandler?(.playing(sourceID: currentSourceID)) }
    }

    func pause() {
        guard currentItem != nil else { return }
        player.pause()
        if let currentSourceID { eventHandler?(.paused(sourceID: currentSourceID)) }
    }

    func seek(to positionMillis: Int64) {
        guard let currentItem else { return }
        let seconds = max(0, Double(positionMillis) / 1000)
        let time = CMTime(seconds: seconds, preferredTimescale: 1_000)
        currentItem.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in
                guard let sourceID = self.currentSourceID else { return }
                self.emitPosition(time: time)
                self.eventHandler?(.ready(sourceID: sourceID, durationMillis: self.durationMillis()))
            }
        }
    }

    func setPlaybackRate(_ rate: Double) {
        currentRate = AudioBootstrap.normalizedRate(rate)
        player.defaultRate = Float(currentRate)
        if player.timeControlStatus == .playing { player.rate = Float(currentRate) }
    }

    func teardown() {
        removeCurrentObservers()
        if let timeObserver { player.removeTimeObserver(timeObserver); self.timeObserver = nil }
        player.pause()
        player.removeAllItems()
        resourceLoader?.cancelAllRequests()
        resourceLoader = nil
        currentItem = nil
        currentSourceID = nil
        currentTrack = nil
        currentNamespace = nil
    }

    private func observe(item: AVPlayerItem, sourceID: UUID) {
        observations = [
            item.observe(\AVPlayerItem.status, options: [.initial, .new]) { [weak self] item, _ in
                Task { @MainActor in self?.handleStatus(item.status, sourceID: sourceID, error: item.error) }
            },
            item.observe(\AVPlayerItem.isPlaybackBufferEmpty, options: [.new]) { [weak self] item, _ in
                Task { @MainActor in
                    guard let self, self.currentSourceID == sourceID, item.isPlaybackBufferEmpty else { return }
                    self.didEmitBuffering = true
                    self.eventHandler?(.buffering(sourceID: sourceID))
                }
            },
            item.observe(\AVPlayerItem.isPlaybackLikelyToKeepUp, options: [.new]) { [weak self] item, _ in
                Task { @MainActor in
                    guard let self, self.currentSourceID == sourceID, item.isPlaybackLikelyToKeepUp else { return }
                    self.didEmitBuffering = false
                    self.eventHandler?(.ready(sourceID: sourceID, durationMillis: self.durationMillis()))
                }
            },
            player.observe(\AVQueuePlayer.timeControlStatus, options: [.new]) { [weak self] player, _ in
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
                        if !self.didEmitBuffering { self.eventHandler?(.paused(sourceID: sourceID)) }
                    @unknown default: break
                    }
                }
            }
        ]
    }

    private func removeCurrentObservers() {
        observations.forEach { $0.invalidate() }
        observations.removeAll()
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
            self.endObserver = nil
        }
    }

    private func handleStatus(_ status: AVPlayerItem.Status, sourceID: UUID, error: Error?) {
        guard currentSourceID == sourceID else { return }
        switch status {
        case .readyToPlay:
            eventHandler?(.ready(sourceID: sourceID, durationMillis: durationMillis()))
        case .failed:
            eventHandler?(.failed(sourceID: sourceID, failure: mapFailure(error)))
        case .unknown:
            break
        @unknown default:
            break
        }
    }

    private func emitPosition(time: CMTime) {
        guard let sourceID = currentSourceID, currentItem != nil else { return }
        let milliseconds = max(0, Int64((time.seconds * 1_000).rounded()))
        eventHandler?(.position(
            sourceID: sourceID,
            positionMillis: milliseconds,
            durationMillis: durationMillis()
        ))
    }

    private func durationMillis() -> Int64? {
        guard let duration = currentItem?.duration.seconds, duration.isFinite, duration >= 0 else { return nil }
        return Int64((duration * 1_000).rounded())
    }

    private func mapFailure(_ error: Error?) -> AudioEngineFailure {
        guard let error else { return AudioEngineFailure(code: .unknown, detail: nil) }
        let nsError = error as NSError
        let code = AVError.Code(rawValue: nsError.code)
        let codecCodes: Set<AVError.Code> = [
            .decoderNotFound,
            .fileFormatNotRecognized,
            .contentIsNotAuthorized,
            .decoderNotFound
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
