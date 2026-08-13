import Foundation
import XCTest
@testable import ErmaoLibrary

final class CbzPublicationTests: XCTestCase {
    func testBuildsCanonicalNaturalPageIndex() throws {
        let url = try makeArchive([
            Entry(name: "pages/10.png", bytes: Data([1])),
            Entry(name: "pages/2.jpg", bytes: Data([2])),
            Entry(name: "ComicInfo.xml", bytes: Data("<ComicInfo/>".utf8)),
        ])
        defer { try? FileManager.default.removeItem(at: url) }
        let index = try IosCbzArchiveIndex(fileURL: url)
        XCTAssertEqual(index.pages.map(\.resourceHref), ["pages/2.jpg", "pages/10.png"])
        XCTAssertEqual(index.pages.map(\.pageIndex), [0, 1])
        XCTAssertNoThrow(try index.requireCanonicalPages(index.pages))
        XCTAssertThrowsError(try index.requireCanonicalPages(Array(index.pages.reversed())))
    }

    func testRejectsTraversalDuplicateEncryptedAndSymlinkEntries() throws {
        for entries in [
            [Entry(name: "../page.jpg", bytes: Data([1]))],
            [Entry(name: "Page.jpg", bytes: Data([1])), Entry(name: "page.jpg", bytes: Data([2]))],
            [Entry(name: "page.jpg", bytes: Data([1]), flags: 1)],
            [Entry(name: "page.jpg", bytes: Data([1]), unixMode: 0xA000)],
        ] {
            let url = try makeArchive(entries)
            defer { try? FileManager.default.removeItem(at: url) }
            XCTAssertThrowsError(try IosCbzArchiveIndex(fileURL: url))
        }
    }

    func testRejectsArchiveWithoutSupportedImage() throws {
        let url = try makeArchive([Entry(name: "ComicInfo.xml", bytes: Data("<ComicInfo/>".utf8))])
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertThrowsError(try IosCbzArchiveIndex(fileURL: url))
    }

    private struct Entry {
        let name: String
        let bytes: Data
        var flags: UInt16 = 0x0800
        var unixMode: UInt16 = 0
    }

    private func makeArchive(_ entries: [Entry]) throws -> URL {
        var local = Data()
        var central = Data()
        for entry in entries {
            let name = Data(entry.name.utf8)
            let offset = UInt32(local.count)
            local.appendLE(UInt32(0x0403_4B50)); local.appendLE(UInt16(20)); local.appendLE(entry.flags)
            local.appendLE(UInt16(0)); local.appendLE(UInt16(0)); local.appendLE(UInt16(0)); local.appendLE(UInt32(0))
            local.appendLE(UInt32(entry.bytes.count)); local.appendLE(UInt32(entry.bytes.count))
            local.appendLE(UInt16(name.count)); local.appendLE(UInt16(0)); local.append(name); local.append(entry.bytes)

            central.appendLE(UInt32(0x0201_4B50)); central.appendLE(UInt16(0x0314)); central.appendLE(UInt16(20))
            central.appendLE(entry.flags); central.appendLE(UInt16(0)); central.appendLE(UInt16(0)); central.appendLE(UInt16(0))
            central.appendLE(UInt32(0)); central.appendLE(UInt32(entry.bytes.count)); central.appendLE(UInt32(entry.bytes.count))
            central.appendLE(UInt16(name.count)); central.appendLE(UInt16(0)); central.appendLE(UInt16(0))
            central.appendLE(UInt16(0)); central.appendLE(UInt16(0)); central.appendLE(UInt32(entry.unixMode) << 16)
            central.appendLE(offset); central.append(name)
        }
        var data = local
        let centralOffset = UInt32(data.count)
        data.append(central)
        data.appendLE(UInt32(0x0605_4B50)); data.appendLE(UInt16(0)); data.appendLE(UInt16(0))
        data.appendLE(UInt16(entries.count)); data.appendLE(UInt16(entries.count))
        data.appendLE(UInt32(central.count)); data.appendLE(centralOffset); data.appendLE(UInt16(0))
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathExtension("cbz")
        try data.write(to: url)
        return url
    }
}

private extension Data {
    mutating func appendLE<T: FixedWidthInteger>(_ value: T) {
        var little = value.littleEndian
        Swift.withUnsafeBytes(of: &little) { append(contentsOf: $0) }
    }
}
