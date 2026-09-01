import Foundation

/// The user intention accepted by the mobile audio capability.
///
/// This type deliberately contains no URL, cookie, file path, or platform player
/// details. The shared bootstrap adapter owns authorization and transport.
struct AudioLaunchIntent: Hashable, Codable, Sendable {
    let resourceID: String
    let assetID: String?
    let chapterID: String?
    let positionMillis: Int64?
    let autoplay: Bool

    init(
        resourceID: String,
        assetID: String? = nil,
        chapterID: String? = nil,
        positionMillis: Int64? = nil,
        autoplay: Bool
    ) {
        self.resourceID = resourceID
        self.assetID = assetID
        self.chapterID = chapterID
        self.positionMillis = positionMillis
        self.autoplay = autoplay
    }
}

struct AudioLocation: Codable, Equatable, Sendable {
    let resourceID: String
    let assetID: String
    let chapterID: String?
    let positionMillis: Int64

    init(resourceID: String, assetID: String, chapterID: String?, positionMillis: Int64) {
        self.resourceID = resourceID
        self.assetID = assetID
        self.chapterID = chapterID
        self.positionMillis = max(0, positionMillis)
    }
}

struct AudioBookSummary: Codable, Equatable, Sendable {
    let id: String
    let title: String
    let author: String?
    /// A display-only reference. Fetching it is the responsibility of the
    /// authenticated cover adapter, never the player or the view.
    let coverReference: String?
}

struct AudioResourceSummary: Codable, Equatable, Sendable, Identifiable {
    let id: String
    let bookID: String
    let title: String
    let sortOrder: Int
    let durationMillis: Int64
    let chapterCount: Int
    let resourceCompleted: Bool
}

struct AudioTrack: Codable, Equatable, Sendable, Identifiable {
    let assetID: String
    let title: String
    let mediaReference: String
    let mimeType: String
    let codec: String?
    let sizeBytes: Int64
    let durationMillis: Int64
    let discNumber: Int?
    let trackNumber: Int?
    let sortOrder: Int

    var id: String { assetID }

    init(
        assetID: String,
        title: String,
        mediaReference: String,
        mimeType: String,
        codec: String? = nil,
        sizeBytes: Int64 = 1,
        durationMillis: Int64,
        discNumber: Int? = nil,
        trackNumber: Int? = nil,
        sortOrder: Int
    ) {
        self.assetID = assetID
        self.title = title
        self.mediaReference = mediaReference
        self.mimeType = mimeType
        self.codec = codec
        self.sizeBytes = max(1, sizeBytes)
        self.durationMillis = max(0, durationMillis)
        self.discNumber = discNumber
        self.trackNumber = trackNumber
        self.sortOrder = sortOrder
    }
}

struct AudioChapter: Codable, Equatable, Sendable, Identifiable {
    let id: String
    let title: String
    let assetID: String
    let startMillis: Int64
    let endMillis: Int64
    let sortOrder: Int

    init(
        id: String,
        title: String,
        assetID: String,
        startMillis: Int64,
        endMillis: Int64,
        sortOrder: Int
    ) {
        self.id = id
        self.title = title
        self.assetID = assetID
        self.startMillis = max(0, startMillis)
        self.endMillis = max(self.startMillis, endMillis)
        self.sortOrder = sortOrder
    }
}

