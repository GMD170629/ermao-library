import CLibMobi
import Foundation

actor NativeMobiExtractor: MobiExtracting {
    static var libmobiVersion: String {
        String(cString: shuku_mobi_version())
    }

    func extract(_ file: URL) async throws -> MobiExtractedBook {
        guard FileManager.default.fileExists(atPath: file.path) else {
            throw MobiExtractionError.fileNotFound
        }
        guard file.isFileURL, FileManager.default.isReadableFile(atPath: file.path) else {
            throw MobiExtractionError.unreadableFile
        }

        var bridgeBook: UnsafeMutablePointer<ShukuMobiBook>?
        var bridgeError: UnsafeMutablePointer<CChar>?
        let result = file.path.withCString { path in
            shuku_mobi_extract_path(path, &bridgeBook, &bridgeError)
        }
        defer {
            if let bridgeBook {
                shuku_mobi_free_book(bridgeBook)
            }
            if let bridgeError {
                shuku_mobi_free_error(bridgeError)
            }
        }

        guard result == SHUKU_MOBI_BRIDGE_SUCCESS, let bridgeBook else {
            throw mapBridgeError(result, message: bridgeError.map { String(cString: $0) })
        }

        return try makeBook(from: bridgeBook.pointee, fallbackTitle: file.deletingPathExtension().lastPathComponent)
    }

    private func makeBook(from bridge: ShukuMobiBook, fallbackTitle: String) throws -> MobiExtractedBook {
        var resources: [MobiResource] = []
        var seenPaths: Set<String> = []
        resources.reserveCapacity(bridge.part_count)

        if let parts = bridge.parts {
            for index in 0 ..< bridge.part_count {
                let part = parts.advanced(by: index).pointee
                guard let rawName = part.name.map({ String(cString: $0) }),
                      let href = PublicationPath.normalizedResourcePath(rawName)
                else {
                    throw MobiExtractionError.invalidResourcePath(part.name.map { String(cString: $0) } ?? "")
                }
                guard seenPaths.insert(href).inserted else {
                    throw MobiExtractionError.duplicateResourcePath(href)
                }

                let mediaType = normalizedMediaType(
                    part.media_type.map { String(cString: $0) },
                    filename: href
                )
                let data: Data
                if part.length == 0 {
                    data = Data()
                } else if let bytes = part.bytes {
                    data = Data(bytes: bytes, count: part.length)
                } else {
                    throw MobiExtractionError.corruptContainer
                }
                resources.append(MobiResource(
                    uid: part.uid,
                    href: href,
                    mediaType: mediaType,
                    category: category(for: part.category),
                    data: data
                ))
            }
        }

        let markup = resources.filter { $0.category == .markup && $0.isHTML }
        guard !markup.isEmpty else {
            throw MobiExtractionError.noMarkup
        }

        var warnings: [MobiWarning] = []
        let opf = resources.first { $0.mediaType == "application/oebps-package+xml" }
        let package = opf.flatMap { resource -> OPFPackage? in
            do {
                return try OPFPackageParser().parse(resource.data)
            } catch {
                warnings.append(MobiWarning(code: .invalidOPF, message: String(describing: error)))
                return nil
            }
        }
        if opf == nil {
            warnings.append(MobiWarning(code: .missingOPF, message: "libmobi did not reconstruct an OPF package"))
        }

        let resourcesByHREF = Dictionary(uniqueKeysWithValues: resources.map { ($0.href, $0) })
        var readingOrder: [MobiResource]
        if let package {
            readingOrder = package.readingOrderHREFs.compactMap { rawHREF in
                guard let href = PublicationPath.normalizedResourcePath(rawHREF) else { return nil }
                return resourcesByHREF[href]
            }.filter(\.isHTML)
            if readingOrder.isEmpty {
                warnings.append(MobiWarning(code: .readingOrderFallback, message: "OPF spine did not resolve to HTML resources"))
                readingOrder = markup
            }
        } else {
            warnings.append(MobiWarning(code: .readingOrderFallback, message: "Using libmobi markup order because OPF is unavailable"))
            readingOrder = markup
        }

        let ncx = resources.first { $0.mediaType == "application/x-dtbncx+xml" }
        let tableOfContents: [MobiNavigationItem]
        if let ncx {
            do {
                tableOfContents = try NCXNavigationParser().parse(ncx.data)
            } catch {
                tableOfContents = []
                warnings.append(MobiWarning(code: .invalidNCX, message: String(describing: error)))
            }
        } else {
            tableOfContents = []
            warnings.append(MobiWarning(code: .missingNCX, message: "libmobi did not reconstruct an NCX table of contents"))
        }

        let readingOrderPaths = Set(readingOrder.map(\.href))
        for item in tableOfContents.flattened where
            PublicationPath.resourcePath(from: item.href).map({ !readingOrderPaths.contains($0) }) ?? true
        {
            warnings.append(MobiWarning(code: .unresolvedTOCTarget, message: item.href))
        }

        let progression = package?.progression ?? progressionFromMarkup(resources)
        let metadata = MobiMetadata(
            title: normalizedString(bridge.title) ?? fallbackTitle,
            author: normalizedString(bridge.author),
            language: normalizedString(bridge.language),
            description: normalizedString(bridge.description_text),
            readingProgression: progression
        )

        let readingOrderSet = Set(readingOrder.map(\.href))
        return MobiExtractedBook(
            format: format(for: bridge.format),
            metadata: metadata,
            readingOrder: readingOrder,
            resources: resources.filter { !readingOrderSet.contains($0.href) },
            tableOfContents: tableOfContents,
            warnings: warnings
        )
    }

    private func mapBridgeError(_ result: ShukuMobiBridgeResult, message: String?) -> MobiExtractionError {
        switch result {
        case SHUKU_MOBI_BRIDGE_INVALID_ARGUMENT:
            return .unreadableFile
        case SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY:
            return .outOfMemory
        case SHUKU_MOBI_BRIDGE_ENCRYPTED:
            return .encrypted
        case SHUKU_MOBI_BRIDGE_UNSUPPORTED:
            return .unsupportedFormat
        case SHUKU_MOBI_BRIDGE_CORRUPT:
            return .corruptContainer
        case SHUKU_MOBI_BRIDGE_NO_MARKUP:
            return .noMarkup
        default:
            return .libmobi(code: Int(result.rawValue), message: message ?? "Unknown libmobi failure")
        }
    }

    private func format(for value: ShukuMobiFormat) -> MobiFormat {
        switch value {
        case SHUKU_MOBI_FORMAT_KF8:
            .kf8
        case SHUKU_MOBI_FORMAT_HYBRID:
            .hybrid
        default:
            .mobi6
        }
    }

    private func category(for value: ShukuMobiPartCategory) -> MobiResourceCategory {
        switch value {
        case SHUKU_MOBI_PART_FLOW:
            .flow
        case SHUKU_MOBI_PART_RESOURCE:
            .resource
        default:
            .markup
        }
    }

    private func normalizedString(_ value: UnsafeMutablePointer<CChar>?) -> String? {
        guard let value else { return nil }
        let string = String(cString: value).trimmingCharacters(in: .whitespacesAndNewlines)
        return string.isEmpty ? nil : string
    }

    private func normalizedMediaType(_ rawValue: String?, filename: String) -> String {
        if let rawValue, rawValue.contains("/") {
            return rawValue
        }
        return switch URL(fileURLWithPath: filename).pathExtension.lowercased() {
        case "html", "htm": "text/html"
        case "xhtml": "application/xhtml+xml"
        case "css": "text/css"
        case "opf": "application/oebps-package+xml"
        case "ncx": "application/x-dtbncx+xml"
        case "jpg", "jpeg": "image/jpeg"
        case "png": "image/png"
        case "gif": "image/gif"
        case "svg": "image/svg+xml"
        case "ttf": "font/ttf"
        case "otf": "font/otf"
        default: "application/octet-stream"
        }
    }

    private func progressionFromMarkup(_ resources: [MobiResource]) -> MobiReadingProgression {
        let sample = resources
            .filter { $0.isHTML || $0.mediaType == "text/css" }
            .prefix(8)
            .compactMap { String(data: $0.data, encoding: .utf8) }
            .joined(separator: "\n")
            .lowercased()
        if sample.contains("writing-mode: vertical-rl") || sample.contains("writing-mode:vertical-rl") {
            return .rightToLeft
        }
        return .leftToRight
    }
}
