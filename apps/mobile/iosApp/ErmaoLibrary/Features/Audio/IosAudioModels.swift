import Foundation
@preconcurrency import ErmaoShared

/// Platform launch input. It is mapped directly to the shared command at the Runtime boundary.
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
}

struct AudioBookSummary: Codable, Equatable, Sendable {
    let id: String
    let title: String
    let author: String?
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
        self.sizeBytes = sizeBytes
        self.durationMillis = durationMillis
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
}

/// SwiftUI projection only. Ordering, selection, duration, rate and restore rules remain in KMP.
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
        totalDurationMillis: Int64 = 0,
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
        self.tracks = tracks
        self.chapters = chapters
        self.totalDurationMillis = totalDurationMillis
        self.resumeLocation = resumeLocation
        self.progressRevision = progressRevision
        self.progressPercent = progressPercent
        self.playbackRate = playbackRate
        self.skipBackwardSeconds = skipBackwardSeconds
        self.skipForwardSeconds = skipForwardSeconds
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
    case track
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
    let recoverable: Bool
    let detail: String?
}

struct AudioPlaybackSnapshot: Codable, Equatable, Sendable {
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
    let supportedPlaybackRates: [Double]
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
            supportedPlaybackRates: [],
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
}

extension AudioPlaybackSnapshot {
    init(
        shared: ErmaoShared.AudioPlaybackSnapshot,
        mediaReference: (ErmaoShared.AudioAsset) -> String
    ) {
        let publication = shared.publication
        let tracks: [AudioTrack]
        let chapters: [AudioChapter]
        let resources: [AudioResourceSummary]
        if let publication {
            tracks = publication.assets.map { asset in
                AudioTrack(
                    assetID: asset.assetId,
                    title: asset.title,
                    mediaReference: mediaReference(asset),
                    mimeType: asset.mimeType,
                    codec: asset.codec,
                    sizeBytes: asset.sizeBytes,
                    durationMillis: asset.durationMillis?.int64Value ?? 0,
                    discNumber: asset.discNumber?.intValue,
                    trackNumber: asset.trackNumber?.intValue,
                    sortOrder: Int(asset.sortOrder)
                )
            }
            chapters = publication.chapters.map { chapter in
                let duration = tracks.first(where: { $0.assetID == chapter.assetId })?.durationMillis ?? 0
                return AudioChapter(
                    id: chapter.chapterId,
                    title: chapter.title,
                    assetID: chapter.assetId,
                    startMillis: chapter.startMillis,
                    endMillis: chapter.endMillis?.int64Value ?? duration,
                    sortOrder: Int(chapter.index)
                )
            }
            resources = publication.availableResources.map { resource in
                AudioResourceSummary(
                    id: resource.resourceId,
                    bookID: publication.bookId,
                    title: resource.title,
                    sortOrder: Int(resource.sortOrder),
                    durationMillis: resource.durationMillis?.int64Value ?? 0,
                    chapterCount: resource.chapterCount?.intValue ?? 0,
                    resourceCompleted: false
                )
            }
        } else {
            tracks = []
            chapters = []
            resources = []
        }
        let resource = publication.map {
            AudioResourceSummary(
                id: $0.resource.resourceId,
                bookID: $0.bookId,
                title: $0.resource.title,
                sortOrder: Int($0.resource.sortOrder),
                durationMillis: $0.resource.durationMillis?.int64Value ?? 0,
                chapterCount: $0.resource.chapterCount?.intValue ?? 0,
                resourceCompleted: false
            )
        }
        let bootstrap: AudioBootstrap? = if let publication, let resource {
            AudioBootstrap(
                namespace: shared.namespaceKey ?? publication.namespace_.stableKey,
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
                totalDurationMillis: shared.totalDurationMillis,
                playbackRate: shared.playbackRate,
                skipBackwardSeconds: Int(shared.skipBackwardSeconds),
                skipForwardSeconds: Int(shared.skipForwardSeconds)
            )
        } else {
            nil
        }
        let trackIndex = Int(shared.currentAssetIndex)
        self.init(
            lifecycle: shared.isPreparing || shared.isSeeking ? .loading : Self.lifecycle(shared.stage),
            namespace: shared.namespaceKey,
            bootstrap: bootstrap,
            pendingResourceID: shared.pendingResourceId,
            resourceID: publication?.resource.resourceId,
            bookID: publication?.bookId,
            trackIndex: trackIndex,
            track: tracks.indices.contains(trackIndex) ? tracks[trackIndex] : nil,
            chapter: chapters.first(where: { $0.id == shared.currentChapterId }),
            positionMillis: shared.positionMillis,
            durationMillis: shared.durationMillis?.int64Value ?? 0,
            absolutePositionMillis: shared.displayedAbsolutePositionMillis,
            totalDurationMillis: shared.totalDurationMillis,
            playbackRate: shared.playbackRate,
            supportedPlaybackRates: shared.supportedPlaybackRates.map(\.doubleValue),
            skipBackwardSeconds: Int(shared.skipBackwardSeconds),
            skipForwardSeconds: Int(shared.skipForwardSeconds),
            syncState: Self.syncState(shared.syncState),
            sleepTimerMode: Self.sleepMode(shared.sleepTimerMode),
            sleepTimerEndsAtEpochMillis: shared.sleepTimerEndsAtEpochMillis?.int64Value,
            recoverableError: shared.error.map {
                AudioRecoverableError(
                    code: AudioRecoverableErrorCode(rawValue: $0.code) ?? .unknown,
                    recoverable: $0.recoverable,
                    detail: $0.code
                )
            }
        )
    }

    private static func lifecycle(_ stage: ErmaoShared.AudioPlaybackStage) -> AudioPlaybackLifecycle {
        switch stage {
        case .idle: .idle
        case .preparing: .loading
        case .ready: .ready
        case .playing: .playing
        case .paused: .paused
        case .buffering: .buffering
        case .ended: .ended
        case .error: .error
        default: .error
        }
    }

    private static func syncState(_ state: ErmaoShared.AudioProgressSyncState) -> AudioSyncState {
        switch state {
        case .synced: .synced
        case .pending: .pending
        case .failed: .failed
        default: .failed
        }
    }

    private static func sleepMode(_ mode: ErmaoShared.AudioSleepTimerMode) -> AudioSleepTimerMode? {
        switch mode {
        case .off: nil
        case .minutes15, .minutes30, .minutes45, .minutes60: .timer
        case .endofchapter: .chapter
        case .endoftrack: .track
        default: nil
        }
    }
}