/// The complete, normalized Reader v4 audio projection consumed by the native
/// player. The shared adapter must validate policy version, identity, ordering,
/// bounds, MIME and redirect rules before constructing this value.
struct AudioBootstrap: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let namespace: String
    let userID: String
    let book: AudioBookSummary
    let resource: AudioResourceSummary
    let availableResources: [AudioResourceSummary]
    let tracks: [AudioTrack]
    let chapters: [AudioChapter]
    let totalDurationMillis: Int64
    let resumeLocation: AudioLocation?
    let progressRevision: Int64
    let progressPercent: Double
    let playbackRate: Double
    let skipBackwardSeconds: Int
    let skipForwardSeconds: Int

    init(
        schemaVersion: Int = 4,
        namespace: String,
        userID: String,
        book: AudioBookSummary,
        resource: AudioResourceSummary,
        availableResources: [AudioResourceSummary] = [],
        tracks: [AudioTrack],
        chapters: [AudioChapter] = [],
        totalDurationMillis: Int64? = nil,
        resumeLocation: AudioLocation? = nil,
        progressRevision: Int64 = 0,
        progressPercent: Double = 0,
        playbackRate: Double = 1,
        skipBackwardSeconds: Int = 15,
        skipForwardSeconds: Int = 30
    ) {
        self.schemaVersion = schemaVersion
        self.namespace = namespace
        self.userID = userID
        self.book = book
        self.resource = resource
        self.availableResources = availableResources
        self.tracks = Self.orderedTracks(tracks)
        let trackIDs = Set(self.tracks.map(\.assetID))
        self.chapters = Self.orderedChapters(chapters.filter { trackIDs.contains($0.assetID) })
        let calculatedDuration = self.tracks.reduce(into: Int64(0)) { result, track in
            result = result.addingReportingOverflow(max(0, track.durationMillis)).partialValue
        }
        self.totalDurationMillis = max(totalDurationMillis ?? 0, calculatedDuration)
        self.resumeLocation = resumeLocation
        self.progressRevision = max(0, progressRevision)
        self.progressPercent = min(100, max(0, progressPercent))
        self.playbackRate = Self.normalizedRate(playbackRate)
        self.skipBackwardSeconds = skipBackwardSeconds > 0 ? skipBackwardSeconds : 15
        self.skipForwardSeconds = skipForwardSeconds > 0 ? skipForwardSeconds : 30
    }

    static func orderedTracks(_ tracks: [AudioTrack]) -> [AudioTrack] {
        tracks.sorted {
            $0.sortOrder == $1.sortOrder
                ? $0.assetID.localizedStandardCompare($1.assetID) == .orderedAscending
                : $0.sortOrder < $1.sortOrder
        }
    }

    static func orderedChapters(_ chapters: [AudioChapter]) -> [AudioChapter] {
        chapters.sorted {
            if $0.sortOrder != $1.sortOrder { return $0.sortOrder < $1.sortOrder }
            if $0.startMillis != $1.startMillis { return $0.startMillis < $1.startMillis }
            return $0.id.localizedStandardCompare($1.id) == .orderedAscending
        }
    }

    static func normalizedRate(_ rate: Double) -> Double {
        let supported = AudioPlaybackSnapshot.supportedPlaybackRates
        guard rate.isFinite else { return 1 }
        return supported.min { abs($0 - rate) < abs($1 - rate) } ?? 1
    }
}

enum AudioPlaybackLifecycle: String, Codable, Equatable, Sendable {
    case idle
    case loading
    case ready
    case playing
    case paused
    case buffering
    case ended
    case error
}

enum AudioSyncState: String, Codable, Equatable, Sendable {
    case synced
    case pending
    case failed
}

enum AudioSleepTimerMode: String, Codable, Equatable, Sendable {
    case timer
    case chapter
}

enum AudioRecoverableErrorCode: String, Codable, Equatable, Sendable {
    case networkRetryable = "NETWORK_RETRYABLE"
    case unauthorized = "AUTHENTICATION_REQUIRED"
    case codecUnsupported = "ENGINE_CODEC_UNSUPPORTED"
    case invalidBootstrap = "AUDIO_BOOTSTRAP_INVALID"
    case resourceUnavailable = "AUDIO_RESOURCE_UNAVAILABLE"
    case interrupted = "AUDIO_INTERRUPTED"
    case localArtifactUnavailable = "AUDIO_LOCAL_ARTIFACT_UNAVAILABLE"
    case unknown = "AUDIO_PLAYBACK_FAILED"
}

struct AudioRecoverableError: Codable, Equatable, Sendable {
    let code: AudioRecoverableErrorCode
    let detail: String?

    init(code: AudioRecoverableErrorCode, detail: String? = nil) {
        self.code = code
        self.detail = detail
    }
}

