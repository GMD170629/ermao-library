import CryptoKit
import Foundation
import XCTest
@testable import ErmaoLibrary

final class MobiCoreTests: XCTestCase {
    func testHostAndIosProduceIdenticalAbiV1GoldenSnapshotsOnPhysicalDevice() async throws {
#if targetEnvironment(simulator)
        XCTFail("R5 iOS snapshot evidence must run on a physical iOS device")
#else
        for fixtureBaseName in ["01-basic-mobi6", "11-upstream-huff-cdic"] {
            let fixtureURL = try XCTUnwrap(
                Bundle(for: Self.self).url(forResource: fixtureBaseName, withExtension: "mobi")
            )
            let goldenURL = try XCTUnwrap(
                Bundle(for: Self.self).url(
                    forResource: "\(fixtureBaseName).abi-v1",
                    withExtension: "snapshot"
                )
            )
            let expected = try String(contentsOf: goldenURL, encoding: .utf8)
            let book = try IosMobiBook.open(fileURL: fixtureURL)
            let actual = try await snapshot(book)
            await book.close()
            XCTAssertEqual(actual, expected, fixtureBaseName)
        }
#endif
    }

    func testCorpusOpenQueryChunkReadAndCloseOnPhysicalDevice() async throws {
#if targetEnvironment(simulator)
        XCTFail("R5 iOS runtime evidence must run on a physical iOS device")
#else
        let fixtures: [(name: String, fileExtension: String)] = [
            ("01-basic-mobi6", "mobi"),
            ("test", "azw3"),
            ("03-css", "azw3"),
            ("04-font", "azw3"),
            ("05-images", "azw3"),
            ("06-footnotes", "azw3"),
            ("07-complex-toc", "azw3"),
            ("08-zh-hans", "azw3"),
            ("09-ja-vertical", "azw3"),
            ("10-long-chapter", "azw3"),
            ("11-upstream-huff-cdic", "mobi"),
            ("12-basic", "prc"),
            ("13-basic", "azw"),
        ]

        for fixture in fixtures {
            let fixtureURL = try XCTUnwrap(
                Bundle(for: Self.self).url(
                    forResource: fixture.name,
                    withExtension: fixture.fileExtension
                )
            )
            let book = try IosMobiBook.open(fileURL: fixtureURL)
            let info = try await book.info()
            XCTAssertGreaterThan(info.resourceCount, 0, fixture.name)
            XCTAssertGreaterThan(info.readingOrderCount, 0, fixture.name)
            let resourceIndex = try await book.readingOrderResourceIndex(at: 0)
            let resource = try await book.resource(at: resourceIndex)
            XCTAssertFalse(resource.sourceName.isEmpty, fixture.name)
            XCTAssertFalse(resource.mediaType.isEmpty, fixture.name)
            let firstChunk = try await book.readResource(
                at: resourceIndex,
                offset: 0,
                length: 4096
            )
            XCTAssertFalse(firstChunk.isEmpty, fixture.name)
            let eofChunk = try await book.readResource(
                at: resourceIndex,
                offset: resource.decodedLength,
                length: 4096
            )
            XCTAssertTrue(eofChunk.isEmpty, fixture.name)
            await book.close()
            await book.close()
        }
#endif
    }

    func testSyntheticLargePublicationOnPhysicalDevice() async throws {
#if targetEnvironment(simulator)
        XCTFail("R5 iOS memory evidence must run on a physical iOS device")
#else
        let sourceURL = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "test", withExtension: "azw3")
        )
        let targetURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("ermao-r5-synthetic-110m.azw3")
        try? FileManager.default.removeItem(at: targetURL)
        try FileManager.default.copyItem(at: sourceURL, to: targetURL)
        let file = try FileHandle(forWritingTo: targetURL)
        try file.truncate(atOffset: 110 * 1024 * 1024)
        try file.close()

        let clock = ContinuousClock()
        let started = clock.now
        for _ in 0 ..< 5 {
            let book = try IosMobiBook.open(fileURL: targetURL)
            let resourceIndex = try await book.readingOrderResourceIndex(at: 0)
            let firstChunk = try await book.readResource(
                at: resourceIndex,
                offset: 0,
                length: 4096
            )
            XCTAssertFalse(firstChunk.isEmpty)
            await book.close()
        }
        let elapsed = started.duration(to: clock.now)
        XCTAssertGreaterThan(elapsed, .zero)
