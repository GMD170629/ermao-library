import Foundation
import ErmaoChapterCore

struct IosChapterCoreEntry: Sendable {
    let index: Int
    let parentIndex: Int?
    let navigable: Bool
    let key: String
    let title: String
    let href: String?
    let sourceStart: UInt64
    let sourceEnd: UInt64
    let contentStart: UInt64
}

struct IosChapterCoreResult: Sendable {
    let entries: [IosChapterCoreEntry]
    let text: String
}

struct IosChapterCoreXmlAttribute: Sendable {
    let name: String
    let value: String
}

struct IosChapterCoreXmlEvent: Sendable {
    let kind: UInt32
    let name: String?
    let text: String?
    let attributes: [IosChapterCoreXmlAttribute]
    let href: String?
}

struct IosChapterCoreMobiNode: Sendable {
    let parentIndex: Int?
    let title: String
    let href: String?
}

enum IosChapterCore {
    static func parseTXT(_ text: String) throws -> IosChapterCoreResult {
        let input = Data(text.utf8)
        var result: OpaquePointer?
        let status = input.withUnsafeBytes { rawBuffer -> ErmaoChapterStatus in
            let bytes = rawBuffer.bindMemory(to: UInt8.self)
            return ermao_chapters_parse_txt(
                bytes.baseAddress,
                UInt64(bytes.count),
                &result
            )
        }
        try requireSuccess(status)
        return try consume(result)
    }

    static func parseMobi(nodes: [IosChapterCoreMobiNode]) throws -> IosChapterCoreResult {
        guard nodes.count <= Int(UInt32.max) else {
            throw IosChapterCoreError.invalidInput
        }
        var nativeNodes: [ErmaoChapterMobiNode] = []
        nativeNodes.reserveCapacity(nodes.count)
        var ownedStrings: [UnsafeMutablePointer<CChar>] = []
        defer {
            for pointer in ownedStrings {
                pointer.deinitialize(count: 1)
                pointer.deallocate()
            }
        }
        for node in nodes {
            if let parentIndex = node.parentIndex {
                guard parentIndex >= Int(Int32.min), parentIndex <= Int(Int32.max) else {
                    throw IosChapterCoreError.invalidInput
                }
            }
            let title = try copyCString(node.title, owned: &ownedStrings)
            let href = try copyCString(node.href, owned: &ownedStrings)
            nativeNodes.append(ErmaoChapterMobiNode(
                parent_index: Int32(node.parentIndex ?? -1),
                title: title,
                target_href: href
            ))
        }
        var result: OpaquePointer?
        let status = nativeNodes.withUnsafeBufferPointer { buffer in
            ermao_chapters_from_mobi(
                buffer.baseAddress,
                UInt32(buffer.count),
                &result
            )
        }
        try requireSuccess(status)
        return try consume(result)
    }