struct AudioPlaybackSnapshot: Codable, Equatable, Sendable {
    static let supportedPlaybackRates: [Double] = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3]

    let lifecycle: AudioPlaybackLifecycle
    let namespace: String?
    let bootstrap: AudioBootstrap?
    let pendingResourceID: String?
    let resourceID: String?
    let bookID: String?
    let trackIndex: Int
    let track: AudioTrack?
    let chapter: AudioChapter?
    let positionMillis: Int64
    let durationMillis: Int64
    let absolutePositionMillis: Int64
    let totalDurationMillis: Int64
    let playbackRate: Double
    let skipBackwardSeconds: Int
    let skipForwardSeconds: Int
    let syncState: AudioSyncState
    let sleepTimerMode: AudioSleepTimerMode?
    let sleepTimerEndsAtEpochMillis: Int64?
    let recoverableError: AudioRecoverableError?

    static func idle(namespace: String? = nil) -> AudioPlaybackSnapshot {
        AudioPlaybackSnapshot(
            lifecycle: .idle,
            namespace: namespace,
            bootstrap: nil,
            pendingResourceID: nil,
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
            syncState: .synced,
            sleepTimerMode: nil,
            sleepTimerEndsAtEpochMillis: nil,
            recoverableError: nil
        )
    }

    var hasSession: Bool { bootstrap != nil && resourceID != nil && lifecycle != .idle }
    var isPlaying: Bool { lifecycle == .playing || lifecycle == .buffering }

    func clearingSleepTimer() -> AudioPlaybackSnapshot {
        AudioPlaybackSnapshot(
            lifecycle: lifecycle,
            namespace: namespace,
            bootstrap: bootstrap,
            pendingResourceID: pendingResourceID,
            resourceID: resourceID,
            bookID: bookID,
            trackIndex: trackIndex,
            track: track,
            chapter: chapter,
            positionMillis: positionMillis,
            durationMillis: durationMillis,
            absolutePositionMillis: absolutePositionMillis,
            totalDurationMillis: totalDurationMillis,
            playbackRate: playbackRate,
            skipBackwardSeconds: skipBackwardSeconds,
            skipForwardSeconds: skipForwardSeconds,
            syncState: syncState,
            sleepTimerMode: nil,
            sleepTimerEndsAtEpochMillis: nil,
            recoverableError: recoverableError
        )
    }

    func replacing(
        lifecycle: AudioPlaybackLifecycle? = nil,
        pendingResourceID: String?? = nil,
        trackIndex: Int? = nil,
        track: AudioTrack?? = nil,
        chapter: AudioChapter?? = nil,
        positionMillis: Int64? = nil,
        durationMillis: Int64? = nil,
        absolutePositionMillis: Int64? = nil,
        playbackRate: Double? = nil,
        syncState: AudioSyncState? = nil,
        sleepTimerMode: AudioSleepTimerMode?? = nil,
        sleepTimerEndsAtEpochMillis: Int64?? = nil,
        recoverableError: AudioRecoverableError?? = nil
    ) -> AudioPlaybackSnapshot {
        AudioPlaybackSnapshot(
            lifecycle: lifecycle ?? self.lifecycle,
            namespace: namespace,
            bootstrap: bootstrap,
            pendingResourceID: pendingResourceID ?? self.pendingResourceID,
            resourceID: resourceID,
            bookID: bookID,
            trackIndex: trackIndex ?? self.trackIndex,
            track: track ?? self.track,
            chapter: chapter ?? self.chapter,
            positionMillis: positionMillis ?? self.positionMillis,
            durationMillis: durationMillis ?? self.durationMillis,
            absolutePositionMillis: absolutePositionMillis ?? self.absolutePositionMillis,
            totalDurationMillis: totalDurationMillis,
            playbackRate: playbackRate ?? self.playbackRate,
            skipBackwardSeconds: skipBackwardSeconds,
            skipForwardSeconds: skipForwardSeconds,
            syncState: syncState ?? self.syncState,
            sleepTimerMode: sleepTimerMode ?? self.sleepTimerMode,
            sleepTimerEndsAtEpochMillis: sleepTimerEndsAtEpochMillis ?? self.sleepTimerEndsAtEpochMillis,
            recoverableError: recoverableError ?? self.recoverableError
        )
    }

    init(
        lifecycle: AudioPlaybackLifecycle,
        namespace: String?,
        bootstrap: AudioBootstrap?,
        pendingResourceID: String?,
        resourceID: String?,
        bookID: String?,
        trackIndex: Int,
        track: AudioTrack?,
        chapter: AudioChapter?,
        positionMillis: Int64,
        durationMillis: Int64,
        absolutePositionMillis: Int64,
        totalDurationMillis: Int64,
        playbackRate: Double,
        skipBackwardSeconds: Int,
        skipForwardSeconds: Int,
        syncState: AudioSyncState,
        sleepTimerMode: AudioSleepTimerMode?,
        sleepTimerEndsAtEpochMillis: Int64?,
        recoverableError: AudioRecoverableError?
    ) {
        self.lifecycle = lifecycle
        self.namespace = namespace
        self.bootstrap = bootstrap
        self.pendingResourceID = pendingResourceID
        self.resourceID = resourceID
        self.bookID = bookID
        self.trackIndex = trackIndex
        self.track = track
        self.chapter = chapter
        self.positionMillis = max(0, positionMillis)
        self.durationMillis = max(0, durationMillis)
        self.absolutePositionMillis = max(0, absolutePositionMillis)
        self.totalDurationMillis = max(0, totalDurationMillis)
        self.playbackRate = AudioBootstrap.normalizedRate(playbackRate)
        self.skipBackwardSeconds = skipBackwardSeconds
        self.skipForwardSeconds = skipForwardSeconds
        self.syncState = syncState
        self.sleepTimerMode = sleepTimerMode
        self.sleepTimerEndsAtEpochMillis = sleepTimerEndsAtEpochMillis
        self.recoverableError = recoverableError
    }
}

