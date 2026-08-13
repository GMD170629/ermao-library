import Foundation
import PDFKit
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer
import SwiftSoup

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
            onCreatePublication: sanitizeEpubPublication
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
        guard managed.fingerprint.parserVersion == IosMobiBook.parserIdentifier,
              managed.fingerprint.normalizationVersion == IosMobiBook.normalizationIdentifier,
              let contentFingerprint = managed.serverContentFingerprint
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        do {
            let result = try await IosMobiPublicationFactory().open(
                fileURL: managed.fileURL,
                contentFingerprint: contentFingerprint,
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
            case .invalidContentFingerprint:
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
private func sanitizeEpubPublication(
    _: inout Manifest,
    container: inout Container,
    _: inout PublicationServicesBuilder
) async {
    container = container.map { href, resource in
        guard IosEpubContentSanitizer.isMarkup(href.string) else { return resource }
        return resource.mapAsString { markup in
            IosEpubContentSanitizer.sanitize(markup, resource: href.string)
        }
    }
}

enum IosEpubContentSanitizer {
    private static let maximumMarkupBytes = 8 * 1_024 * 1_024
    private static let urlAttributes = ["href", "src", "srcset", "poster", "action", "formaction", "xlink:href"]

    static func isMarkup(_ resource: String) -> Bool {
        let resource = resource.lowercased()
            .split(whereSeparator: { $0 == "#" || $0 == "?" })
            .first.map(String.init) ?? resource
        return resource.hasSuffix(".html") || resource.hasSuffix(".htm") || resource.hasSuffix(".xhtml")
    }

    static func sanitize(_ markup: String, resource: String) -> String {
        guard markup.utf8.count <= maximumMarkupBytes else {
            return "<html><body></body></html>"
        }
        do {
            let document = try SwiftSoup.parse(markup, resource)
            try document.select("script, iframe, frame, frameset, object, embed, applet, form, base, foreignobject").remove()
            for meta in try document.select("meta[http-equiv]").array() {
                if try meta.attr("http-equiv").lowercased() == "refresh" { try meta.remove() }
            }
            for element in try document.getAllElements().array() {
                if let attributes = element.getAttributes() {
                    for attribute in attributes.asList() where attribute.getKey().lowercased().hasPrefix("on") {
                        try element.removeAttr(attribute.getKey())
                    }
                }
                for name in urlAttributes {
                    let value = try element.attr(name).trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !value.isEmpty else { continue }
                    if !isAllowedURL(value, tagName: element.tagNameNormal(), attribute: name) {
                        try element.removeAttr(name)
                    }
                }
                let inlineStyle = try element.attr("style")
                if containsRemoteCSS(inlineStyle) {
                    try element.removeAttr("style")
                }
            }
            for style in try document.select("style").array() {
                if containsRemoteCSS(try style.html()) {
                    try style.remove()
                }
            }
            return try document.outerHtml()
        } catch {
            return "<html><body></body></html>"
        }
    }

    private static func isAllowedURL(_ value: String, tagName: String, attribute: String) -> Bool {
        let normalized = value.lowercased()
        if normalized.hasPrefix("#") { return true }
        if normalized.hasPrefix("//") { return false }
        if let colon = normalized.firstIndex(of: ":") {
            let scheme = String(normalized[..<colon])
            return tagName == "a" && attribute == "href" && (scheme == "http" || scheme == "https")
        }
        return !normalized.contains("\\")
    }

    private static func containsRemoteCSS(_ css: String) -> Bool {
        let compact = css.lowercased().filter {
            !$0.isWhitespace && $0 != "\"" && $0 != "'"
        }
        return compact.contains("@import")
            || compact.contains("url(http:")
            || compact.contains("url(https:")
            || compact.contains("url(//")
    }
}
