import CLibMobi
import Foundation

enum IosMobiCoreStatus: Int32, Sendable {
    case invalidArgument = 1
    case fileNotFound = 2
    case io = 3
    case unsupported = 4
    case drmProtected = 5
    case corrupt = 6
    case parseFailed = 7
    case noContent = 8
    case limitExceeded = 9
    case outOfMemory = 10
    case notFound = 11
    case outOfRange = 12
    case bufferTooSmall = 13
    case internalFailure = 14
}

struct IosMobiCoreError: Error, Equatable, Sendable {
    let status: IosMobiCoreStatus

    init(_ rawStatus: ErmaoMobiStatus) {
        status = IosMobiCoreStatus(rawValue: Int32(rawStatus.rawValue)) ?? .internalFailure
    }
}

enum IosMobiFormat: Int32, Sendable {
    case mobi6 = 1
    case kf8 = 2
    case hybridKf8 = 3
    case hybridMobi6Fallback = 4
}

enum IosMobiReadingDirection: Int32, Sendable {
    case unknown = 0
    case leftToRight = 1
    case rightToLeft = 2
}

enum IosMobiResourceCategory: Int32, Sendable {
    case markup = 1
    case flow = 2
    case asset = 3
}

enum IosMobiMetadataField: Int32, CaseIterable, Sendable {
    case title = 1
    case author = 2
    case publisher = 3
    case language = 4
    case asin = 5
    case isbn = 6
    case description = 7
}

struct IosMobiBookInfo: Equatable, Sendable {
    let format: IosMobiFormat
    let readingDirection: IosMobiReadingDirection
    let resourceCount: Int
    let readingOrderCount: Int
    let tocCount: Int
    let warningCount: Int
    let coverResourceIndex: Int?
}

struct IosMobiResourceInfo: Equatable, Sendable {
    let category: IosMobiResourceCategory
    let sourceUID: UInt64
    let decodedLength: UInt64
    let sourceName: String
    let mediaType: String
}

struct IosMobiTocInfo: Equatable, Sendable {
    let parentIndex: Int?
    let targetResourceIndex: Int?
    let title: String?
    let fragment: String?
}

struct IosMobiWarning: Equatable, Sendable {
    let code: UInt32
    let relatedIndex: Int?
}

