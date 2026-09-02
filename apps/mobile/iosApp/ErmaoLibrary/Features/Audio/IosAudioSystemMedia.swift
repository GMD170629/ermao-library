@preconcurrency import AVFoundation
@preconcurrency import Foundation
@preconcurrency import MediaPlayer

@MainActor
protocol AudioSystemMediaDelegate: AnyObject {
    func audioSystemDidBeginInterruption()
    func audioSystemDidEndInterruption(shouldResume: Bool)
    func audioSystemDidLoseRoute()
    func audioSystemDidResetMediaServices()
    func audioSystemPlayRequested() -> MPRemoteCommandHandlerStatus
    func audioSystemPauseRequested() -> MPRemoteCommandHandlerStatus
    func audioSystemStopRequested() -> MPRemoteCommandHandlerStatus
    func audioSystemSeekRequested(positionSeconds: Double) -> MPRemoteCommandHandlerStatus
    func audioSystemSkipBackwardRequested() -> MPRemoteCommandHandlerStatus
    func audioSystemSkipForwardRequested() -> MPRemoteCommandHandlerStatus
    func audioSystemPreviousRequested() -> MPRemoteCommandHandlerStatus
    func audioSystemNextRequested() -> MPRemoteCommandHandlerStatus
}

@MainActor
protocol AudioSystemMediaControlling: AnyObject {
    var delegate: (any AudioSystemMediaDelegate)? { get set }
    func activate() throws
    func deactivate()
    func updateNowPlaying(snapshot: AudioPlaybackSnapshot, artwork: MPMediaItemArtwork?)
    func clearNowPlaying()
}

/// Owns only system media integration. Business state remains in
/// AudioPlaybackRuntime, and transport/authentication remains in KMP adapters.
@MainActor
final class IosAudioSystemMediaController: NSObject, AudioSystemMediaControlling {
    weak var delegate: (any AudioSystemMediaDelegate)?

    private let audioSession = AVAudioSession.sharedInstance()
    private let commandCenter = MPRemoteCommandCenter.shared()
    private var observers: [NSObjectProtocol] = []
    private var wasPlayingBeforeInterruption = false
    private var isPlaying = false
    private var isConfigured = false

    func activate() throws {
        if !isConfigured {
            configureNotifications()
            configureRemoteCommands()
            isConfigured = true
        }
        try audioSession.setCategory(
            .playback,
            mode: .spokenAudio,
            options: []
        )
        try audioSession.setActive(true, options: [])
    }

    func deactivate() {
        try? audioSession.setActive(false, options: [.notifyOthersOnDeactivation])
    }

    func updateNowPlaying(
        snapshot: AudioPlaybackSnapshot,
        artwork: MPMediaItemArtwork? = nil
    ) {
        isPlaying = snapshot.lifecycle == .playing
        guard snapshot.hasSession,
              let bootstrap = snapshot.bootstrap,
              let track = snapshot.track else {
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
            return
        }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: track.title,
            MPMediaItemPropertyAlbumTitle: bootstrap.book.title,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: TimeInterval(snapshot.absolutePositionMillis) / 1_000,
            MPMediaItemPropertyPlaybackDuration: TimeInterval(snapshot.totalDurationMillis) / 1_000,
            MPNowPlayingInfoPropertyPlaybackRate: snapshot.lifecycle == .playing ? snapshot.playbackRate : 0,
            MPNowPlayingInfoPropertyDefaultPlaybackRate: snapshot.playbackRate,
            MPNowPlayingInfoPropertyMediaType: NSNumber(value: MPNowPlayingInfoMediaType.audio.rawValue)
        ]
        if let author = bootstrap.book.author, !author.isEmpty {
            info[MPMediaItemPropertyArtist] = author
        }
        if let chapter = snapshot.chapter {
            info[MPNowPlayingInfoPropertyExternalContentIdentifier] = chapter.id
        }
        if let artwork { info[MPMediaItemPropertyArtwork] = artwork }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    func clearNowPlaying() {
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }

    deinit {}

    private func configureNotifications() {
        observers.append(
            NotificationCenter.default.addObserver(
                forName: AVAudioSession.interruptionNotification,
                object: audioSession,
                queue: .main
            ) { [weak self] notification in
                let rawType = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
                let rawOptions = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt
                Task { @MainActor in
                    self?.handleInterruption(rawType: rawType, rawOptions: rawOptions)
                }
            }
        )
        observers.append(
            NotificationCenter.default.addObserver(
                forName: AVAudioSession.routeChangeNotification,
                object: audioSession,
                queue: .main
            ) { [weak self] notification in
                let rawReason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                Task { @MainActor in self?.handleRouteChange(rawReason: rawReason) }
            }
        )
        observers.append(
            NotificationCenter.default.addObserver(
                forName: AVAudioSession.mediaServicesWereResetNotification,
                object: audioSession,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.delegate?.audioSystemDidResetMediaServices() }
            }
        )
    }

    private func configureRemoteCommands() {
        commandCenter.playCommand.isEnabled = true
        commandCenter.pauseCommand.isEnabled = true
        commandCenter.stopCommand.isEnabled = true
        commandCenter.changePlaybackPositionCommand.isEnabled = true
        commandCenter.skipBackwardCommand.preferredIntervals = [15]
        commandCenter.skipForwardCommand.preferredIntervals = [30]
        commandCenter.skipBackwardCommand.isEnabled = true
        commandCenter.skipForwardCommand.isEnabled = true
        commandCenter.previousTrackCommand.isEnabled = true
        commandCenter.nextTrackCommand.isEnabled = true

        commandCenter.playCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemPlayRequested() ?? .commandFailed
        }
        commandCenter.pauseCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemPauseRequested() ?? .commandFailed
        }
        commandCenter.stopCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemStopRequested() ?? .commandFailed
        }
        commandCenter.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            return self?.delegate?.audioSystemSeekRequested(positionSeconds: event.positionTime) ?? .commandFailed
        }
        commandCenter.skipBackwardCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemSkipBackwardRequested() ?? .commandFailed
        }
        commandCenter.skipForwardCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemSkipForwardRequested() ?? .commandFailed
        }
        commandCenter.previousTrackCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemPreviousRequested() ?? .commandFailed
        }
        commandCenter.nextTrackCommand.addTarget { [weak self] _ in
            self?.delegate?.audioSystemNextRequested() ?? .commandFailed
        }
    }

    private func handleInterruption(rawType: UInt?, rawOptions: UInt?) {
        guard let rawType,
              let type = AVAudioSession.InterruptionType(rawValue: rawType) else { return }
        switch type {
        case .began:
            wasPlayingBeforeInterruption = isPlaying
            delegate?.audioSystemDidBeginInterruption()
        case .ended:
            let options = rawOptions
                .map(AVAudioSession.InterruptionOptions.init(rawValue:)) ?? []
            delegate?.audioSystemDidEndInterruption(
                shouldResume: wasPlayingBeforeInterruption && options.contains(.shouldResume)
            )
            wasPlayingBeforeInterruption = false
        @unknown default:
            wasPlayingBeforeInterruption = false
        }
    }

    private func handleRouteChange(rawReason: UInt?) {
        guard let rawReason,
              let reason = AVAudioSession.RouteChangeReason(rawValue: rawReason) else { return }
        if reason == .oldDeviceUnavailable {
            delegate?.audioSystemDidLoseRoute()
        }
    }
}
