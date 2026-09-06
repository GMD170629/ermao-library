import Foundation
@preconcurrency import ErmaoShared

enum IosPublicationSecurityError: Error, Sendable {
    case invalidEncoding
    case invalidMarkup
    case rejected(ruleId: String, errorCode: String)
}

/// Renderer-only actions for native reflowable readers.
///
/// Markup, declaration, URI, and CSS decisions belong to the generated KMP safety
/// policy. This type only adapts the sanitized result to Readium/WebKit and keeps
/// the parser projection in sync with the sanitized in-memory document.
enum IosPublicationSecurityPolicy {
    private static let contentSecurityPolicy =
        "default-src 'none'; base-uri 'none'; connect-src 'none'; form-action 'none'; " +
        "frame-src 'none'; child-src 'none'; object-src 'none'; script-src 'none'; " +
        "style-src 'self' readium://assets blob: 'unsafe-inline'; img-src 'self' blob: data:; " +
        "font-src 'self' readium://assets blob: data:; media-src 'self' blob: data:"
    private static var securityHead: String {
        let meta = #"<meta http-equiv="Content-Security-Policy" content="\#(contentSecurityPolicy)"/>"#
        let selectors = ErmaoShared.PublicKt.readerSafetySanitizedElementSelectors()
            .joined(separator: ",")
        let style = selectors.isEmpty ? "" : "<style>\(selectors){display:none!important;}</style>"
        return meta + style + readerThemeStyle
    }

    private static var readerThemeStyle: String {
        """
        <style data-shuku-reader-theme-adapter="v1">
        :root[style*="--USER__backgroundColor"] { background-image: none !important; }
        :root[style*="--USER__backgroundColor"] body,
        :root[style*="--USER__backgroundColor"] body *,
        :root[style*="--USER__backgroundColor"] body *::before,
        :root[style*="--USER__backgroundColor"] body *::after {
          background-color: transparent !important;
          background-image: none !important;
        }
        :root.readium-sepia-on {
          --RS__linkColor: \(GeneratedDesignTokens.Reader.Warm.link) !important;
          --RS__visitedColor: \(GeneratedDesignTokens.Reader.Warm.link) !important;
        }
        :root.readium-night-on {
          --RS__linkColor: \(GeneratedDesignTokens.Reader.Night.link) !important;
          --RS__visitedColor: \(GeneratedDesignTokens.Reader.Night.link) !important;
        }
        :root[style*="\(GeneratedDesignTokens.Reader.Day.canvas)" i] {
          --RS__linkColor: \(GeneratedDesignTokens.Reader.Day.link) !important;
          --RS__visitedColor: \(GeneratedDesignTokens.Reader.Day.link) !important;
        }
        :root[style*="\(GeneratedDesignTokens.Reader.Green.canvas)" i] {
          --RS__linkColor: \(GeneratedDesignTokens.Reader.Green.link) !important;
          --RS__visitedColor: \(GeneratedDesignTokens.Reader.Green.link) !important;
        }
        </style>
        """
    }

    /// Only for XHTML emitted by the owned TXT/FB2 templates, never original chapters.
    static func generatedChapter(_ markup: String) throws -> Data {
        try decorate(data: Data(markup.utf8))
    }

    static func decorate(data: Data) throws -> Data {
        guard !data.isEmpty else {
            throw IosPublicationSecurityError.invalidMarkup
        }
        let markup = try decode(data)
        let sanitized = try sanitize(markup, sourceByteCount: Int64(data.count))
        let safeMarkup = sanitized.markup
        guard let open = HEAD_OPEN.firstMatch(in: safeMarkup),
              let close = HEAD_CLOSE.firstMatch(in: safeMarkup, after: open.range.upperBound)
        else {
            throw IosPublicationSecurityError.invalidMarkup
        }
        let headStart = open.range.upperBound
        let originalHead = String(safeMarkup[headStart ..< close.range.lowerBound])
        let viewport = META_TAG.find(in: originalHead).contains { match in
            NAME.find(in: match.value).contains {
                $0.groups["value"]?.lowercased() == "viewport"
            }
        } ? "" : DEVICE_VIEWPORT
        let decorated = String(safeMarkup[..<headStart]) + securityHead + viewport + originalHead +
            String(safeMarkup[close.range.lowerBound...])
        return Data(normalizeXmlDeclaration(decorated).utf8)
    }