enum AudioPlaybackMath {
    static func clamp(_ value: Int64, lower: Int64 = 0, upper: Int64) -> Int64 {
        min(upper, max(lower, value))
    }

    static func trackOffsets(_ tracks: [AudioTrack]) -> [Int64] {
        var elapsed: Int64 = 0
        return tracks.map { track in
            let offset = elapsed
            elapsed = elapsed.addingReportingOverflow(max(0, track.durationMillis)).partialValue
            return offset
        }
    }

    static func absolutePosition(tracks: [AudioTrack], trackIndex: Int, positionMillis: Int64) -> Int64 {
        guard !tracks.isEmpty else { return 0 }
        let index = min(tracks.count - 1, max(0, trackIndex))
        let offsets = trackOffsets(tracks)
        return offsets[index] + clamp(positionMillis, upper: tracks[index].durationMillis)
    }

    static func targetForAbsolutePosition(
        tracks: [AudioTrack],
        absolutePositionMillis: Int64
    ) -> (trackIndex: Int, positionMillis: Int64)? {
        guard !tracks.isEmpty else { return nil }
        let total = tracks.reduce(into: Int64(0)) {
            $0 = $0.addingReportingOverflow(max(0, $1.durationMillis)).partialValue
        }
        let target = clamp(absolutePositionMillis, upper: total)
        let offsets = trackOffsets(tracks)
        for index in stride(from: tracks.count - 1, through: 0, by: -1) where target >= offsets[index] {
            return (index, clamp(target - offsets[index], upper: tracks[index].durationMillis))
        }
        return (0, 0)
    }

    static func chapter(
        in chapters: [AudioChapter],
        assetID: String,
        positionMillis: Int64
    ) -> AudioChapter? {
        let candidates = chapters.filter { $0.assetID == assetID }
        guard !candidates.isEmpty else { return nil }
        return candidates.first(where: {
            positionMillis >= $0.startMillis && positionMillis < $0.endMillis
        }) ?? candidates.last(where: { positionMillis >= $0.startMillis }) ?? candidates.first
    }
}
