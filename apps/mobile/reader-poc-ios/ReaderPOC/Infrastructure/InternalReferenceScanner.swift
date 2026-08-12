import Foundation

struct InternalResourceReference: Equatable, Hashable, Sendable {
    let sourceHREF: String
    let targetHREF: String
    let fragment: String?
}

struct InternalReferenceScanner: Sendable {
    private static let attributePattern = #"(?i)\b(?:href|src)\s*=\s*[\"']([^\"']+)[\"']"#
    private static let cssURLPattern = #"(?i)url\(\s*[\"']?([^\"')]+)[\"']?\s*\)"#

    func references(in resource: MobiResource) -> [InternalResourceReference] {
        guard resource.isHTML || resource.mediaType == "text/css",
              let text = String(data: resource.data, encoding: .utf8)
        else {
            return []
        }
        let patterns = resource.isHTML
            ? [Self.attributePattern, Self.cssURLPattern]
            : [Self.cssURLPattern]
        return patterns.flatMap { pattern in
            matches(pattern, text: text).compactMap { resolve($0, relativeTo: resource.href) }
        }
    }

    private func matches(_ pattern: String, text: String) -> [String] {
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(text.startIndex..., in: text)
        return expression.matches(in: text, range: range).compactMap { match in
            guard match.numberOfRanges > 1, let valueRange = Range(match.range(at: 1), in: text) else {
                return nil
            }
            return String(text[valueRange])
        }
    }

    private func resolve(_ rawReference: String, relativeTo sourceHREF: String) -> InternalResourceReference? {
        let reference = rawReference.trimmingCharacters(in: .whitespacesAndNewlines)
        let lowercased = reference.lowercased()
        guard !reference.isEmpty,
              !lowercased.hasPrefix("data:"),
              !lowercased.hasPrefix("http:"),
              !lowercased.hasPrefix("https:"),
              !lowercased.hasPrefix("mailto:"),
              !lowercased.hasPrefix("javascript:")
        else {
            return nil
        }

        let fragment = reference.firstIndex(of: "#").map { String(reference[reference.index(after: $0)...]) }
        let referencePath = reference.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? ""
        let sourcePath = PublicationPath.resourcePath(from: sourceHREF) ?? sourceHREF
        let rawTarget: String
        if referencePath.isEmpty {
            rawTarget = sourcePath
        } else if referencePath.hasPrefix("/") {
            rawTarget = referencePath
        } else {
            let base = sourcePath.split(separator: "/").dropLast().joined(separator: "/")
            rawTarget = base.isEmpty ? referencePath : "\(base)/\(referencePath)"
        }
        guard let target = PublicationPath.normalizedResourcePath(rawTarget) else {
            return nil
        }
        return InternalResourceReference(sourceHREF: sourcePath, targetHREF: target, fragment: fragment)
    }
}