    /// Prepares a Readium resource before the EPUB parser sees it. Media type is only a
    /// capability hint; the content root is detected by the shared KMP lexical pass.
    static func prepareResource(data: Data, mediaType: String?) throws -> Data {
        guard !data.isEmpty else {
            if isTextualMediaType(mediaType) { throw IosPublicationSecurityError.invalidMarkup }
            return data
        }
        guard let markup = decodeOptional(data) else {
            if isTextualMediaType(mediaType) {
                throw IosPublicationSecurityError.invalidEncoding
            }
            return data
        }
        let leading = markup.trimmingCharacters(in: CharacterSet.whitespacesAndNewlines.union(CharacterSet(charactersIn: "\u{FEFF}")))
        guard leading.hasPrefix("<") || isTextualMediaType(mediaType) else { return data }

        let facade = ErmaoShared.ReaderSafetyFacade()
        let root = facade.rootElementName(markup: markup)
        let normalizedMediaType = baseMediaType(mediaType)
        switch true {
        case normalizedMediaType == "text/css":
            return try sanitizedCss(facade: facade, source: markup, sourceByteCount: Int64(data.count))
        case root == "html" || normalizedMediaType == "application/xhtml+xml" || normalizedMediaType == "text/html":
            return try decorate(data: data)
        case root == "svg" || normalizedMediaType == "image/svg+xml":
            let sanitized = try sanitizedMarkup(
                facade: facade,
                source: markup,
                sourceByteCount: Int64(data.count)
            )
            guard let encoded = sanitized.markup.data(using: .utf8) else {
                throw IosPublicationSecurityError.invalidEncoding
            }
            return encoded
        default:
            let prepared = try preparedXml(facade: facade, source: markup, sourceByteCount: Int64(data.count))
            return Data(prepared.parserMarkup.utf8)
        }
    }

    static func locatorBodyProjection(data: Data) throws -> [[String: String]] {
        let markup = try decode(data)
        let sanitized = try sanitize(markup, sourceByteCount: Int64(data.count))
        return try parse(sanitized.parserMarkup).map { element in
            var value = ["path": element.path, "localName": element.localName]
            if let id = element.id { value["id"] = id }
            if let text = element.text { value["text"] = text }
            return value
        }
    }

    private static func sanitize(
        _ markup: String,
        sourceByteCount: Int64
    ) throws -> ErmaoShared.ReaderSanitizedMarkup {
        let result = ErmaoShared.ReaderSafetyFacade().sanitizeMarkup(
            markup: markup,
            sourceByteCount: sourceByteCount
        )
        if let accepted = result as? ErmaoShared.ReaderSafetyMarkupResultAccepted {
            return accepted.value
        }
        if let rejected = result as? ErmaoShared.ReaderSafetyMarkupResultRejected {
            throw IosPublicationSecurityError.rejected(
                ruleId: rejected.failure.ruleId,
                errorCode: rejected.failure.errorCode
            )
        }
        throw IosPublicationSecurityError.invalidMarkup
    }

    private static func sanitizedMarkup(
        facade: ErmaoShared.ReaderSafetyFacade,
        source: String,
        sourceByteCount: Int64
    ) throws -> ErmaoShared.ReaderSanitizedMarkup {
        let result = facade.sanitizeMarkup(markup: source, sourceByteCount: sourceByteCount)
        if let accepted = result as? ErmaoShared.ReaderSafetyMarkupResultAccepted {
            return accepted.value
        }
        if let rejected = result as? ErmaoShared.ReaderSafetyMarkupResultRejected {
            throw IosPublicationSecurityError.rejected(
                ruleId: rejected.failure.ruleId,
                errorCode: rejected.failure.errorCode
            )
        }
        throw IosPublicationSecurityError.invalidMarkup
    }

