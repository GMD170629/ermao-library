import Foundation

struct IosMobiContentSanitizer: Sendable {
    private static let contentSecurityPolicy = """
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; img-src 'self' data: blob:; media-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'; script-src 'none'">
    """

    func sanitize(data: Data, mediaType: String) throws -> Data {
        guard var source = String(data: data, encoding: .utf8) else {
            throw IosMobiPublicationError.invalidTextEncoding
        }

        if mediaType.lowercased() == "text/css" {
            source = sanitizeCSS(source)
        } else {
            source = sanitizeMarkup(source)
        }
        return Data(source.utf8)
    }

    func sanitizeMarkup(_ source: String) -> String {
        var result = replacing(
            #"(?is)<\s*(script|iframe|object|embed)\b[^>]*>.*?<\s*/\s*\1\s*>"#,
            in: source,
            with: ""
        )
        result = replacing(
            #"(?is)<\s*(script|iframe|object|embed)\b[^>]*/?\s*>"#,
            in: result,
            with: ""
        )
        result = replacing(
            #"(?is)<\s*base\b[^>]*>|<\s*meta\b[^>]*http-equiv\s*=\s*([\"']?)refresh\1[^>]*>"#,
            in: result,
            with: ""
        )
        result = replacing(
            #"(?is)\s+on[a-z][a-z0-9_-]*\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)"#,
            in: result,
            with: ""
        )
        result = replacing(
            #"(?is)(\s+(?:href|xlink:href|action|formaction)\s*=\s*)([\"'])(?:[a-z][a-z0-9+.-]*:|//)[^\"']*\2"#,
            in: result,
            with: "$1$2#$2"
        )
        result = replacing(
            #"(?is)(\s+(?:href|xlink:href|action|formaction)\s*=\s*)(?:[a-z][a-z0-9+.-]*:|//)[^\s>]+"#,
            in: result,
            with: "$1#"
        )
        result = replacing(
            #"(?is)(\s+(?:src|poster)\s*=\s*)([\"'])(?!(?:data):)(?:[a-z][a-z0-9+.-]*:|//)[^\"']*\2"#,
            in: result,
            with: "$1$2#$2"
        )
        result = replacing(
            #"(?is)(\s+(?:src|poster)\s*=\s*)(?!(?:data):)(?:[a-z][a-z0-9+.-]*:|//)[^\s>]+"#,
            in: result,
            with: "$1#"
        )
        // Apply the same network boundary to embedded style blocks and style
        // attributes. The CSP remains defense in depth if malformed markup slips
        // past the textual transformation.
        result = sanitizeCSS(result)

        let policy = Self.contentSecurityPolicy
        if let head = result.range(of: #"(?i)<head\b[^>]*>"#, options: .regularExpression) {
            result.insert(contentsOf: policy, at: head.upperBound)
        } else if let html = result.range(of: #"(?i)<html\b[^>]*>"#, options: .regularExpression) {
            result.insert(contentsOf: "<head>\(policy)</head>", at: html.upperBound)
        } else {
            result = "<head>\(policy)</head>" + result
        }
        return result
    }

    func sanitizeCSS(_ source: String) -> String {
        var result = replacing(
            #"(?is)@import\s+(?:url\s*\()?\s*[\"']?(?:[a-z][a-z0-9+.-]*:|//)[^;\)]*\)?\s*;"#,
            in: source,
            with: ""
        )
        result = replacing(
            #"(?is)url\s*\(\s*[\"']?(?!data:)(?:[a-z][a-z0-9+.-]*:|//)[^\)]*\)"#,
            in: result,
            with: "url()"
        )
        return result
    }

    private func replacing(_ pattern: String, in source: String, with replacement: String) -> String {
        source.replacingOccurrences(
            of: pattern,
            with: replacement,
            options: .regularExpression
        )
    }
}
