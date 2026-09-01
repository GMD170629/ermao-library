import Foundation
import UniformTypeIdentifiers
@preconcurrency import ErmaoShared

enum AudioAdapterError: Error, Equatable, Sendable {
    case unavailable
    case unauthorized
    case retryableNetwork
    case invalidResponse
    case codecUnsupported
    case resourceUnavailable
    case cancelled

    var errorCode: AudioRecoverableErrorCode {
        switch self {
        case .unavailable, .invalidResponse: .invalidBootstrap
        case .unauthorized: .unauthorized
        case .retryableNetwork, .cancelled: .networkRetryable
        case .codecUnsupported: .codecUnsupported
        case .resourceUnavailable: .resourceUnavailable
        }
    }
}

/// A bounded byte range requested by AVAssetResourceLoader. `end` is exclusive.
struct AudioMediaByteRange: Equatable, Sendable {
    let start: Int64
    let end: Int64?

    init(start: Int64, end: Int64? = nil) {
        let normalizedStart = max(0, start)
        self.start = normalizedStart
        self.end = end.map { max(normalizedStart, $0) }
    }
}

struct AudioMediaStreamRequest: Equatable, Sendable {
    let namespace: String
    let resourceID: String
    let assetID: String
    let mediaReference: String
    let mimeType: String
    let sizeBytes: Int64
    let durationMillis: Int64?
    let codec: String?
    let byteRange: AudioMediaByteRange?
}

struct AudioMediaProbe: Equatable, Sendable {
    let uniformTypeIdentifier: String
    let contentLength: Int64?
    let supportsByteRanges: Bool
}

struct AudioBootstrapEnvelope {
    let presentation: AudioBootstrap
    let publication: ErmaoShared.AudioPublication
    let readerBootstrap: ErmaoShared.ReaderBootstrap
}

enum IosAudioProgressSaveReason: Sendable {
    case tick
    case seek
    case pause
    case chapterChange
    case trackChange
    case stop
    case background
    case completed
}

/// The shared/KMP media owner supplies an incremental stream. It owns Cookie
/// vault access, TLS profile, base-path resolution, redirect policy and HTTP
/// status validation. The iOS engine only consumes bounded chunks.
@MainActor
protocol AudioMediaStream: AnyObject {
    var uniformTypeIdentifier: String { get }
    var contentLength: Int64? { get }
    var rangeStart: Int64 { get }
    var supportsByteRanges: Bool { get }
    func read(maximumBytes: Int) async throws -> Data
    func cancel()
}

@MainActor
protocol AudioMediaStreamAdapter: AnyObject {
    func probe(_ request: AudioMediaStreamRequest) async throws -> AudioMediaProbe
    func open(_ request: AudioMediaStreamRequest) async throws -> any AudioMediaStream
}

@MainActor
protocol AudioBootstrapGateway: AnyObject {
    func loadAudioBootstrap(resourceID: String, namespace: String) async throws -> AudioBootstrapEnvelope
}

enum AudioProgressSaveResult: Equatable, Sendable {
    case synced
    case pending
    case failed
}

/// The shared progress outbox is the authoritative implementation. Native UI
/// never talks to the server directly; this port only carries the normalized
/// audio location and ordering hints.
@MainActor
protocol AudioProgressAdapter: AnyObject {
    func loadLocation(namespace: String, resourceID: String) async throws -> AudioLocation?
    func saveLocation(
    _ location: AudioLocation,
        namespace: String,
        completed: Bool,
        reason: IosAudioProgressSaveReason
    ) async throws -> AudioProgressSaveResult
    func flush(namespace: String) async
}

@MainActor
protocol AudioSessionConfiguring: AnyObject {
    func configure(session: IosAudioSessionContext?)
}

@MainActor
protocol AudioProgressSessionConfiguring: AnyObject {
    func configure(bootstrap: AudioBootstrapEnvelope) async
}

@MainActor
protocol AudioLocalProgressSessionConfiguring: AnyObject {
    func configureLocal(bookID: String, resourceID: String) async
}

@MainActor
protocol AudioCoverAdapter: AnyObject {
    /// Returns a locally cached image only. Network retrieval stays in the
    /// shared authenticated cover adapter.
    func cachedArtwork(for reference: String?, namespace: String) -> Data?
}

@MainActor
final class EmptyAudioCoverAdapter: AudioCoverAdapter {
    func cachedArtwork(for reference: String?, namespace: String) -> Data? { nil }
}

