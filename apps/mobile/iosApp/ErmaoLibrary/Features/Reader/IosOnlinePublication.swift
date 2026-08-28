import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

/** Only bridges shared resource access to native Readium; it owns no download or cache policy. */
struct IosOnlinePublicationFactory {
    let session: ErmaoShared.OnlinePublicationSession
    let onFailure: @MainActor @Sendable (String) -> Void

    func open() async throws -> Publication {
        let metadata = try await session.open()
        let manifest = try Manifest(json: JSONSerialization.jsonObject(with: Data(metadata.manifestJson.utf8)))
        guard let payload = try JSONSerialization.jsonObject(with: Data(metadata.positionsJson.utf8)) as? [String: Any],
              let items = payload["positions"] as? [[String: Any]] else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let positions = try items.map { try Locator(json: $0) }
        let container = try IosOnlinePublicationContainer(session: session, metadata: metadata, onFailure: onFailure)
        return Publication(
            manifest: manifest,
            container: container,
            servicesBuilder: PublicationServicesBuilder(
                content: DefaultContentService.makeFactory(
                    resourceContentIteratorFactories: [HTMLResourceContentIterator.Factory()]
                ),
                positions: InMemoryPositionsService.makeFactory(
                    positionsByReadingOrder: manifest.readingOrder.map { link in
                        positions.filter { $0.href.string == link.href }
                    }
                ),
                search: StringSearchService.makeFactory()
            )
        )
    }
}

private final class IosOnlinePublicationContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let session: ErmaoShared.OnlinePublicationSession
    private let onFailure: @MainActor @Sendable (String) -> Void

    init(session: ErmaoShared.OnlinePublicationSession, metadata: ErmaoShared.OnlinePublicationMetadata,
         onFailure: @escaping @MainActor @Sendable (String) -> Void) throws {
        self.session = session
        self.onFailure = onFailure
        entries = try Set((metadata.readingOrder + metadata.resources).map {
            guard let url = AnyURL(string: $0.href) else { throw IosReaderFailure(code: .corruptFile) }
            return url
        })
    }

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
        let href = url.anyURL.removingQuery().removingFragment()
        guard entries.contains(href) else { return nil }
        let resource = IosOnlinePublicationResource(session: session, href: href.string, onFailure: onFailure)
        guard IosPublicationSecurityPolicy.isMarkup(href.string) else { return resource }
        return TransformingResource(resource) { result in
            result.flatMap { bytes in
                do { return .success(try IosPublicationSecurityPolicy.decorate(data: bytes)) }
                catch { return .failure(.decoding("Invalid publication markup", cause: error)) }
            }
        }
    }

    func close() { session.close() }
}

private final class IosOnlinePublicationResource: ReadiumShared.Resource, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    private let session: ErmaoShared.OnlinePublicationSession
    private let onFailure: @MainActor @Sendable (String) -> Void
    private let href: String

    init(session: ErmaoShared.OnlinePublicationSession, href: String,
         onFailure: @escaping @MainActor @Sendable (String) -> Void) {
        self.session = session
        self.onFailure = onFailure
        self.href = href
    }

    func estimatedLength() async -> ReadResult<UInt64?> { .success(nil) }
    func properties() async -> ReadResult<ResourceProperties> { .success(ResourceProperties()) }

    func stream(range: Range<UInt64>?, consume: @escaping (Data) -> Void) async -> ReadResult<Void> {
        do {
            let result = try await session.read(href: href)
            guard let content = result as? ErmaoShared.OnlinePublicationReadResultContent else {
                let failure = result as? ErmaoShared.OnlinePublicationReadResultFailure
                let code = failure?.errorCode.wireValue ?? "READER_ENGINE_ERROR"
                await onFailure(code)
                return .failure(.decoding(code))
            }
            let bytes = content.bytes.foundationData()
            let lower = Int(min(range?.lowerBound ?? 0, UInt64(bytes.count)))
            let upper = Int(min(range?.upperBound ?? UInt64(bytes.count), UInt64(bytes.count)))
            if lower < upper { consume(bytes[lower ..< upper]) }
            return .success(())
        } catch {
            return .failure(.decoding("Publication read failed", cause: error))
        }
    }
}