    private static func sanitizedCss(
        facade: ErmaoShared.ReaderSafetyFacade,
        source: String,
        sourceByteCount: Int64
    ) throws -> Data {
        let result = facade.sanitizeCss(css: source, sourceByteCount: sourceByteCount)
        if let accepted = result as? ErmaoShared.ReaderSafetyMarkupResultAccepted {
            return Data(accepted.value.markup.utf8)
        }
        if let rejected = result as? ErmaoShared.ReaderSafetyMarkupResultRejected {
            throw IosPublicationSecurityError.rejected(
                ruleId: rejected.failure.ruleId,
                errorCode: rejected.failure.errorCode
            )
        }
        throw IosPublicationSecurityError.invalidMarkup
    }

    private static func preparedXml(
        facade: ErmaoShared.ReaderSafetyFacade,
        source: String,
        sourceByteCount: Int64
    ) throws -> ErmaoShared.ReaderSanitizedMarkup {
        let result = facade.prepareXmlControlDocument(markup: source, sourceByteCount: sourceByteCount)
        if let accepted = result as? ErmaoShared.ReaderSafetyMarkupResultAccepted {
            return accepted.value
        }
        if let rejected = result as? ErmaoShared.ReaderSafetyMarkupResultRejected {
            throw IosPublicationSecurityError.rejected(
                ruleId: rejected.failure.ruleId,
                errorCode: rejected.failure.errorCode
            )
        }
        throw IosPublicationSecurityError.invalidMarkup
    }

    private static func isTextualMediaType(_ mediaType: String?) -> Bool {
        switch baseMediaType(mediaType) {
        case "text/css", "text/html", "application/xhtml+xml", "application/xml", "text/xml", "image/svg+xml":
            true
        default:
            false
        }
    }

