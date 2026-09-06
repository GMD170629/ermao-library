import Foundation
import ErmaoChapterCore
@preconcurrency import ReadiumShared

/// Projects EPUB navigation from the already protected Readium container.
///
/// This adapter never opens the EPUB file again. It reads container.xml, the OPF,
/// and the selected navigation document through the protected ContainerAsset and
/// delegates chapter semantics to the shared ChapterCore.
internal enum IosEpubChapterProjection {
    static func project(asset: ContainerAsset) async throws -> [Link] {
        try await projectInternal(asset: asset)
    }

    private struct ManifestItem {
        let id: String
        let href: String
        let mediaType: String
        let properties: Set<String>
    }

    private struct PackageInfo {
        let manifest: [ManifestItem]
        let navPath: String?
        let ncxPath: String?

        var manifestPaths: Set<String> {
            Set(manifest.map(\.href))
        }
    }

    private static func projectInternal(asset: ContainerAsset) async throws -> [Link] {
        let indexed = indexContainer(asset.container)
        guard let containerData = try await read(
            asset: asset,
            path: "META-INF/container.xml",
            indexed: indexed
        ) else { return [] }
        guard let opfPath = try parseRootfile(containerData, available: Set(indexed.keys)) else {
            return []
        }
        guard let opfData = try await read(asset: asset, path: opfPath, indexed: indexed) else {
            return []
        }
        let packageInfo = try parsePackage(
            opfData,
            opfPath: opfPath,
            available: Set(indexed.keys)
        )
        guard !packageInfo.manifest.isEmpty else { return [] }

        if let navPath = packageInfo.navPath,
           let navData = try await read(asset: asset, path: navPath, indexed: indexed)
        {
            do {
                let links = try parseNavigation(
                    navData,
                    documentPath: navPath,
                    manifestPaths: packageInfo.manifestPaths,
                    format: UInt32(ERMAO_CHAPTER_EPUB_NAV)
                )
                if !links.isEmpty { return links }
            } catch is IosEpubChapterProjectionError {
                // A malformed optional NAV permits the NCX fallback. Other errors,
                // including ChapterCore and resource failures, remain visible.
            }
        }

        guard let ncxPath = packageInfo.ncxPath,
              let ncxData = try await read(asset: asset, path: ncxPath, indexed: indexed)
        else { return [] }
        return try parseNavigation(
            ncxData,
            documentPath: ncxPath,
            manifestPaths: packageInfo.manifestPaths,
            format: UInt32(ERMAO_CHAPTER_EPUB_NCX)
        )
    }

    private static func indexContainer(_ container: Container) -> [String: AnyURL] {
        var indexed: [String: AnyURL] = [:]
        for url in container.entries {
            guard let path = IosEpubArchiveSafetyPreflight.canonicalArchivePath(url.path) else {
                continue
            }
            indexed[path] = url.removingQuery().removingFragment()
        }
        return indexed
    }

    private static func read(
        asset: ContainerAsset,
        path: String,
        indexed: [String: AnyURL]
    ) async throws -> Data? {
        guard let url = indexed[path], let resource = asset.container[url] else {
            return nil
        }
        return try await resource.read().get()
    }

    private static func parseRootfile(_ data: Data, available: Set<String>) throws -> String? {
        var candidate: String?
        try parseXML(data) { name, attributes in
            guard candidate == nil, name == "rootfile",
                  let raw = attributes["full-path"],
                  let path = IosEpubArchiveSafetyPreflight.canonicalArchivePath(raw),
                  available.contains(path)
            else { return }
            candidate = path
        }
        return candidate
    }

