import CryptoKit
import Foundation
@preconcurrency import ReadiumShared
import XCTest
@testable import ErmaoLibrary

final class MobiPublicationFactoryTests: XCTestCase {
    override func setUp() {
        super.setUp()
#if targetEnvironment(simulator)
        XCTFail("MOBI Publication product tests require a connected physical iOS device")
#endif
    }

    func testFormalPublicationFactoryOpensMobiFamilyOnPhysicalDevice() async throws {
#if targetEnvironment(simulator)
        XCTFail("MOBI Publication product evidence must run on a physical iOS device")
#else
        let fixtures = [
            ("01-basic-mobi6", "mobi"),
            ("test", "azw3"),
            ("12-basic", "prc"),
            ("13-basic", "azw"),
        ]
        for fixture in fixtures {
            let url = try XCTUnwrap(
                Bundle(for: Self.self).url(
                    forResource: fixture.0,
                    withExtension: fixture.1
                )
            )
            let result = try await IosMobiPublicationFactory().open(
                fileURL: url,
                contentFingerprint: "physical-\(fixture.0)",
                displayTitle: fixture.0
            )
            let firstLink = try XCTUnwrap(result.publication.readingOrder.first)
            let firstResource = try XCTUnwrap(result.publication.get(firstLink))
            let firstBytes = try await firstResource.read(range: 0 ..< 4096).get()
            XCTAssertFalse(firstBytes.isEmpty, fixture.0)
            await result.close()
        }
#endif
    }

    func testBuildsLazyPublicationFromAbiIndexesAndHierarchicalToc() async throws {
        let book = FixedMobiBook.fixture()
        let result = try await IosMobiPublicationFactory().build(
            book: book,
            contentFingerprint: "sha256-parser-normalization"
        )

        XCTAssertEqual(result.format, .kf8)
        XCTAssertEqual(result.publication.readingOrder.map(\.href), ["text/chapter.xhtml"])
        XCTAssertEqual(result.publication.manifest.tableOfContents.count, 1)
        XCTAssertEqual(result.publication.manifest.tableOfContents.first?.href, "text/chapter.xhtml")
        XCTAssertEqual(
            result.publication.manifest.tableOfContents.first?.children.first?.href,
            "text/chapter.xhtml#section"
        )
        XCTAssertEqual(
            result.publication.resources.first { $0.rels.contains(.cover) }?.href,
            "images/cover.jpg"
        )
        let firstLink = try XCTUnwrap(
            result.publication.readingOrder.first { $0.href == "text/chapter.xhtml" }
        )
        let firstResource = try XCTUnwrap(result.publication.get(firstLink))
        let estimatedLength = try await firstResource.estimatedLength().get()
        XCTAssertNotNil(estimatedLength)
        let initialReadRequests = await book.readRequests()
        XCTAssertTrue(initialReadRequests.isEmpty)

        await result.close()
        await result.close()
        let closeCount = await book.closeCount()
        XCTAssertEqual(closeCount, 1)
    }

    func testBinaryResourceStreamsInChunksNoLargerThanCoreLimit() async throws {
        let book = FixedMobiBook.fixture(binarySize: IosMobiBook.maximumReadBytes * 2 + 31)
        let result = try await IosMobiPublicationFactory().build(
            book: book,
            contentFingerprint: "streaming-fixture"
        )
        let resourceLink = try XCTUnwrap(
            result.publication.resources.first { $0.href == "assets/large.bin" }
        )
        let resource = try XCTUnwrap(result.publication.get(resourceLink))

        let data = try await resource.read().get()
        XCTAssertEqual(data.count, IosMobiBook.maximumReadBytes * 2 + 31)
        let requests = await book.readRequests().filter { $0.index == 3 }
        XCTAssertEqual(requests.map(\.length), [
            IosMobiBook.maximumReadBytes,
            IosMobiBook.maximumReadBytes,
            31,
        ])
        XCTAssertTrue(requests.allSatisfy { $0.length <= IosMobiBook.maximumReadBytes })

        await result.close()
    }

    func testStructuralTocNodeUsesFirstDescendantTarget() async throws {
        let book = FixedMobiBook.fixture(structuralTocRoot: true)
        let result = try await IosMobiPublicationFactory().build(
            book: book,
            contentFingerprint: "structural-toc"
        )

        let root = try XCTUnwrap(result.publication.manifest.tableOfContents.first)
        XCTAssertEqual(root.href, "text/chapter.xhtml#section")
        XCTAssertEqual(root.children.first?.href, "text/chapter.xhtml#section")
        await result.close()
    }