    static func parseXML(format: UInt32, events: [IosChapterCoreXmlEvent]) throws -> IosChapterCoreResult {
        guard format >= UInt32(ERMAO_CHAPTER_EPUB_NAV), format <= UInt32(ERMAO_CHAPTER_FB2) else {
            throw IosChapterCoreError.invalidInput
        }
        guard events.count <= Int(UInt32.max) else {
            throw IosChapterCoreError.invalidInput
        }
        var nativeEvents: [ErmaoChapterXmlEvent] = []
        nativeEvents.reserveCapacity(events.count)
        var ownedStrings: [UnsafeMutablePointer<CChar>] = []
        var ownedAttributes: [(pointer: UnsafeMutablePointer<ErmaoChapterAttribute>, count: Int)] = []
        defer {
            for allocation in ownedAttributes {
                allocation.pointer.deinitialize(count: allocation.count)
                allocation.pointer.deallocate()
            }
            for pointer in ownedStrings {
                pointer.deinitialize(count: 1)
                pointer.deallocate()
            }
        }
        for event in events {
            let name = try copyCString(event.name, owned: &ownedStrings)
            let text = try copyCString(event.text, owned: &ownedStrings)
            let href = try copyCString(event.href, owned: &ownedStrings)
            guard event.attributes.count <= Int(UInt32.max) else {
                throw IosChapterCoreError.invalidInput
            }
            var attributePointer: UnsafeMutablePointer<ErmaoChapterAttribute>?
            if event.attributes.isEmpty {
                attributePointer = nil
            } else {
                let allocated = UnsafeMutablePointer<ErmaoChapterAttribute>.allocate(
                    capacity: event.attributes.count
                )
                ownedAttributes.append((pointer: allocated, count: event.attributes.count))
                for (index, attribute) in event.attributes.enumerated() {
                    let attributeName = try copyCString(attribute.name, owned: &ownedStrings)
                    let attributeValue = try copyCString(attribute.value, owned: &ownedStrings)
                    allocated.advanced(by: index).initialize(
                        to: ErmaoChapterAttribute(name: attributeName, value: attributeValue)
                    )
                }
                attributePointer = allocated
            }
            nativeEvents.append(ErmaoChapterXmlEvent(
                kind: event.kind,
                name: name,
                text: text,
                attributes: attributePointer,
                attribute_count: UInt32(event.attributes.count),
                target_href: href
            ))
        }
        var result: OpaquePointer?
        let status = nativeEvents.withUnsafeBufferPointer { buffer in
            ermao_chapters_parse_xml(
                format,
                buffer.baseAddress,
                UInt32(buffer.count),
                &result
            )
        }
        try requireSuccess(status)
        return try consume(result)
    }

    private static func consume(_ result: OpaquePointer?) throws -> IosChapterCoreResult {
        guard let result else { throw IosChapterCoreError.invalidResult }
        defer { ermao_chapters_free(result) }
        let count = Int(ermao_chapters_count(result))
        let entries = try (0 ..< count).map { index -> IosChapterCoreEntry in
            guard let entryPointer = ermao_chapters_entry(result, UInt32(index)) else {
                throw IosChapterCoreError.invalidResult
            }
            let entry = entryPointer.pointee
            guard let key = entry.key.map({ String(cString: $0) }),
                  let title = entry.title.map({ String(cString: $0) })
            else { throw IosChapterCoreError.invalidResult }
            return IosChapterCoreEntry(
                index: Int(entry.index),
                parentIndex: entry.parent_index >= 0 ? Int(entry.parent_index) : nil,
                navigable: entry.navigable != 0,
                key: key,
                title: title,
                href: entry.href.map { String(cString: $0) },
                sourceStart: entry.source_start,
                sourceEnd: entry.source_end,
                contentStart: entry.content_start
            )
        }
        let textBytes = ermao_chapters_text(result)
        let textLength = Int(ermao_chapters_text_length(result))
        let text = textBytes.map { String(decoding: UnsafeBufferPointer(start: $0, count: textLength), as: UTF8.self) } ?? ""
        return IosChapterCoreResult(entries: entries, text: text)
    }

    private static func copyCString(
        _ value: String?,
        owned: inout [UnsafeMutablePointer<CChar>]
    ) throws -> UnsafePointer<CChar>? {
        guard let value else { return nil }
        let pointer = UnsafeMutablePointer<CChar>.allocate(capacity: value.utf8.count + 1)
        value.withCString { source in
            pointer.initialize(from: source, count: value.utf8.count + 1)
        }
        owned.append(pointer)
        return UnsafePointer(pointer)
    }

    private static func requireSuccess(_ status: ErmaoChapterStatus) throws {
        switch status {
        case ERMAO_CHAPTER_OK:
            return
        case ERMAO_CHAPTER_OUT_OF_MEMORY:
            throw IosChapterCoreError.outOfMemory
        default:
            throw IosChapterCoreError.invalidInput
        }
    }
}

enum IosChapterCoreError: Error, Sendable {
    case invalidInput
    case outOfMemory
    case invalidResult
}
