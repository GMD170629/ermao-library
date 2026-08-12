import Foundation
import ReadiumShared
import XCTest
@testable import ReaderPOC

@MainActor
final class MobiPublicationFactoryTests: XCTestCase {
    func testBuildsEPUBSemanticPublicationEntirelyFromMemory() async throws {
        let result = try await MobiPublicationFactory(extractor: FixedExtractor(book: Self.validBook)).build(Self.validBook)

        XCTAssertTrue(result.publication.metadata.conformsTo.contains(.epub))
        XCTAssertEqual(result.publication.readingOrder.map(\.href), ["text/chapter1.xhtml", "text/chapter2.xhtml"])
        XCTAssertEqual(result.publication.manifest.tableOfContents.first?.children.count, 1)
        XCTAssertEqual(result.preflight.resourceCount, 5)
        XCTAssertEqual(result.preflight.verifiedReferenceCount, 6)

        let cssLink = try XCTUnwrap(result.publication.resources.first { $0.href == "styles/book.css" })
        let cssResource = try XCTUnwrap(result.publication.get(cssLink) as? DataResource)
        let css = try await cssResource.read().get()
        XCTAssertTrue(String(decoding: css, as: UTF8.self).contains("@font-face"))
    }

    func testFailsPreflightForMissingInternalResource() async {
        let brokenChapter = Self.resource(
            uid: 1,
            href: "text/chapter1.xhtml",
            mediaType: "application/xhtml+xml",
            category: .markup,
            text: #"<html><body><img src="../images/missing.png" /></body></html>"#
        )
        let book = MobiExtractedBook(
            format: .kf8,
            metadata: Self.metadata,
            readingOrder: [brokenChapter],
            resources: [],
            tableOfContents: [],
            warnings: []
        )

        do {
            _ = try await MobiPublicationFactory(extractor: FixedExtractor(book: book)).build(book)
            XCTFail("Expected unresolved resource failure")
        } catch let error as MobiPublicationError {
            XCTAssertEqual(error, .unresolvedResource(source: "text/chapter1.xhtml", target: "images/missing.png"))
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testContainerRejectsDuplicateAndEscapingPaths() {
        let resource = Self.resource(uid: 1, href: "same.css", mediaType: "text/css", category: .flow, text: "body{}")
        XCTAssertThrowsError(try InMemoryMobiContainer(resources: [resource, resource]))
        let escaping = Self.resource(uid: 2, href: "../same.css", mediaType: "text/css", category: .flow, text: "body{}")
        XCTAssertThrowsError(try InMemoryMobiContainer(resources: [escaping]))
    }

    private struct FixedExtractor: MobiExtracting {
        let book: MobiExtractedBook

        func extract(_ file: URL) async throws -> MobiExtractedBook {
            book
        }
    }

    private static let metadata = MobiMetadata(
        title: "In-memory publication",
        author: "POC",
        language: "en",
        description: nil,
        readingProgression: .leftToRight
    )

    private static let validBook: MobiExtractedBook = {
        let chapter1 = resource(
            uid: 1,
            href: "text/chapter1.xhtml",
            mediaType: "application/xhtml+xml",
            category: .markup,
            text: #"<html><head><link rel="stylesheet" href="../styles/book.css" /></head><body><p id="one">One</p><a href="chapter2.xhtml#two">Two</a><img src="../images/proof.png" /></body></html>"#
        )
        let chapter2 = resource(
            uid: 2,
            href: "text/chapter2.xhtml",
            mediaType: "application/xhtml+xml",
            category: .markup,
            text: #"<html><body><p id="two">Two</p></body></html>"#
        )
        let css = resource(
            uid: 3,
            href: "styles/book.css",
            mediaType: "text/css",
            category: .flow,
            text: "@font-face { font-family: Proof; src: url('../fonts/proof.ttf'); }"
        )
        let image = MobiResource(uid: 4, href: "images/proof.png", mediaType: "image/png", category: .resource, data: Data([0x89, 0x50, 0x4e, 0x47]))
        let font = MobiResource(uid: 5, href: "fonts/proof.ttf", mediaType: "font/ttf", category: .resource, data: Data([0, 1, 0, 0]))
        return MobiExtractedBook(
            format: .kf8,
            metadata: metadata,
            readingOrder: [chapter1, chapter2],
            resources: [css, image, font],
            tableOfContents: [
                MobiNavigationItem(
                    id: "one",
                    title: "One",
                    href: "text/chapter1.xhtml#one",
                    children: [MobiNavigationItem(id: "two", title: "Two", href: "text/chapter2.xhtml#two", children: [])]
                ),
            ],
            warnings: []
        )
    }()

    private static func resource(
        uid: UInt64,
        href: String,
        mediaType: String,
        category: MobiResourceCategory,
        text: String
    ) -> MobiResource {
        MobiResource(uid: uid, href: href, mediaType: mediaType, category: category, data: Data(text.utf8))
    }
}
