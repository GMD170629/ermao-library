import Foundation

struct OPFPackage: Equatable, Sendable {
    let readingOrderHREFs: [String]
    let progression: MobiReadingProgression
}

enum OPFPackageParserError: Error, Equatable, Sendable {
    case malformedXML
    case emptySpine
}

struct OPFPackageParser: Sendable {
    func parse(_ data: Data) throws -> OPFPackage {
        let delegate = Delegate()
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse() else {
            throw OPFPackageParserError.malformedXML
        }
        let hrefs = delegate.spine.compactMap { delegate.manifest[$0] }
        guard !hrefs.isEmpty else {
            throw OPFPackageParserError.emptySpine
        }
        return OPFPackage(readingOrderHREFs: hrefs, progression: delegate.progression)
    }

    private final class Delegate: NSObject, XMLParserDelegate {
        var manifest: [String: String] = [:]
        var spine: [String] = []
        var progression: MobiReadingProgression = .leftToRight

        func parser(
            _ parser: XMLParser,
            didStartElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?,
            attributes attributeDict: [String: String] = [:]
        ) {
            switch localName(qName ?? elementName) {
            case "item":
                if let id = attributeDict["id"], let href = attributeDict["href"] {
                    manifest[id] = href
                }
            case "spine":
                if attributeDict["page-progression-direction"]?.lowercased() == "rtl" {
                    progression = .rightToLeft
                }
            case "itemref":
                if let idref = attributeDict["idref"] {
                    spine.append(idref)
                }
            default:
                break
            }
        }

        private func localName(_ value: String) -> String {
            value.split(separator: ":").last.map(String.init) ?? value
        }
    }
}
