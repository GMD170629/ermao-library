import CLibMobi
import Foundation

actor NativeMobiExtractor: MobiExtracting {
    static var libmobiVersion: String {
        String(cString: ermao_mobi_parser_identifier())
    }

    func extract(_ file: URL) async throws -> MobiExtractedBook {
        guard FileManager.default.fileExists(atPath: file.path) else {
            throw MobiExtractionError.fileNotFound
        }
        guard file.isFileURL, FileManager.default.isReadableFile(atPath: file.path) else {
            throw MobiExtractionError.unreadableFile
        }

        var handle: OpaquePointer?
        let openStatus = file.path.withCString { path in
            ermao_mobi_open(path, nil, &handle)
        }
        defer {
            ermao_mobi_close(&handle)
        }
        guard openStatus == ERMAO_MOBI_OK, let handle else {
            throw mapCoreError(openStatus)
        }

        var bookInfo = ErmaoMobiBookInfo()
        bookInfo.struct_size = UInt32(MemoryLayout<ErmaoMobiBookInfo>.size)
        let infoStatus = ermao_mobi_get_book_info(handle, &bookInfo)
        guard infoStatus == ERMAO_MOBI_OK else {
            throw mapCoreError(infoStatus)
        }

        var resources: [MobiResource] = []
        var seenPaths: Set<String> = []
        resources.reserveCapacity(Int(bookInfo.resource_count))
        for index in 0 ..< bookInfo.resource_count {
            var resourceInfo = ErmaoMobiResourceInfo()
            resourceInfo.struct_size = UInt32(MemoryLayout<ErmaoMobiResourceInfo>.size)
            let resourceStatus = ermao_mobi_get_resource_info(handle, index, &resourceInfo)
            guard resourceStatus == ERMAO_MOBI_OK else {
                throw mapCoreError(resourceStatus)
            }
            guard let rawName = try copyString({ buffer, capacity, required in
                ermao_mobi_copy_resource_source_name(handle, index, buffer, capacity, required)
            }), let href = PublicationPath.normalizedResourcePath(rawName) else {
                throw MobiExtractionError.invalidResourcePath("")
            }
            guard seenPaths.insert(href).inserted else {
                throw MobiExtractionError.duplicateResourcePath(href)
            }
            let mediaType = try copyString { buffer, capacity, required in
                ermao_mobi_copy_resource_media_type(handle, index, buffer, capacity, required)
            } ?? "application/octet-stream"
            resources.append(MobiResource(
                uid: resourceInfo.source_uid,
                href: href,
                mediaType: mediaType,
                category: category(for: resourceInfo.category),
                data: try readResource(
                    handle: handle,
                    index: index,
                    length: resourceInfo.decoded_length
                )
            ))
        }

        let core = ExtractedCoreBook(
            format: format(for: bookInfo.format),
            title: try metadata(handle: handle, field: ERMAO_MOBI_METADATA_TITLE),
            author: try metadata(handle: handle, field: ERMAO_MOBI_METADATA_AUTHOR),
            language: try metadata(handle: handle, field: ERMAO_MOBI_METADATA_LANGUAGE),
            description: try metadata(handle: handle, field: ERMAO_MOBI_METADATA_DESCRIPTION),
            readingProgression: bookInfo.reading_direction == 2
                ? .rightToLeft
                : .leftToRight,
            resources: resources
        )
        return try makeBook(
            from: core,
            fallbackTitle: file.deletingPathExtension().lastPathComponent
        )
    }

    private func makeBook(from core: ExtractedCoreBook, fallbackTitle: String) throws -> MobiExtractedBook {
        let resources = core.resources
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

        let progression = package?.progression ?? core.readingProgression
        let metadata = MobiMetadata(
            title: core.title ?? fallbackTitle,
            author: core.author,
            language: core.language,
            description: core.description,
            readingProgression: progression
        )

        let readingOrderSet = Set(readingOrder.map(\.href))
        return MobiExtractedBook(
            format: core.format,
            metadata: metadata,
            readingOrder: readingOrder,
            resources: resources.filter { !readingOrderSet.contains($0.href) },
            tableOfContents: tableOfContents,
            warnings: warnings
        )
    }

    private func mapCoreError(_ result: ErmaoMobiStatus) -> MobiExtractionError {
        switch result {
        case ERMAO_MOBI_INVALID_ARGUMENT, ERMAO_MOBI_IO_ERROR:
            return .unreadableFile
        case ERMAO_MOBI_FILE_NOT_FOUND:
            return .fileNotFound
        case ERMAO_MOBI_OUT_OF_MEMORY:
            return .outOfMemory
        case ERMAO_MOBI_DRM_PROTECTED:
            return .encrypted
        case ERMAO_MOBI_UNSUPPORTED:
            return .unsupportedFormat
        case ERMAO_MOBI_CORRUPT, ERMAO_MOBI_PARSE_FAILED:
            return .corruptContainer
        case ERMAO_MOBI_NO_CONTENT:
            return .noMarkup
        default:
            return .libmobi(
                code: Int(result.rawValue),
                message: String(cString: ermao_mobi_status_name(result))
            )
        }
    }

    private func format(for value: UInt32) -> MobiFormat {
        switch value {
        case 2:
            .kf8
        case 3, 4:
            .hybrid
        default:
            .mobi6
        }
    }

    private func category(for value: UInt32) -> MobiResourceCategory {
        switch value {
        case 2:
            .flow
        case 3:
            .resource
        default:
            .markup
        }
    }

    private func metadata(
        handle: OpaquePointer,
        field: ErmaoMobiMetadataField
    ) throws -> String? {
        try copyString { buffer, capacity, required in
            ermao_mobi_copy_metadata(handle, field, buffer, capacity, required)
        }
    }

    private func copyString(
        _ operation: (
            UnsafeMutablePointer<CChar>?,
            UInt32,
            UnsafeMutablePointer<UInt32>
        ) -> ErmaoMobiStatus
    ) throws -> String? {
        var required: UInt32 = 0
        let queryStatus = operation(nil, 0, &required)
        if queryStatus == ERMAO_MOBI_NOT_FOUND {
            return nil
        }
        guard queryStatus == ERMAO_MOBI_BUFFER_TOO_SMALL, required > 0 else {
            throw mapCoreError(queryStatus)
        }
        var buffer = [CChar](repeating: 0, count: Int(required))
        let copyStatus = buffer.withUnsafeMutableBufferPointer { pointer in
            operation(pointer.baseAddress, required, &required)
        }
        guard copyStatus == ERMAO_MOBI_OK else {
            throw mapCoreError(copyStatus)
        }
        let value = buffer.withUnsafeBufferPointer { pointer in
            guard let baseAddress = pointer.baseAddress else { return nil }
            return String(cString: baseAddress)
        }?.trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value : nil
    }

    private func readResource(
        handle: OpaquePointer,
        index: UInt32,
        length: UInt64
    ) throws -> Data {
        guard let capacity = Int(exactly: length) else {
            throw MobiExtractionError.outOfMemory
        }
        var data = Data()
        data.reserveCapacity(capacity)
        var offset: UInt64 = 0
        while offset < length {
            let requested = Int(min(UInt64(ERMAO_MOBI_MAX_READ_BYTES), length - offset))
            var buffer = [UInt8](repeating: 0, count: requested)
            var bytesRead: UInt32 = 0
            let status = buffer.withUnsafeMutableBufferPointer { pointer in
                ermao_mobi_read_resource(
                    handle,
                    index,
                    offset,
                    pointer.baseAddress,
                    UInt32(requested),
                    &bytesRead
                )
            }
            guard status == ERMAO_MOBI_OK else {
                throw mapCoreError(status)
            }
            guard bytesRead > 0 else {
                throw MobiExtractionError.corruptContainer
            }
            data.append(contentsOf: buffer.prefix(Int(bytesRead)))
            offset += UInt64(bytesRead)
        }
        return data
    }
}

private struct ExtractedCoreBook {
    let format: MobiFormat
    let title: String?
    let author: String?
    let language: String?
    let description: String?
    let readingProgression: MobiReadingProgression
    let resources: [MobiResource]
}
