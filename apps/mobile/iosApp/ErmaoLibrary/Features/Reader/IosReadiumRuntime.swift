import Foundation
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer
import SwiftSoup

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

    func open(_ managed: IosManagedPublication) async throws -> Publication {
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
        return publication
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
