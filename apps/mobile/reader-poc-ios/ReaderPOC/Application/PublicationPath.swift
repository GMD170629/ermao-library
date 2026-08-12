import Foundation

enum PublicationPath {
    static func normalizedResourcePath(_ rawValue: String) -> String? {
        normalizedReference(rawValue, preservingSuffix: false)
    }

    static func normalizedReference(_ rawValue: String, preservingSuffix: Bool = true) -> String? {
        guard !rawValue.isEmpty, !rawValue.contains("\0") else {
            return nil
        }

        let splitIndex = rawValue.firstIndex { $0 == "?" || $0 == "#" }
        let rawPath = splitIndex.map { String(rawValue[..<$0]) } ?? rawValue
        let suffix = preservingSuffix && splitIndex != nil
            ? String(rawValue[splitIndex!...])
            : ""
        let decodedPath = rawPath.removingPercentEncoding ?? rawPath

        var segments: [String] = []
        for segment in decodedPath.split(separator: "/", omittingEmptySubsequences: true) {
            switch segment {
            case ".":
                continue
            case "..":
                guard !segments.isEmpty else {
                    return nil
                }
                segments.removeLast()
            default:
                segments.append(String(segment))
            }
        }

        guard !segments.isEmpty else {
            return suffix.hasPrefix("#") ? suffix : nil
        }
        let allowed = CharacterSet.urlPathAllowed.subtracting(CharacterSet(charactersIn: "?#"))
        let encodedSegments = segments.compactMap { $0.addingPercentEncoding(withAllowedCharacters: allowed) }
        guard encodedSegments.count == segments.count else {
            return nil
        }
        return encodedSegments.joined(separator: "/") + suffix
    }

    static func resourcePath(from reference: String) -> String? {
        normalizedReference(reference)?.split(whereSeparator: { $0 == "?" || $0 == "#" }).first.map(String.init)
    }
}