actor IosMobiBook {
    static let abiVersion = 1
    static let maximumReadBytes = 256 * 1024
    static var parserIdentifier: String {
        String(cString: ermao_mobi_parser_identifier())
    }
    static var normalizationIdentifier: String {
        String(cString: ermao_mobi_normalization_identifier())
    }
    private static let noIndex = UInt32.max

    private nonisolated(unsafe) var handle: OpaquePointer?

    private init(handle: OpaquePointer) {
        self.handle = handle
    }

    deinit {
        var closingHandle = handle
        ermao_mobi_close(&closingHandle)
    }

    static func open(fileURL: URL) throws -> IosMobiBook {
        guard fileURL.isFileURL else {
            throw IosMobiCoreError(ERMAO_MOBI_INVALID_ARGUMENT)
        }
        var openedHandle: OpaquePointer?
        let status = fileURL.path.withCString { path in
            ermao_mobi_open(path, nil, &openedHandle)
        }
        try requireSuccess(status)
        guard let openedHandle else {
            throw IosMobiCoreError(ERMAO_MOBI_INTERNAL)
        }
        guard ermao_mobi_abi_version() == abiVersion else {
            var closingHandle: OpaquePointer? = openedHandle
            ermao_mobi_close(&closingHandle)
            throw IosMobiCoreError(ERMAO_MOBI_INTERNAL)
        }
        return IosMobiBook(handle: openedHandle)
    }

    func info() throws -> IosMobiBookInfo {
        var value = ErmaoMobiBookInfo()
        value.struct_size = UInt32(MemoryLayout<ErmaoMobiBookInfo>.size)
        try Self.requireSuccess(ermao_mobi_get_book_info(try requireOpen(), &value))
        guard let format = IosMobiFormat(rawValue: Int32(value.format)),
              let direction = IosMobiReadingDirection(rawValue: Int32(value.reading_direction))
        else {
            throw IosMobiCoreError(ERMAO_MOBI_INTERNAL)
        }
        return IosMobiBookInfo(
            format: format,
            readingDirection: direction,
            resourceCount: Int(value.resource_count),
            readingOrderCount: Int(value.reading_order_count),
            tocCount: Int(value.toc_count),
            warningCount: Int(value.warning_count),
            coverResourceIndex: Self.optionalIndex(value.cover_resource_index)
        )
    }

    func metadata(_ field: IosMobiMetadataField) throws -> String? {
        let currentHandle = try requireOpen()
        return try Self.copyString { buffer, capacity, required in
            ermao_mobi_copy_metadata(
                currentHandle,
                Self.coreMetadataField(field),
                buffer,
                capacity,
                required
            )
        }
    }

    func resource(at index: Int) throws -> IosMobiResourceInfo {
        let resourceIndex = try Self.checkedIndex(index)
        let currentHandle = try requireOpen()
        var value = ErmaoMobiResourceInfo()
        value.struct_size = UInt32(MemoryLayout<ErmaoMobiResourceInfo>.size)
        try Self.requireSuccess(ermao_mobi_get_resource_info(currentHandle, resourceIndex, &value))
        guard let category = IosMobiResourceCategory(rawValue: Int32(value.category)),
              let sourceName = try Self.copyString({ buffer, capacity, required in
                  ermao_mobi_copy_resource_source_name(
                      currentHandle,
                      resourceIndex,
                      buffer,
                      capacity,
                      required
                  )
              }),
              let mediaType = try Self.copyString({ buffer, capacity, required in
                  ermao_mobi_copy_resource_media_type(
                      currentHandle,
                      resourceIndex,
                      buffer,
                      capacity,
                      required
                  )
              })
        else {
            throw IosMobiCoreError(ERMAO_MOBI_INTERNAL)
        }
        return IosMobiResourceInfo(
            category: category,
            sourceUID: value.source_uid,
            decodedLength: value.decoded_length,
            sourceName: sourceName,
            mediaType: mediaType
        )
    }

    func readResource(
        at index: Int,
        offset: UInt64,
        length: Int
    ) throws -> Data {
        guard length >= 0, length <= Self.maximumReadBytes else {
            throw IosMobiCoreError(ERMAO_MOBI_LIMIT_EXCEEDED)
        }
        let resourceIndex = try Self.checkedIndex(index)
        let currentHandle = try requireOpen()
        var bytes = [UInt8](repeating: 0, count: length)
        var bytesRead: UInt32 = 0
        let status = bytes.withUnsafeMutableBufferPointer { buffer in
            ermao_mobi_read_resource(
                currentHandle,
                resourceIndex,
                offset,
                buffer.baseAddress,
                UInt32(length),
                &bytesRead
            )
        }
        try Self.requireSuccess(status)
        return Data(bytes.prefix(Int(bytesRead)))
    }

    func readingOrderResourceIndex(at position: Int) throws -> Int {
        let checkedPosition = try Self.checkedIndex(position)
        var resourceIndex: UInt32 = 0
        try Self.requireSuccess(
            ermao_mobi_reading_order_resource_index(
                try requireOpen(),
                checkedPosition,
                &resourceIndex
            )
        )
        return Int(resourceIndex)
    }

    func toc(at index: Int) throws -> IosMobiTocInfo {
        let tocIndex = try Self.checkedIndex(index)
        let currentHandle = try requireOpen()
        var value = ErmaoMobiTocInfo()
        value.struct_size = UInt32(MemoryLayout<ErmaoMobiTocInfo>.size)
        try Self.requireSuccess(ermao_mobi_get_toc_info(currentHandle, tocIndex, &value))
        let title = try Self.copyString { buffer, capacity, required in
            ermao_mobi_copy_toc_title(currentHandle, tocIndex, buffer, capacity, required)
        }
        let fragment = try Self.copyString { buffer, capacity, required in
            ermao_mobi_copy_toc_fragment(currentHandle, tocIndex, buffer, capacity, required)
        }
        return IosMobiTocInfo(
            parentIndex: Self.optionalIndex(value.parent_index),
            targetResourceIndex: Self.optionalIndex(value.target_resource_index),
            title: title,
            fragment: fragment
        )
    }

    func warning(at index: Int) throws -> IosMobiWarning {
        let warningIndex = try Self.checkedIndex(index)
        var value = ErmaoMobiWarningInfo()
        value.struct_size = UInt32(MemoryLayout<ErmaoMobiWarningInfo>.size)
        try Self.requireSuccess(
            ermao_mobi_get_warning_info(try requireOpen(), warningIndex, &value)
        )
        return IosMobiWarning(
            code: value.code,
            relatedIndex: Self.optionalIndex(value.related_index)
        )
    }

    func close() {
        guard handle != nil else { return }
        ermao_mobi_close(&handle)
    }

    private func requireOpen() throws -> OpaquePointer {
        guard let handle else {
            throw IosMobiCoreError(ERMAO_MOBI_INVALID_ARGUMENT)
        }
        return handle
    }

    private static func checkedIndex(_ index: Int) throws -> UInt32 {
        guard index >= 0, let checked = UInt32(exactly: index) else {
            throw IosMobiCoreError(ERMAO_MOBI_OUT_OF_RANGE)
        }
        return checked
    }

    private static func optionalIndex(_ index: UInt32) -> Int? {
        index == noIndex ? nil : Int(index)
    }

    private static func coreMetadataField(
        _ field: IosMobiMetadataField
    ) -> ErmaoMobiMetadataField {
        switch field {
        case .title:
            ERMAO_MOBI_METADATA_TITLE
        case .author:
            ERMAO_MOBI_METADATA_AUTHOR
        case .publisher:
            ERMAO_MOBI_METADATA_PUBLISHER
        case .language:
            ERMAO_MOBI_METADATA_LANGUAGE
        case .asin:
            ERMAO_MOBI_METADATA_ASIN
        case .isbn:
            ERMAO_MOBI_METADATA_ISBN
        case .description:
            ERMAO_MOBI_METADATA_DESCRIPTION
        }
    }

    private static func requireSuccess(_ status: ErmaoMobiStatus) throws {
        guard status == ERMAO_MOBI_OK else {
            throw IosMobiCoreError(status)
        }
    }

    private static func copyString(
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
            throw IosMobiCoreError(queryStatus)
        }
        var buffer = [CChar](repeating: 0, count: Int(required))
        let copyStatus = buffer.withUnsafeMutableBufferPointer { pointer in
            operation(pointer.baseAddress, required, &required)
        }
        try requireSuccess(copyStatus)
        return buffer.withUnsafeBufferPointer { pointer in
            guard let baseAddress = pointer.baseAddress else { return nil }
            return String(cString: baseAddress)
        }
    }
}