#endif
    }

    func testHybridHuffAndStableErrorsOnPhysicalDevice() async throws {
#if targetEnvironment(simulator)
        XCTFail("R5 iOS corpus evidence must run on a physical iOS device")
#else
        let hybridURL = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "11-upstream-huff-cdic", withExtension: "mobi")
        )
        let hybridBook = try IosMobiBook.open(fileURL: hybridURL)
        let hybridInfo = try await hybridBook.info()
        XCTAssertEqual(hybridInfo.format, .hybridKf8)
        await hybridBook.close()

        let failures: [(name: String, fileExtension: String, status: IosMobiCoreStatus)] = [
            ("negative-synthetic-drm-header", "mobi", .drmProtected),
            ("negative-upstream-drm-v1", "mobi", .drmProtected),
            ("negative-no-content", "mobi", .noContent),
            ("negative-truncated", "mobi", .corrupt),
            ("negative-corrupt-record-offset", "mobi", .corrupt),
            ("negative-pseudo", "mobi", .unsupported),
            ("negative-synthetic-kfx", "kfx", .unsupported),
            ("negative-synthetic-azw4", "azw4", .unsupported),
        ]
        for failure in failures {
            let fixtureURL = try XCTUnwrap(
                Bundle(for: Self.self).url(
                    forResource: failure.name,
                    withExtension: failure.fileExtension
                )
            )
            XCTAssertThrowsError(try IosMobiBook.open(fileURL: fixtureURL)) { error in
                XCTAssertEqual((error as? IosMobiCoreError)?.status, failure.status, failure.name)
            }
        }
#endif
    }

    private func snapshot(_ book: IosMobiBook) async throws -> String {
        let info = try await book.info()
        var lines = [
            "snapshot-version\t1",
            "abi\t\(IosMobiBook.abiVersion)",
            "parser\t\(IosMobiBook.parserIdentifier.hexEncoded)",
            "normalization\t\(IosMobiBook.normalizationIdentifier.hexEncoded)",
            "book\t\(info.format.rawValue)\t\(info.readingDirection.rawValue)\t" +
                snapshotIndex(info.coverResourceIndex),
        ]
        for field in IosMobiMetadataField.allCases {
            lines.append(
                "metadata\t\(field.rawValue)\t" + nullableHex(try await book.metadata(field))
            )
        }
        for resourceIndex in 0 ..< info.resourceCount {
            let resource = try await book.resource(at: resourceIndex)
            var hasher = SHA256()
            var offset: UInt64 = 0
            while offset < resource.decodedLength {
                let requested = Int(
                    min(UInt64(IosMobiBook.maximumReadBytes), resource.decodedLength - offset)
                )
                let chunk = try await book.readResource(
                    at: resourceIndex,
                    offset: offset,
                    length: requested
                )
                guard !chunk.isEmpty else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                hasher.update(data: chunk)
                offset += UInt64(chunk.count)
            }
            let digest = Data(hasher.finalize()).hexEncoded
            lines.append(
                "resource\t\(resourceIndex)\t\(resource.category.rawValue)\t" +
                    "\(resource.sourceUID)\t\(resource.decodedLength)\t\(digest)\t" +
                    "\(resource.sourceName.hexEncoded)\t\(resource.mediaType.hexEncoded)"
            )
        }
        for position in 0 ..< info.readingOrderCount {
            lines.append(
                "reading\t\(position)\t\(try await book.readingOrderResourceIndex(at: position))"
            )
        }
        for tocIndex in 0 ..< info.tocCount {
            let toc = try await book.toc(at: tocIndex)
            lines.append(
                "toc\t\(tocIndex)\t\(snapshotIndex(toc.parentIndex))\t" +
                    "\(snapshotIndex(toc.targetResourceIndex))\t\(nullableHex(toc.title))\t" +
                    nullableHex(toc.fragment)
            )
        }
        for warningIndex in 0 ..< info.warningCount {
            let warning = try await book.warning(at: warningIndex)
            lines.append(
                "warning\t\(warningIndex)\t\(warning.code)\t" +
                    snapshotIndex(warning.relatedIndex)
            )
        }
        return lines.joined(separator: "\n") + "\n"
    }

    private func snapshotIndex(_ index: Int?) -> String {
        index.map { String($0) } ?? String(UInt32.max)
    }

    private func nullableHex(_ value: String?) -> String {
        value?.hexEncoded ?? "-"
    }
}

private extension String {
    var hexEncoded: String { Data(utf8).hexEncoded }
}

private extension Data {
    var hexEncoded: String {
        map { String(format: "%02x", $0) }.joined()
    }
}