    private static func baseMediaType(_ mediaType: String?) -> String? {
        mediaType?
            .split(separator: ";", maxSplits: 1, omittingEmptySubsequences: true)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    private static func decodeOptional(_ data: Data) -> String? {
        if data.starts(with: [0xEF, 0xBB, 0xBF]) {
            return String(data: data.dropFirst(3), encoding: .utf8)
        }
        if data.starts(with: [0xFF, 0xFE]) {
            return String(data: data.dropFirst(2), encoding: .utf16LittleEndian)
        }
        if data.starts(with: [0xFE, 0xFF]) {
            return String(data: data.dropFirst(2), encoding: .utf16BigEndian)
        }
        if let utf8 = String(data: data, encoding: .utf8) {
            return utf8
        }
        let prefix = String(decoding: data.prefix(512), as: UTF8.self)
        guard prefix.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("<") else { return nil }
        guard let encoding = declaredEncoding(in: prefix) else { return nil }
        return String(data: data, encoding: encoding)
    }

    private static func decode(_ data: Data) throws -> String {
        let decoded: String?
        if data.starts(with: [0xEF, 0xBB, 0xBF]) {
            decoded = String(data: data.dropFirst(3), encoding: .utf8)
        } else if data.starts(with: [0xFF, 0xFE]) {
            decoded = String(data: data.dropFirst(2), encoding: .utf16LittleEndian)
        } else if data.starts(with: [0xFE, 0xFF]) {
            decoded = String(data: data.dropFirst(2), encoding: .utf16BigEndian)
        } else {
            let prefix = String(decoding: data.prefix(512), as: UTF8.self)
            let encoding = declaredEncoding(in: prefix) ?? .utf8
            decoded = String(data: data, encoding: encoding)
        }
        guard let decoded else {
            throw IosPublicationSecurityError.invalidEncoding
        }
        return decoded
    }

    private static func declaredEncoding(in prefix: String) -> String.Encoding? {
        let declaration = prefix.range(
            of: #"(?i)<\?xml\b[^?]*\?>"#,
            options: .regularExpression
        ).map { String(prefix[$0]) }
        let name = declaration?.range(
            of: #"(?i)encoding\s*=\s*[\"']([^\"']+)[\"']"#,
            options: .regularExpression
        ).map { String(declaration![$0]) }
        let normalized = name?
            .replacingOccurrences(of: #"(?i).*encoding\s*=\s*[\"']"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"[\"'].*$"#, with: "", options: .regularExpression)
            .lowercased()
            .replacingOccurrences(of: "_", with: "-")
        switch normalized {
        case nil, "utf-8", "utf8": return .utf8
        case "utf-16", "utf16": return .utf16
        case "utf-16le", "utf16le": return .utf16LittleEndian
        case "utf-16be", "utf16be": return .utf16BigEndian
        case "windows-1251", "cp1251": return .windowsCP1251
        case "iso-8859-1", "latin1": return .isoLatin1
        default: return nil
        }
    }

    private static func parse(_ parserMarkup: String) throws -> [LocatorElementProjection] {
        let delegate = StrictXhtmlDelegate()
        let parser = XMLParser(data: Data(parserMarkup.utf8))
        parser.shouldProcessNamespaces = true
        parser.shouldResolveExternalEntities = false
        parser.delegate = delegate
        guard parser.parse(), delegate.isValid else {
            throw IosPublicationSecurityError.invalidMarkup
        }
        return delegate.bodyProjection
    }

    private static func normalizeXmlDeclaration(_ markup: String) -> String {
        guard let declaration = markup.range(
            of: #"(?i)<\?xml\b[^?]*\?>"#,
            options: .regularExpression
        ) else {
            return markup
        }
        let replacement = String(markup[declaration]).replacingOccurrences(
            of: #"(?i)encoding\s*=\s*[\"'][^\"']+[\"']"#,
            with: "encoding=\"utf-8\"",
            options: .regularExpression
        )
        var result = markup
        result.replaceSubrange(declaration, with: replacement)
        return result
    }

    private struct RegexMatch {
        let range: Range<String.Index>
        let value: String
        let groups: [String: String]
    }

    private struct Regex {
        let expression: NSRegularExpression

        init(_ pattern: String) {
            expression = try! NSRegularExpression(pattern: pattern)
        }

        func firstMatch(in value: String, after: String.Index? = nil) -> RegexMatch? {
            let start = after?.utf16Offset(in: value) ?? 0
            let nsRange = NSRange(location: start, length: value.utf16.count - start)
            guard let match = expression.firstMatch(in: value, range: nsRange),
                  let range = Range(match.range, in: value)
            else { return nil }
            var groups: [String: String] = [:]
            let valueRange = match.range(withName: "value")
            if valueRange.location != NSNotFound, let captured = Range(valueRange, in: value) {
                groups["value"] = String(value[captured])
            }
            return RegexMatch(range: range, value: String(value[range]), groups: groups)
        }

        func find(in value: String) -> [RegexMatch] {
            expression.matches(
                in: value,
                range: NSRange(location: 0, length: value.utf16.count)
            ).compactMap { match in
                guard let range = Range(match.range, in: value) else { return nil }
                var groups: [String: String] = [:]
                let valueRange = match.range(withName: "value")
                if valueRange.location != NSNotFound, let captured = Range(valueRange, in: value) {
                    groups["value"] = String(value[captured])
                }
                return RegexMatch(range: range, value: String(value[range]), groups: groups)
            }
        }
    }

    private static let DEVICE_VIEWPORT =
        #"<meta name="viewport" content="width=device-width, initial-scale=1.0"/>"#
    private static let HEAD_OPEN = Regex(#"(?i)<(?:[A-Za-z_][\w.-]*:)?head\b[^>]*>"#)
    private static let HEAD_CLOSE = Regex(#"(?i)</(?:[A-Za-z_][\w.-]*:)?head\s*>"#)
    private static let META_TAG = Regex(#"(?i)<(?:[A-Za-z_][\w.-]*:)?meta\b[^>]*(?:/\s*)?>"#)
    private static let NAME = Regex(#"(?i)\bname\s*=\s*[\"'](?<value>[^\"']+)[\"']"#)
}

private struct LocatorElementProjection: Equatable {
    let path: String
    let localName: String
    let id: String?
    let text: String?
}

private final class ProjectionNode {
    let localName: String
    let id: String?
    var locatorText = ""
    var children: [ProjectionNode] = []

    init(localName: String, id: String?) {
        self.localName = localName
        self.id = id
    }
}

private final class StrictXhtmlDelegate: NSObject, XMLParserDelegate {
    private var depth = 0
    private var rootName: String?
    private var headCount = 0
    private var bodyCount = 0
    private var body: ProjectionNode?
    private var stack: [ProjectionNode] = []

    var isValid: Bool { rootName == "html" && headCount == 1 && bodyCount == 1 }
    var bodyProjection: [LocatorElementProjection] {
        guard let body else { return [] }
        return project(body, path: "/body[1]")
    }

    func parser(
        _: XMLParser,
        didStartElement elementName: String,
        namespaceURI _: String?,
        qualifiedName qName: String?,
        attributes: [String: String] = [:]
    ) {
        depth += 1
        let name = (qName ?? elementName).split(separator: ":").last.map(String.init)?.lowercased()
        if depth == 1 { rootName = name }
        if depth == 2, name == "head" { headCount += 1 }
        if depth == 2, name == "body" { bodyCount += 1 }
        guard let name else { return }
        let node = ProjectionNode(localName: name, id: attributes["id"])
        stack.last?.children.append(node)
        stack.append(node)
        if depth == 2, name == "body" { body = node }
    }

    func parser(
        _: XMLParser,
        didEndElement _: String,
        namespaceURI _: String?,
        qualifiedName _: String?
    ) {
        _ = stack.popLast()
        depth -= 1
    }

    func parser(_: XMLParser, foundCharacters string: String) {
        for node in stack where Self.locatorBlocks.contains(node.localName) {
            node.locatorText += string
        }
    }

    func parser(
        _: XMLParser,
        resolveExternalEntityName _: String,
        systemID _: String?
    ) -> Data? {
        Data()
    }

    private func project(_ node: ProjectionNode, path: String) -> [LocatorElementProjection] {
        var records = [LocatorElementProjection(
            path: path,
            localName: node.localName,
            id: node.id,
            text: Self.locatorBlocks.contains(node.localName) ? Self.normalize(node.locatorText) : nil
        )]
        var siblingCounts: [String: Int] = [:]
        for child in node.children {
            let ordinal = siblingCounts[child.localName, default: 0] + 1
            siblingCounts[child.localName] = ordinal
            records += project(child, path: "\(path)/\(child.localName)[\(ordinal)]")
        }
        return records
    }

    private static func normalize(_ value: String) -> String {
        let canonical = value
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .precomposedStringWithCanonicalMapping
        return canonical
            .replacingOccurrences(of: #"[\s\p{Z}]+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static let locatorBlocks: Set<String> = [
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote",
        "figcaption", "td", "th",
    ]
}

struct IosPublicationSecurityAdapter: Sendable {
    func decorate(data: Data, mediaType: String) throws -> Data {
        let baseMediaType = mediaType
            .split(separator: ";", maxSplits: 1, omittingEmptySubsequences: true)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        if baseMediaType == "text/css" { return data }
        guard let markup = String(data: data, encoding: .utf8) else {
            throw IosPublicationSecurityError.invalidEncoding
        }
        let prepared = try MobiMarkupEnvelope().prepare(markup: markup)
        return try IosPublicationSecurityPolicy.decorate(data: Data(prepared.utf8))
    }

    func decorateMarkup(_ source: String) throws -> String {
        String(decoding: try IosPublicationSecurityPolicy.decorate(data: Data(source.utf8)), as: UTF8.self)
    }
}