    func testLegacyValidMarkupHeadIsDecoratedWithoutChangingAuthorBodyOrCss() async throws {
        let book = FixedMobiBook.fixture(
            markup: """
            <html xmlns="http://www.w3.org/1999/xhtml"><head></head><body onload="steal()">
            <script src="https://evil.example/a.js">steal()</script>
            <img src="https://evil.example/cover.jpg"/><a href="chapter2.xhtml">Local</a>
            <p style="background:url(https://evil.example/tracker.png)">Text</p>
            </body></html>
            """,
            css: """
            @import url("https://evil.example/theme.css");
            body { background: url(//evil.example/pixel.png); }
            p { background: url('../images/local.png'); }
            """
        )
        let result = try await IosMobiPublicationFactory().build(
            book: book,
            contentFingerprint: "sanitizer-fixture"
        )
        let markupLink = try XCTUnwrap(
            result.publication.readingOrder.first { $0.href == "text/chapter.xhtml" }
        )
        let cssLink = try XCTUnwrap(
            result.publication.resources.first { $0.href == "styles/book.css" }
        )
        let markupResource = try XCTUnwrap(result.publication.get(markupLink))
        let cssResource = try XCTUnwrap(result.publication.get(cssLink))

        let markupData = try await markupResource.read().get()
        let cssData = try await cssResource.read().get()
        let markup = try XCTUnwrap(String(data: markupData, encoding: .utf8))
        let css = try XCTUnwrap(String(data: cssData, encoding: .utf8))
        XCTAssertTrue(markup.contains("Content-Security-Policy"))
        XCTAssertTrue(markup.localizedCaseInsensitiveContains("<script"))
        XCTAssertTrue(markup.localizedCaseInsensitiveContains("onload="))
        XCTAssertTrue(markup.contains("https://evil.example"))
        XCTAssertTrue(markup.contains("href=\"chapter2.xhtml\""))
        XCTAssertTrue(css.contains("https://evil.example"))
        XCTAssertTrue(css.contains("//evil.example"))
        XCTAssertTrue(css.contains("../images/local.png"))

        await result.close()
    }

    func testRejectsEscapingDuplicateAndInvalidTocResources() async {
        let invalidPath = FixedMobiBook.fixture(resourceNameOverride: "../../private.xhtml")
        do {
            _ = try await IosMobiPublicationFactory().build(
                book: invalidPath,
                contentFingerprint: "invalid-path"
            )
            XCTFail("Expected invalid resource path")
        } catch {
            XCTAssertEqual(error as? IosMobiPublicationError, .invalidResourcePath("../../private.xhtml"))
        }

        let duplicatePath = FixedMobiBook.fixture(resourceNameOverride: "styles/book.css")
        do {
            _ = try await IosMobiPublicationFactory().build(
                book: duplicatePath,
                contentFingerprint: "duplicate-path"
            )
            XCTFail("Expected duplicate resource path")
        } catch {
            XCTAssertEqual(error as? IosMobiPublicationError, .duplicateResourcePath("styles/book.css"))
        }

        let invalidToc = FixedMobiBook.fixture(invalidTocParent: true)
        do {
            _ = try await IosMobiPublicationFactory().build(
                book: invalidToc,
                contentFingerprint: "invalid-toc"
            )
            XCTFail("Expected invalid table of contents")
        } catch {
            XCTAssertEqual(error as? IosMobiPublicationError, .invalidTableOfContents)
        }
    }

    func testPublicationPathRejectsEncodedTraversalAndSchemes() {
        XCTAssertNil(IosMobiPublicationPath.resourcePath("%2e%2e/private.xhtml"))
        XCTAssertNil(IosMobiPublicationPath.resourcePath("https%3A//evil.example/book.xhtml"))
        XCTAssertNil(IosMobiPublicationPath.resourcePath("OPS%5cprivate.xhtml"))
        XCTAssertEqual(
            IosMobiPublicationPath.resourcePath("/OPS/./text/../chapter.xhtml"),
            "OPS/chapter.xhtml"
        )
    }

    func testManagedStorePersistsSidecarEpubWithOriginalMobiFingerprint() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("managed-mobi-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try IosManagedPublicationStore(root: root)
        let sidecar = Data([
            0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00,
            0x14, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00,
        ]) + Data("mimetypeapplication/epub+zip".utf8)
        let artifactHash = "sha256:" + SHA256.hash(data: sidecar)
            .map { String(format: "%02x", $0) }
            .joined()
        let originalHash = "sha256:" + String(repeating: "a", count: 64)
        let staging = try await store.prepareDownload(
            sourceID: "volume-azw3",
            expectedSize: Int64(sidecar.count)
        )
        try sidecar.write(to: staging)

        let imported = try await store.commitDownload(
            staging: staging,
            sourceID: "volume-azw3",
            displayTitle: "AZW3 fixture",
            byteCount: Int64(sidecar.count),
            artifactContentHash: artifactHash,
            expectedSize: Int64(sidecar.count),
            expectedContentHash: artifactHash,
            originalFileHash: originalHash,
            parserVersion: IosMobiBook.parserIdentifier,
            normalizationVersion: IosMobiPublicationIdentity.normalizationIdentifier,
            sourceFormat: .epub,
            workID: "work-azw3",
            volumeID: "volume-azw3"
        )
        XCTAssertEqual(imported.sourceFormat, .epub)
        XCTAssertEqual(imported.fileURL.pathExtension, "epub")
        XCTAssertEqual(imported.artifactContentHash, artifactHash)
        XCTAssertEqual(imported.fingerprint.originalFileHash, originalHash)

        try await store.bindServerContentFingerprint(
            sourceID: imported.sourceID,
            value: "opaque-content-key"
        )
        let restored = try await store.resolve(sourceID: imported.sourceID)
        XCTAssertEqual(restored.sourceFormat, .epub)
        XCTAssertEqual(restored.serverContentFingerprint, "opaque-content-key")
        XCTAssertEqual(restored.fingerprint.parserVersion, IosMobiBook.parserIdentifier)
        XCTAssertEqual(
            restored.fingerprint.normalizationVersion,
            IosMobiPublicationIdentity.normalizationIdentifier
        )
    }
}

