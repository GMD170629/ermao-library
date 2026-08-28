import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

@MainActor
struct IosOpenedReadiumPublication {
    let publication: Publication
    private let closePublication: () async -> Void

    init(publication: Publication, close: @escaping () async -> Void) {
        self.publication = publication
        closePublication = close
    }

    func close() async {
        await closePublication()
    }
}

@MainActor
final class IosReadiumRuntime {
    private let assetRetriever: AssetRetriever
    private let publicationOpener: PublicationOpener

    init() {
        let httpClient = DefaultHTTPClient(ephemeral: true)
        let retriever = AssetRetriever(httpClient: httpClient)
        assetRetriever = retriever
        publicationOpener = PublicationOpener(
            parser: DefaultPublicationParser(
                httpClient: httpClient,
                assetRetriever: retriever,
                pdfFactory: DefaultPDFDocumentFactory()
            ),
            contentProtections: [],
            onCreatePublication: secureEpubPublication
        )
    }

    func open(_ managed: IosManagedPublication) async throws -> IosOpenedReadiumPublication {
        switch managed.sourceFormat {
        case .epub:
            return try await openEPUB(managed)
        case .mobi, .azw, .azw3, .prc:
            return try await openMobiFamily(managed)
        case .txt:
            do {
                let publication = try IosTxtPublicationFactory().open(managed)
                return IosOpenedReadiumPublication(publication: publication) { publication.close() }
            } catch IosTxtPublicationError.invalidEncoding {
                throw IosReaderFailure(code: .txtEncodingUnsupported)
            } catch let failure as IosReaderFailure {
                throw failure
            } catch {
                let code: IosReaderFailureCode = (error as NSError).kotlinException is ErmaoShared.TxtPublicationEmptyException
                    ? .txtEmpty : .parseFailed
                throw IosReaderFailure(code: code, underlyingError: error as NSError)
            }
        case .fb2:
            do {
                let publication = try IosFb2PublicationFactory().open(managed)
                return IosOpenedReadiumPublication(publication: publication) { publication.close() }
            } catch IosFb2PublicationError.limitExceeded {
                throw IosReaderFailure(code: .outOfMemoryRisk)
            } catch let failure as IosReaderFailure {
                throw failure
            } catch {
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            }
        case .pdf:
            return try await openPDF(managed)
        default:
            throw IosReaderFailure(code: .unsupportedFormat)
        }
    }

    private func openPDF(_ managed: IosManagedPublication) async throws -> IosOpenedReadiumPublication {
        guard let fileURL = FileURL(url: managed.fileURL) else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        let asset: ReadiumShared.Asset
        switch await assetRetriever.retrieve(url: fileURL) {
        case let .success(value): asset = value
        case let .failure(error): throw IosReaderFailure(code: .engineError, underlyingError: error as NSError)
        }
        let publication: Publication
        switch await publicationOpener.open(asset: asset, allowUserInteraction: false) {
        case let .success(value): publication = value
        case let .failure(error):
            switch error {
            case .formatNotSupported:
                throw IosReaderFailure(code: .unsupportedFormat)
            case .reading:
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            }
        }
        guard publication.conforms(to: .pdf) else {
            publication.close()
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        guard !publication.isRestricted else {
            publication.close()
            throw IosReaderFailure(code: .drmProtected)
        }
        return IosOpenedReadiumPublication(publication: publication) { publication.close() }
    }

    private func openEPUB(_ managed: IosManagedPublication) async throws -> IosOpenedReadiumPublication {
        guard let fileURL = FileURL(url: managed.fileURL) else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        let asset: ReadiumShared.Asset
        switch await assetRetriever.retrieve(url: fileURL) {
        case let .success(value): asset = value
        case let .failure(error): throw IosReaderFailure(code: .engineError, underlyingError: error as NSError)
        }
        let publication: Publication
        switch await publicationOpener.open(asset: asset, allowUserInteraction: false) {
        case let .success(value): publication = value
        case let .failure(error): throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
        }
        guard publication.conforms(to: .epub) else {
            publication.close()
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        guard !publication.isRestricted else {
            publication.close()
            throw IosReaderFailure(code: .drmProtected)
        }
        return IosOpenedReadiumPublication(publication: publication) {
            publication.close()
        }
    }

    private func openMobiFamily(
        _ managed: IosManagedPublication
    ) async throws -> IosOpenedReadiumPublication {
        do {
            let result = try await IosMobiPublicationFactory().open(
                fileURL: managed.fileURL,
                resourceID: managed.resourceID,
                displayTitle: managed.displayTitle
            )
            return IosOpenedReadiumPublication(publication: result.publication) {
                await result.close()
            }
        } catch let error as IosMobiCoreError {
            throw IosReaderFailure(code: Self.failureCode(error.status), underlyingError: error as NSError)
        } catch let error as IosMobiPublicationError {
            switch error {
            case .closed, .invalidResourceIndex, .invalidResourcePath,
                 .duplicateResourcePath, .invalidTableOfContents, .invalidTextEncoding:
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            case .invalidSourceIdentity:
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            case .missingReadingOrder, .unsupportedMediaType:
                throw IosReaderFailure(code: .unsupportedFormat)
            }
        }
    }

    private static func failureCode(_ status: IosMobiCoreStatus) -> IosReaderFailureCode {
        switch status {
        case .drmProtected:
            .drmProtected
        case .unsupported:
            .unsupportedFormat
        case .limitExceeded, .outOfMemory:
            .outOfMemoryRisk
        case .fileNotFound, .notFound:
            .resourceMissing
        case .io:
            .engineError
        case .corrupt, .parseFailed, .noContent:
            .parseFailed
        case .invalidArgument, .outOfRange,
             .bufferTooSmall, .internalFailure:
            .engineError
        }
    }

}

// Readium resolves container resources on background executors. Keeping this transform
// outside the @MainActor runtime prevents its resource mapper from inheriting main-actor isolation.
private func secureEpubPublication(
    _: inout Manifest,
    container: inout Container,
    _: inout PublicationServicesBuilder
) async {
    container = container.map { href, resource in
        guard IosPublicationSecurityPolicy.isMarkup(href.string) else { return resource }
        return TransformingResource(resource) { result in
            result.flatMap { data in
                do {
                    return .success(try IosPublicationSecurityPolicy.decorate(data: data))
                } catch {
                    return .failure(.decoding("Unsafe or invalid EPUB resource", cause: error))
                }
            }
        }
    }
}
