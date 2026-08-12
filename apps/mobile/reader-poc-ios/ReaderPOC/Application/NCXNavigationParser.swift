import Foundation

enum NCXNavigationParserError: Error, Equatable, Sendable {
    case malformedXML
}

struct NCXNavigationParser: Sendable {
    func parse(_ data: Data) throws -> [MobiNavigationItem] {
        let delegate = Delegate()
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse() else {
            throw NCXNavigationParserError.malformedXML
        }
        return delegate.roots.map(\.item)
    }

    private final class Node {
        let id: String
        var title = ""
        var href = ""
        var children: [Node] = []

        init(id: String) {
            self.id = id
        }

        var item: MobiNavigationItem {
            MobiNavigationItem(
                id: id,
                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                href: PublicationPath.normalizedReference(href) ?? href,
                children: children.map(\.item)
            )
        }
    }

    private final class Delegate: NSObject, XMLParserDelegate {
        var roots: [Node] = []
        private var stack: [Node] = []
        private var textDepth = 0
        private var textBuffer = ""
        private var generatedIdentifier = 0

        func parser(
            _ parser: XMLParser,
            didStartElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?,
            attributes attributeDict: [String: String] = [:]
        ) {
            switch localName(qName ?? elementName) {
            case "navPoint":
                generatedIdentifier += 1
                stack.append(Node(id: attributeDict["id"] ?? "nav-\(generatedIdentifier)"))
            case "text":
                guard !stack.isEmpty else { return }
                textDepth += 1
                textBuffer = ""
            case "content":
                stack.last?.href = attributeDict["src"] ?? ""
            default:
                break
            }
        }

        func parser(_ parser: XMLParser, foundCharacters string: String) {
            if textDepth > 0 {
                textBuffer += string
            }
        }

        func parser(
            _ parser: XMLParser,
            didEndElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?
        ) {
            switch localName(qName ?? elementName) {
            case "text":
                stack.last?.title = textBuffer
                textBuffer = ""
                textDepth = max(0, textDepth - 1)
            case "navPoint":
                guard let node = stack.popLast() else { return }
                if let parent = stack.last {
                    parent.children.append(node)
                } else {
                    roots.append(node)
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
