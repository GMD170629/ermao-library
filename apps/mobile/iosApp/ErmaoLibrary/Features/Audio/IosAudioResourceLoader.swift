@preconcurrency import AVFoundation
import Foundation

/// Bridges AVAssetResourceLoader's pull-style requests to the shared
/// authenticated incremental media stream. No URLSession, cookie, TLS or
/// redirect behavior is implemented here.
@MainActor
final class IosAudioResourceLoader: NSObject, @preconcurrency AVAssetResourceLoaderDelegate {
    private let adapter: any AudioMediaStreamAdapter
    private let request: AudioMediaStreamRequest
    private var activeTasks: [ObjectIdentifier: Task<Void, Never>] = [:]
    // AVFoundation requires delegates to retain accepted loading requests until async completion.
    private var activeRequests: [ObjectIdentifier: AVAssetResourceLoadingRequest] = [:]
    private var activeStreams: [ObjectIdentifier: any AudioMediaStream] = [:]

    init(adapter: any AudioMediaStreamAdapter, request: AudioMediaStreamRequest) {
        self.adapter = adapter
        self.request = request
        super.init()
    }

    static func url(assetID: String, mimeType: String, sourceID: Int64) -> URL {
        var components = URLComponents()
        components.scheme = "ermao-audio"
        components.host = "asset"
        let filenameExtension = IosAudioMediaType.preferredFilenameExtension(for: mimeType)
        let filename = filenameExtension.map {
            "\(Self.escapedComponent(assetID)).\($0)"
        } ?? Self.escapedComponent(assetID)
        components.path = "/\(sourceID)/\(filename)"
        return components.url ?? URL(string: "ermao-audio://asset/audio")!
    }

    func resourceLoader(
        _ resourceLoader: AVAssetResourceLoader,
        shouldWaitForLoadingOfRequestedResource loadingRequest: AVAssetResourceLoadingRequest
    ) -> Bool {
        let key = ObjectIdentifier(loadingRequest)
        activeTasks[key]?.cancel()
        activeRequests[key] = loadingRequest
        activeTasks[key] = Task { @MainActor [weak self] in
            guard let self, let loadingRequest = self.activeRequests[key] else { return }
            await self.serve(loadingRequest, key: key)
        }
        return true
    }

    func resourceLoader(
        _ resourceLoader: AVAssetResourceLoader,
        didCancel loadingRequest: AVAssetResourceLoadingRequest
    ) {
        cancel(loadingRequest)
    }

    func cancelAllRequests() {
        activeTasks.values.forEach { $0.cancel() }
        activeTasks.removeAll()
        activeRequests.removeAll()
        activeStreams.values.forEach { $0.cancel() }
        activeStreams.removeAll()
    }

    deinit {
        activeTasks.values.forEach { $0.cancel() }
    }

    private func serve(_ loadingRequest: AVAssetResourceLoadingRequest, key: ObjectIdentifier) async {
        defer {
            activeTasks[key] = nil
            activeRequests[key] = nil
            activeStreams[key]?.cancel()
            activeStreams[key] = nil
        }
        do {
            let range = requestedRange(loadingRequest.dataRequest)
            let streamRequest = AudioMediaStreamRequest(
                namespace: request.namespace,
                resourceID: request.resourceID,
                assetID: request.assetID,
                mediaReference: request.mediaReference,
                mimeType: request.mimeType,
                sizeBytes: request.sizeBytes,
                durationMillis: request.durationMillis,
                codec: request.codec,
                byteRange: range
            )
            // Probe (HEAD) and open (GET/Range) are both delegated to the
            // shared transport. The loader never creates a URLSession or
            // copies authentication/TLS policy.
            let probe = try await adapter.probe(streamRequest)
            let stream = try await adapter.open(streamRequest)
            activeStreams[key] = stream
            guard !loadingRequest.isCancelled else {
                stream.cancel()
                return
            }
            fillContentInformation(
                loadingRequest.contentInformationRequest,
                probe: probe,
                from: stream
            )
            if let responseURL = loadingRequest.request.url {
                loadingRequest.response = URLResponse(
                    url: responseURL,
                    mimeType: request.mimeType,
                    expectedContentLength: Int(request.sizeBytes),
                    textEncodingName: nil
                )
            }
            guard let dataRequest = loadingRequest.dataRequest else {
                loadingRequest.finishLoading(with: AudioAdapterError.invalidResponse)
                return
            }
            while !Task.isCancelled && !loadingRequest.isCancelled {
                guard !Task.isCancelled, !loadingRequest.isCancelled else {
                    stream.cancel()
                    return
                }
                let chunk = try await stream.read(maximumBytes: 64 * 1024)
                if chunk.isEmpty { break }
                if !chunk.isEmpty { dataRequest.respond(with: chunk) }
            }
            guard !loadingRequest.isCancelled else { return }
            loadingRequest.finishLoading()
        } catch is CancellationError {
            return
        } catch {
            guard !loadingRequest.isCancelled else { return }
            loadingRequest.finishLoading(with: error)
        }
    }

    private func cancel(_ loadingRequest: AVAssetResourceLoadingRequest) {
        let key = ObjectIdentifier(loadingRequest)
        activeTasks[key]?.cancel()
        activeTasks[key] = nil
        activeRequests[key] = nil
        activeStreams[key]?.cancel()
        activeStreams[key] = nil
    }

    private func requestedRange(_ dataRequest: AVAssetResourceLoadingDataRequest?) -> AudioMediaByteRange? {
        guard let dataRequest else { return nil }
        return Self.requestedRange(
            offset: dataRequest.requestedOffset,
            length: dataRequest.requestedLength,
            requestsAllDataToEnd: dataRequest.requestsAllDataToEndOfResource,
            assetSize: request.sizeBytes
        )
    }

    static func requestedRange(
        offset: Int64,
        length: Int,
        requestsAllDataToEnd: Bool,
        assetSize: Int64
    ) -> AudioMediaByteRange {
        let start = max(0, offset)
        guard !requestsAllDataToEnd, length > 0 else {
            return AudioMediaByteRange(start: start)
        }
        let requestedEnd = start.addingReportingOverflow(Int64(length))
        let end = requestedEnd.overflow ? assetSize : min(assetSize, requestedEnd.partialValue)
        return AudioMediaByteRange(start: start, end: end)
    }

    private func fillContentInformation(
        _ information: AVAssetResourceLoadingContentInformationRequest?,
        probe: AudioMediaProbe,
        from stream: any AudioMediaStream
    ) {
        guard let information else { return }
        information.contentType = probe.uniformTypeIdentifier
        information.contentLength = probe.contentLength ?? stream.contentLength ?? 0
        information.isByteRangeAccessSupported = probe.supportsByteRanges && stream.supportsByteRanges
        information.isEntireLengthAvailableOnDemand = information.isByteRangeAccessSupported
    }

    private static func escapedComponent(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? "asset"
    }
}