/// Native AVFoundation code consumes this adapter only. The KMP transport
/// remains the sole owner of authenticated requests, Cookie vault access, TLS,
/// base paths, redirect policy and Reader Safety admission.
@MainActor
final class KmpAudioMediaStreamAdapter: AudioMediaStreamAdapter {
    private let transport: any ErmaoShared.AudioMediaTransport

    init(transport: any ErmaoShared.AudioMediaTransport) {
        self.transport = transport
    }

    func probe(_ request: AudioMediaStreamRequest) async throws -> AudioMediaProbe {
        let asset = makeAsset(from: request)
        let result = try await transport.probe(asset: asset)
        guard let available = result as? ErmaoShared.AudioMediaProbeResultAvailable else {
            if let failure = result as? ErmaoShared.AudioMediaProbeResultFailure {
                throw failure.error.asAudioAdapterError
            }
            throw AudioAdapterError.invalidResponse
        }
        return AudioMediaProbe(
            uniformTypeIdentifier: UTType(mimeType: available.metadata.mimeType)?.identifier
                ?? available.metadata.mimeType,
            contentLength: available.metadata.totalLength?.int64Value
                ?? available.metadata.contentLength?.int64Value,
            supportsByteRanges: available.metadata.acceptsByteRanges
        )
    }

    func open(_ request: AudioMediaStreamRequest) async throws -> any AudioMediaStream {
        let asset = makeAsset(from: request)
        let byteRange = request.byteRange
        let rangeStart = byteRange?.start ?? 0
        let rangeEndInclusive = byteRange?.end
            .flatMap { $0 > rangeStart ? KotlinLong(longLong: $0 - 1) : nil }
        let result = try await transport.open(
            asset: asset,
            rangeStart: rangeStart,
            rangeEndInclusive: rangeEndInclusive
        )
        guard let content = result as? ErmaoShared.AudioMediaOpenResultContent else {
            if let failure = result as? ErmaoShared.AudioMediaOpenResultFailure {
                throw failure.error.asAudioAdapterError
            }
            throw AudioAdapterError.invalidResponse
        }
        return KmpAudioMediaStream(
            stream: content.stream,
            requestedStart: rangeStart
        )
    }

    private func makeAsset(from request: AudioMediaStreamRequest) -> ErmaoShared.AudioAsset {
        ErmaoShared.AudioAsset(
            assetId: request.assetID,
            resourceId: request.resourceID,
            title: request.assetID,
            apiPath: request.mediaReference,
            mimeType: request.mimeType,
            sizeBytes: request.sizeBytes,
            durationMillis: request.durationMillis.map { KotlinLong(longLong: $0) },
            discNumber: nil,
            trackNumber: nil,
            sortOrder: 0,
            codec: request.codec
        )
    }
}

@MainActor
private final class KmpAudioMediaStream: AudioMediaStream {
    private let stream: any ErmaoShared.AudioMediaStream
    private(set) var rangeStart: Int64
    private var isClosed = false

    init(stream: any ErmaoShared.AudioMediaStream, requestedStart: Int64) {
        self.stream = stream
        rangeStart = requestedStart
    }

    var uniformTypeIdentifier: String {
        UTType(mimeType: stream.metadata.mimeType)?.identifier ?? stream.metadata.mimeType
    }

    var contentLength: Int64? { stream.metadata.contentLength?.int64Value }
    var supportsByteRanges: Bool { stream.metadata.acceptsByteRanges }

    func read(maximumBytes: Int) async throws -> Data {
        guard !isClosed else { return Data() }
        let bytes = try await stream.read(maximumBytes: Int32(maximumBytes))
        return bytes.foundationData()
    }

    func cancel() {
        guard !isClosed else { return }
        isClosed = true
        stream.close()
    }
}

private extension ErmaoShared.AudioMediaFailure {
    var asAudioAdapterError: AudioAdapterError {
        switch code {
        case "AUTHENTICATION_REQUIRED", "UNAUTHORIZED", "HTTP_401": .unauthorized
        case "ENGINE_CODEC_UNSUPPORTED": .codecUnsupported
        case "AUDIO_RESOURCE_UNAVAILABLE": .resourceUnavailable
        case "AUDIO_REQUEST_CANCELLED": .cancelled
        default: recoverable ? .retryableNetwork : .invalidResponse
        }
    }
}
