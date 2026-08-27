import Foundation
@preconcurrency import ErmaoShared

enum IosPublicationSecurityError: Error, Sendable {
    case invalidEncoding
    case invalidMarkup
    case unsafeEntity
    case sizeLimit
}

enum IosPublicationSecurityPolicy {
    static let profile = "ios-v2"
    private static let maximumMarkupBytes = 64 * 1_024 * 1_024
    private static let contentSecurityPolicy =
        "default-src 'none'; base-uri 'none'; connect-src 'none'; form-action 'none'; " +
        "frame-src 'none'; child-src 'none'; object-src 'none'; script-src 'none'; " +
        // Readium serves its own CSS and declared fonts from a separate, local-only asset origin.
        // Author scripts/network access remain forbidden; do not allow the whole readium: scheme.
        "style-src 'self' readium://assets blob: 'unsafe-inline'; img-src 'self' blob: data:; " +
        "font-src 'self' readium://assets blob: data:; media-src 'self' blob: data:"
    private static let securityStyle =
        "iframe,frame,object,embed,applet{display:none!important;}" +
        "input,button,select,textarea{pointer-events:none!important;}"

    static func isMarkup(_ resource: String) -> Bool {
        let path = resource.lowercased()
            .split(whereSeparator: { $0 == "#" || $0 == "?" })
            .first.map(String.init) ?? resource
        return path.hasSuffix(".html") || path.hasSuffix(".htm") || path.hasSuffix(".xhtml")
    }

    static func decorate(data: Data) throws -> Data {
        guard !data.isEmpty, data.count <= maximumMarkupBytes else {
            throw IosPublicationSecurityError.sizeLimit
        }
        let markup = try decode(data)
        let originalProjection = try validate(markup)
        let lexicalMarkup = maskNonMarkup(markup)
        guard let lexicalOpen = lexicalMarkup.range(
            of: #"(?i)<(?:[A-Za-z_][\w.-]*:)?head\b[^>]*>"#,
            options: .regularExpression
        ), let open = Range(NSRange(lexicalOpen, in: lexicalMarkup), in: markup),
              let lexicalClose = lexicalMarkup.range(
                  of: #"(?i)</(?:[A-Za-z_][\w.-]*:)?head\s*>"#,
                  options: .regularExpression,
                  range: lexicalOpen.upperBound ..< lexicalMarkup.endIndex
              ), let close = Range(NSRange(lexicalClose, in: lexicalMarkup), in: markup)
        else {
            throw IosPublicationSecurityError.invalidMarkup
        }
        var safeHead = String(markup[open.upperBound ..< close.lowerBound])
        safeHead = replacing(
            #"(?i)<(?:[A-Za-z_][\w.-]*:)?base\b[^>]*(?:/\s*)?>"#,
            in: safeHead,
            with: ""
        )
        safeHead = replacing(
            #"(?is)<(?:[A-Za-z_][\w.-]*:)?meta\b(?=[^>]*\bhttp-equiv\s*=\s*[\"'](?:content-security-policy|refresh)[\"'])[^>]*(?:/\s*)?>"#,
            in: safeHead,
            with: ""
        )
        let decoration =
            #"<meta http-equiv="Content-Security-Policy" content=""# +
            contentSecurityPolicy +
            #"" data-shuku-security-profile=""# + profile + #""/>"# +
            #"<style data-shuku-security-profile=""# + profile + #"">"# +
            securityStyle + "</style>"
        var result = String(markup[..<open.upperBound]) + decoration + safeHead + markup[close.lowerBound...]
        if let declaration = result.range(
            of: #"(?i)<\?xml\b[^?]*\?>"#,
            options: .regularExpression
        ) {
            let updated = replacing(
                #"(?i)encoding\s*=\s*[\"'][^\"']+[\"']"#,
                in: String(result[declaration]),
                with: #"encoding="utf-8""#
            )
            result.replaceSubrange(declaration, with: updated)
        }
        let decorated = Data(result.utf8)
        guard try validate(result) == originalProjection else {
            throw IosPublicationSecurityError.invalidMarkup
        }
        return decorated
    }