private actor FixedMobiBook: IosMobiBookAccess {
    struct StoredResource: Sendable {
        let info: IosMobiResourceInfo
        let content: Data
    }

    struct ReadRequest: Equatable, Sendable {
        let index: Int
        let offset: UInt64
        let length: Int
    }

    private let bookInfo: IosMobiBookInfo
    private let metadataValues: [IosMobiMetadataField: String]
    private let resources: [StoredResource]
    private let readingOrder: [Int]
    private let tocEntries: [IosMobiTocInfo]
    private var requests: [ReadRequest] = []
    private var numberOfCloses = 0
    private var closed = false

    init(
        bookInfo: IosMobiBookInfo,
        metadata: [IosMobiMetadataField: String],
        resources: [StoredResource],
        readingOrder: [Int],
        toc: [IosMobiTocInfo]
    ) {
        self.bookInfo = bookInfo
        metadataValues = metadata
        self.resources = resources
        self.readingOrder = readingOrder
        tocEntries = toc
    }

    func info() throws -> IosMobiBookInfo { bookInfo }
    func metadata(_ field: IosMobiMetadataField) throws -> String? { metadataValues[field] }
    func resource(at index: Int) throws -> IosMobiResourceInfo { resources[index].info }

    func readResource(at index: Int, offset: UInt64, length: Int) throws -> Data {
        guard !closed else { throw IosMobiPublicationError.closed }
        requests.append(ReadRequest(index: index, offset: offset, length: length))
        let data = resources[index].content
        let lower = min(Int(offset), data.count)
        let upper = min(lower + length, data.count)
        return data[lower ..< upper]
    }

    func readingOrderResourceIndex(at position: Int) throws -> Int { readingOrder[position] }
    func toc(at index: Int) throws -> IosMobiTocInfo { tocEntries[index] }

    func close() {
        guard !closed else { return }
        closed = true
        numberOfCloses += 1
    }

    func readRequests() -> [ReadRequest] { requests }
    func closeCount() -> Int { numberOfCloses }

    static func fixture(
        binarySize: Int = 17,
        markup: String = "<html><head></head><body><h1 id=\"section\">Chapter</h1></body></html>",
        css: String = "body { color: black; }",
        resourceNameOverride: String? = nil,
        invalidTocParent: Bool = false,
        structuralTocRoot: Bool = false
    ) -> FixedMobiBook {
        let contents: [(String, String, IosMobiResourceCategory, Data)] = [
            (
                resourceNameOverride ?? "text/chapter.xhtml",
                "application/xhtml+xml",
                .markup,
                Data(markup.utf8)
            ),
            ("styles/book.css", "text/css", .flow, Data(css.utf8)),
            ("images/cover.jpg", "image/jpeg", .asset, Data([0xFF, 0xD8, 0xFF, 0xD9])),
            ("assets/large.bin", "application/octet-stream", .asset, Data(repeating: 0xA5, count: binarySize)),
        ]
        let resources = contents.enumerated().map { index, value in
            StoredResource(
                info: IosMobiResourceInfo(
                    category: value.2,
                    sourceUID: UInt64(index + 100),
                    decodedLength: UInt64(value.3.count),
                    sourceName: value.0,
                    mediaType: value.1
                ),
                content: value.3
            )
        }
        let toc = [
            IosMobiTocInfo(
                parentIndex: invalidTocParent ? 1 : nil,
                targetResourceIndex: structuralTocRoot ? nil : 0,
                title: "Chapter",
                fragment: nil
            ),
            IosMobiTocInfo(
                parentIndex: 0,
                targetResourceIndex: 0,
                title: "Section",
                fragment: "section"
            ),
        ]
        return FixedMobiBook(
            bookInfo: IosMobiBookInfo(
                format: .kf8,
                readingDirection: .leftToRight,
                resourceCount: resources.count,
                readingOrderCount: 1,
                tocCount: toc.count,
                warningCount: 0,
                coverResourceIndex: 2
            ),
            metadata: [
                .title: "Fixture",
                .author: "Author",
                .language: "en",
            ],
            resources: resources,
            readingOrder: [0],
            toc: toc
        )
    }
}