    private static func parsePackage(
        _ data: Data,
        opfPath: String,
        available: Set<String>
    ) throws -> PackageInfo {
        let basePath = opfPath.split(separator: "/", omittingEmptySubsequences: true)
            .dropLast()
            .joined(separator: "/")
        var manifest: [ManifestItem] = []
        var spineToc: String?
        try parseXML(data) { name, attributes in
            switch name {
            case "item":
                let id = attributes["id"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                let rawHref = attributes["href"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                guard !id.isEmpty,
                      let href = resolvePath(basePath: basePath, raw: rawHref, available: available)
                else { return }
                let properties = Set(
                    (attributes["properties"] ?? "")
                        .split(whereSeparator: { $0.isWhitespace })
                        .map(String.init)
                )
                manifest.append(ManifestItem(
                    id: id,
                    href: href,
                    mediaType: attributes["media-type"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "",
                    properties: properties
                ))
            case "spine":
                spineToc = attributes["toc"]?.trimmingCharacters(in: .whitespacesAndNewlines)
                    .flatMap { $0.isEmpty ? nil : $0 }
            default:
                break
            }
        }
        let navPath = manifest.first(where: { $0.properties.contains("nav") })?.href
        let spineNCX = manifest.first(where: { $0.id == spineToc })
        let ncxPath = spineNCX?.href ?? manifest.first(where: {
                $0.mediaType.caseInsensitiveCompare("application/x-dtbncx+xml") == .orderedSame
            })?.href
        return PackageInfo(manifest: manifest, navPath: navPath, ncxPath: ncxPath)
    }

    private static func parseNavigation(
        _ data: Data,
        documentPath: String,
        manifestPaths: Set<String>,
        format: UInt32
    ) throws -> [Link] {
        var events: [IosChapterCoreXmlEvent] = []
        try parseXML(
            data,
            onStart: { name, attributes in
                let rawTarget = attributes["href"] ?? attributes["src"]
                let target = rawTarget.flatMap {
                    resolveTarget(documentPath: documentPath, raw: $0, known: manifestPaths)
                }
                events.append(IosChapterCoreXmlEvent(
                    kind: UInt32(ERMAO_CHAPTER_XML_START),
                    name: name,
                    text: nil,
                    attributes: attributes.map {
                        IosChapterCoreXmlAttribute(name: $0.key, value: $0.value)
                    },
                    href: target
                ))
            },
            onText: { text in
                guard !text.isEmpty else { return }
                events.append(IosChapterCoreXmlEvent(
                    kind: UInt32(ERMAO_CHAPTER_XML_TEXT),
                    name: nil,
                    text: text,
                    attributes: [],
                    href: nil
                ))
            },
            onEnd: { name in
                events.append(IosChapterCoreXmlEvent(
                    kind: UInt32(ERMAO_CHAPTER_XML_END),
                    name: name,
                    text: nil,
                    attributes: [],
                    href: nil
                ))
            }
        )
        if format == UInt32(ERMAO_CHAPTER_EPUB_NAV),
           events.first(where: { $0.kind == UInt32(ERMAO_CHAPTER_XML_START) })?.name != "html"
        {
            return []
        }
        let result = try IosChapterCore.parseXML(format: format, events: events)
        return result.toLinks()
    }

    private static func parseXML(
        _ data: Data,
        onStart: @escaping (String, [String: String]) -> Void,
        onText: @escaping (String) -> Void = { _ in },
        onEnd: @escaping (String) -> Void = { _ in }
    ) throws {
        let delegate = XMLProjectionDelegate(onStart: onStart, onText: onText, onEnd: onEnd)
        let parser = XMLParser(data: data)
        parser.shouldProcessNamespaces = true
        parser.shouldReportNamespacePrefixes = true
        parser.shouldResolveExternalEntities = false
        parser.externalEntityResolvingPolicy = .never
        parser.delegate = delegate
        guard parser.parse(), delegate.failure == nil else {
            throw IosEpubChapterProjectionError.invalidXML
        }
    }

    private static func resolvePath(
        basePath: String,
        raw: String,
        available: Set<String>
    ) -> String? {
        guard let resolved = resolveURL(basePath: basePath, raw: raw),
              let path = IosEpubArchiveSafetyPreflight.canonicalArchivePath(
                  resolved.removingQuery().removingFragment().path
              ),
              available.contains(path)
        else { return nil }
        return path
    }

    private static func resolveTarget(
        documentPath: String,
        raw: String,
        known: Set<String>
    ) -> String? {
        let basePath = documentPath.split(separator: "/", omittingEmptySubsequences: true)
            .dropLast()
            .joined(separator: "/")
        let documentName = documentPath.split(separator: "/", omittingEmptySubsequences: true)
            .last.map(String.init) ?? documentPath
        let href = raw.hasPrefix("#") ? documentName + raw : raw
        guard let resolved = resolveURL(basePath: basePath, raw: href),
              let path = IosEpubArchiveSafetyPreflight.canonicalArchivePath(
                  resolved.removingQuery().removingFragment().path
              ),
              known.contains(path)
        else { return nil }
        let fragment = resolved.fragment?.isEmpty == false ? resolved.fragment : nil
        return fragment.map { "\(path)#\($0)" } ?? path
    }

    private static func resolveURL(basePath: String, raw: String) -> AnyURL? {
        guard URL(string: raw)?.scheme == nil else { return nil }
        guard let relative = RelativeURL(epubHREF: raw) else { return nil }
        if basePath.isEmpty {
            return relative.anyURL.normalized
        }
        guard let base = AnyURL(path: "\(basePath)/") else { return nil }
        return base.resolve(relative)?.normalized
    }

    private static func localName(_ value: String) -> String {
        value.split(separator: ":").last.map(String.init) ?? value
    }

    private static func normalizedAttributes(_ values: [String: String]) -> [String: String] {
        var attributes: [String: String] = [:]
        for (key, value) in values {
            attributes[localName(key)] = value
        }
        return attributes
    }

    fileprivate static func toLink(_ entry: IosChapterCoreEntry, children: [Link]) -> Link {
        return Link(
            href: entry.href ?? "",
            mediaType: .xhtml,
            title: entry.title,
            properties: Properties(["shuku:navigationKey": .string(entry.key)]),
            children: children
        )
    }

    private final class XMLProjectionDelegate: NSObject, XMLParserDelegate {
        let onStart: (String, [String: String]) -> Void
        let onText: (String) -> Void
        let onEnd: (String) -> Void
        var failure: Error?

        init(
            onStart: @escaping (String, [String: String]) -> Void,
            onText: @escaping (String) -> Void,
            onEnd: @escaping (String) -> Void
        ) {
            self.onStart = onStart
            self.onText = onText
            self.onEnd = onEnd
        }

        func parser(
            _ parser: XMLParser,
            didStartElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?,
            attributes attributeDict: [String: String] = [:]
        ) {
            guard failure == nil else { return }
            onStart(
                IosEpubChapterProjection.localName(elementName),
                IosEpubChapterProjection.normalizedAttributes(attributeDict)
            )
        }

        func parser(_ parser: XMLParser, foundCharacters string: String) {
            guard failure == nil else { return }
            onText(string)
        }

        func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
            guard failure == nil,
                  let text = String(data: CDATABlock, encoding: .utf8)
            else { return }
            onText(text)
        }

        func parser(
            _ parser: XMLParser,
            didEndElement elementName: String,
            namespaceURI: String?,
            qualifiedName qName: String?
        ) {
            guard failure == nil else { return }
            onEnd(IosEpubChapterProjection.localName(elementName))
        }

        func parser(_ parser: XMLParser, parseErrorOccurred parseError: Error) {
            failure = parseError
        }

        func parser(
            _ parser: XMLParser,
            validationErrorOccurred validationError: Error
        ) {
            failure = validationError
        }

        func parser(
            _ parser: XMLParser,
            resolveExternalEntityName name: String,
            systemID: String?
        ) -> Data? {
            nil
        }
    }
}

private enum IosEpubChapterProjectionError: Error {
    case invalidXML
}

private extension IosChapterCoreResult {
    func toLinks() -> [Link] {
        let childrenByParent = Dictionary(grouping: entries.indices) { entries[$0].parentIndex }

        func make(_ index: Int) -> Link {
            let children = (childrenByParent[index] ?? []).map(make)
            return IosEpubChapterProjection.toLink(entries[index], children: children)
        }

        return (childrenByParent[nil] ?? []).map(make)
    }
}