    static func locatorBodyProjection(data: Data) throws -> [[String: String]] {
        try validate(decode(data)).map { element in
            var value = ["path": element.path, "localName": element.localName]
            if let id = element.id { value["id"] = id }
            if let text = element.text { value["text"] = text }
            return value
        }
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
            let declaration = prefix.range(
                of: #"(?i)<\?xml\b[^?]*\?>"#,
                options: .regularExpression
            ).map { String(prefix[$0]) }
            let encoding = declaration?.range(
                of: #"(?i)encoding\s*=\s*[\"'](?<encoding>[^\"']+)[\"']"#,
                options: .regularExpression
            ).map { String(declaration![$0]) } ?? "utf-8"
            guard encoding.lowercased().contains("utf-8") || encoding == "utf-8" else {
                throw IosPublicationSecurityError.invalidEncoding
            }
            decoded = String(data: data, encoding: .utf8)
        }
        guard let decoded, !decoded.contains("\0") else {
            throw IosPublicationSecurityError.invalidEncoding
        }
        return decoded
    }

    private static func validate(_ markup: String) throws -> [LocatorElementProjection] {
        try validateDeclarations(markup)
        let parserMarkup = replacingStandardEntitiesForParsing(markup)
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

    private static func validateDeclarations(_ markup: String) throws {
        let lexicalMarkup = maskNonMarkup(markup)
        let fullRange = NSRange(location: 0, length: (lexicalMarkup as NSString).length)
        let entity = try! NSRegularExpression(pattern: #"(?i)<!ENTITY\b"#)
        guard entity.firstMatch(in: lexicalMarkup, range: fullRange) == nil else {
            throw IosPublicationSecurityError.unsafeEntity
        }

        let opens = try! NSRegularExpression(pattern: #"(?i)<!DOCTYPE\b"#)
            .matches(in: lexicalMarkup, range: fullRange)
        guard !opens.isEmpty else { return }
        let declarations = try! NSRegularExpression(
            pattern: #"(?is)<!DOCTYPE\b[^>]*>"#
        ).matches(in: lexicalMarkup, range: fullRange)
        guard opens.count == 1, declarations.count == 1,
              opens[0].range.location == declarations[0].range.location
        else {
            throw IosPublicationSecurityError.unsafeEntity
        }

        let declaration = (lexicalMarkup as NSString).substring(with: declarations[0].range)
        let declarationRange = NSRange(location: 0, length: (declaration as NSString).length)
        let safeDoctype = try! NSRegularExpression(
            pattern: #"(?is)\A<!DOCTYPE\s+html\s*(?:PUBLIC\s+[\"']-//W3C//DTD\s+XHTML\s+(?:1\.1|1\.0\s+(?:Strict|Transitional|Frameset))//EN[\"']\s+[\"']https?://www\.w3\.org/TR/(?:xhtml11/DTD/xhtml11\.dtd|xhtml1/DTD/xhtml1-(?:strict|transitional|frameset)\.dtd)[\"'])?\s*>\z"#
        )
        let safeMatch = safeDoctype.firstMatch(in: declaration, range: declarationRange)
        let prefix = (lexicalMarkup as NSString)
            .substring(to: declarations[0].range.location)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard safeMatch?.range == declarationRange, prefix.isEmpty else {
            throw IosPublicationSecurityError.unsafeEntity
        }
    }

    private static func replacingStandardEntitiesForParsing(_ markup: String) -> String {
        let lexicalMarkup = maskNonMarkup(markup)
        let fullRange = NSRange(location: 0, length: (lexicalMarkup as NSString).length)
        let references = try! NSRegularExpression(pattern: #"&nbsp;"#)
            .matches(in: lexicalMarkup, range: fullRange)
        let result = NSMutableString(string: markup)
        for reference in references.reversed() {
            result.replaceCharacters(in: reference.range, with: "&#xA0;")
        }
        return result as String
    }

    private static func replacing(_ pattern: String, in source: String, with replacement: String) -> String {
        source.replacingOccurrences(of: pattern, with: replacement, options: .regularExpression)
    }

    private static func maskNonMarkup(_ markup: String) -> String {
        let masked = NSMutableString(string: markup)
        let expression = try! NSRegularExpression(
            pattern: #"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>"#,
            options: [.dotMatchesLineSeparators]
        )
        let matches = expression.matches(
            in: markup,
            range: NSRange(location: 0, length: masked.length)
        )
        for match in matches.reversed() {
            masked.replaceCharacters(
                in: match.range,
                with: String(repeating: " ", count: match.range.length)
            )
        }
        return masked as String
    }
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
        if mediaType.lowercased() == "text/css" { return data }
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
