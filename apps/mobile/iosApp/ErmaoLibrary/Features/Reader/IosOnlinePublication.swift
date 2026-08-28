import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

/** Only bridges shared resource access to native Readium; it owns no download or cache policy. */
struct IosOnlinePublicationFactory {
    let session: ErmaoShared.OnlinePublicationSession
    let onFailure: @MainActor @Sendable (IosReaderFailure) -> Void

    func open() async throws -> Publication {
        let metadata: ErmaoShared.OnlinePublicationMetadata
        do { metadata = try await session.open() }
        catch {
            if let failure = (error as NSError).kotlinException as? ErmaoShared.OnlinePublicationFailure {
                throw iosOnlineReaderFailure(
                    code: failure.code, errorCode: failure.errorCode,
                    stage: failure.stage, cause: error
                )
            }
            throw error
        }
        let manifest: Manifest
        do {
            manifest = try Manifest(jsonString: metadata.manifestJson)
        } catch {
            let failure = try ErmaoShared.OnlinePublicationFailure.companion.invalidMetadata(stage: .manifest, cause: nil)
            throw iosOnlineReaderFailure(
                code: failure.code, errorCode: failure.errorCode,
                stage: failure.stage, cause: error
            )
        }
        let positions: [Locator]
        do {
            let payload = try JSONValue(jsonString: metadata.positionsJson)
            guard let items = payload.object?["positions"]?.array else {
                throw IosReaderFailure(code: .invalidResponse)
            }
            positions = try items.map { item in
                guard let locator = try Locator(json: item, warnings: nil) else {
                    throw IosReaderFailure(code: .invalidResponse)
                }
                return locator
            }
        } catch {
            let failure = try ErmaoShared.OnlinePublicationFailure.companion.invalidMetadata(stage: .positions, cause: nil)
            throw iosOnlineReaderFailure(
                code: failure.code, errorCode: failure.errorCode,
                stage: failure.stage, cause: error
            )
        }
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
                search: ContentSearchService.makeFactory()
            )
        )
    }
}

private final class IosOnlinePublicationContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let session: ErmaoShared.OnlinePublicationSession
    private let onFailure: @MainActor @Sendable (IosReaderFailure) -> Void

    init(session: ErmaoShared.OnlinePublicationSession, metadata: ErmaoShared.OnlinePublicationMetadata,
         onFailure: @escaping @MainActor @Sendable (IosReaderFailure) -> Void) throws {
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
        return TransformingResource(resource) { [onFailure] result in
            switch result {
            case let .failure(error): return .failure(error)
            case let .success(bytes):
                do { return .success(try IosPublicationSecurityPolicy.decorate(data: bytes)) }
                catch {
                    let failure = IosReaderFailure(
                        code: .securityRejected,
                        onlineContext: IosReaderOnlineFailureContext(sourceCode: "PUBLICATION_SECURITY_REJECTED", stage: .chapter),
                        underlyingError: error as NSError
                    )
                    await onFailure(failure)
                    return .failure(.decoding(failure.code.rawValue, cause: error))
                }
            }
        }
    }

    func close() { session.close() }
}

private final class IosOnlinePublicationResource: ReadiumShared.Resource, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    private let session: ErmaoShared.OnlinePublicationSession
    private let onFailure: @MainActor @Sendable (IosReaderFailure) -> Void
    private let href: String

    init(session: ErmaoShared.OnlinePublicationSession, href: String,
         onFailure: @escaping @MainActor @Sendable (IosReaderFailure) -> Void) {
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
                let nativeFailure = iosOnlineReaderFailure(
                    code: failure?.code ?? "PUBLICATION_RESPONSE_INVALID",
                    errorCode: failure?.errorCode ?? .invalidresponse,
                    stage: failure?.stage
                )
                await onFailure(nativeFailure)
                return .failure(.decoding(nativeFailure.code.rawValue))
            }
            let bytes = content.bytes.foundationData()
            let lower = Int(min(range?.lowerBound ?? 0, UInt64(bytes.count)))
            let upper = Int(min(range?.upperBound ?? UInt64(bytes.count), UInt64(bytes.count)))
            if lower < upper { consume(bytes[lower ..< upper]) }
            return .success(())
        } catch {
            if let failure = (error as NSError).kotlinException as? ErmaoShared.OnlinePublicationFailure {
                let nativeFailure = iosOnlineReaderFailure(
                    code: failure.code, errorCode: failure.errorCode,
                    stage: failure.stage, cause: error
                )
                await onFailure(nativeFailure)
                return .failure(.decoding(nativeFailure.code.rawValue, cause: error))
            }
            return .failure(.decoding("Publication read failed", cause: error))
        }
    }
}

private func iosOnlineReaderFailure(
    code: String,
    errorCode: ErmaoShared.ReaderErrorCode,
    stage: ErmaoShared.OnlinePublicationStage?,
    cause: (any Error)? = nil
) -> IosReaderFailure {
    IosReaderFailure(
        code: IosReaderFailureCode(sharedCode: errorCode),
        onlineContext: IosReaderOnlineFailureContext(sourceCode: code, stage: stage),
        underlyingError: cause.map { $0 as NSError }
    )
}
