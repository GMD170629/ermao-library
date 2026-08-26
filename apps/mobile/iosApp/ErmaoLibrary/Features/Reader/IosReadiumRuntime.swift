import Foundation
import PDFKit
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
            let publication = try IosTxtPublicationFactory().open(managed)
            return IosOpenedReadiumPublication(publication: publication) { publication.close() }
        case .fb2:
            let publication = try IosFb2PublicationFactory().open(managed)
            return IosOpenedReadiumPublication(publication: publication) { publication.close() }
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
        let preflight = await Task.detached(priority: .userInitiated) {
            guard let document = PDFKit.PDFDocument(url: managed.fileURL) else { return PdfPreflight.invalid }
            if document.isLocked || document.isEncrypted { return PdfPreflight.protected }
            return document.pageCount > 0 ? .readable : .invalid
        }.value
        switch preflight {
        case .readable: break
        case .protected: throw IosReaderFailure(code: .drmProtected)
        case .invalid: throw IosReaderFailure(code: .corruptFile)
        }
        let asset: Asset
        switch await assetRetriever.retrieve(url: fileURL) {
        case let .success(value): asset = value
        case .failure: throw IosReaderFailure(code: .resourceMissing)
        }
        let publication: Publication
        switch await publicationOpener.open(asset: asset, allowUserInteraction: false) {
        case let .success(value): publication = value
        case let .failure(error):
            switch error {
            case .formatNotSupported:
                throw IosReaderFailure(code: .unsupportedFormat)
            case .reading:
                // Readium deliberately does not prompt for PDF passwords. Encrypted,
                // malformed and unreadable documents all stay behind a stable app error.
                throw IosReaderFailure(code: .corruptFile)
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

    private enum PdfPreflight: Sendable {
        case readable
        case protected
        case invalid
    }

    private func openEPUB(_ managed: IosManagedPublication) async throws -> IosOpenedReadiumPublication {
        guard let fileURL = FileURL(url: managed.fileURL) else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        let asset: Asset
        switch await assetRetriever.retrieve(url: fileURL) {
        case let .success(value): asset = value
        case .failure: throw IosReaderFailure(code: .corruptFile)
        }
        let publication: Publication
        switch await publicationOpener.open(asset: asset, allowUserInteraction: false) {
        case let .success(value): publication = value
        case .failure: throw IosReaderFailure(code: .parseFailed)
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
            throw IosReaderFailure(code: Self.failureCode(error.status))
        } catch let error as IosMobiPublicationError {
            switch error {
            case .closed, .invalidResourceIndex, .invalidResourcePath,
                 .duplicateResourcePath, .invalidTableOfContents, .invalidTextEncoding:
                throw IosReaderFailure(code: .corruptFile)
            case .invalidSourceIdentity:
                throw IosReaderFailure(code: .corruptFile)
            case .missingReadingOrder, .unsupportedMediaType:
                throw IosReaderFailure(code: .unsupportedFormat)
            }
        }
    }

    private static func failureCode(_ status: IosMobiCoreStatus) -> IosReaderFailureCode {
        switch status {
        case .drmProtected:
            .drmProtected
        case .unsupported, .noContent:
            .unsupportedFormat
        case .limitExceeded, .outOfMemory:
            .outOfMemoryRisk
        case .fileNotFound, .notFound:
            .resourceMissing
        case .io:
            .engineError
        case .invalidArgument, .corrupt, .parseFailed, .outOfRange,
             .bufferTooSmall, .internalFailure:
            .corruptFile
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
