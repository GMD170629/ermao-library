import Foundation
import XCTest
@testable import ReaderPOC

@MainActor
final class FixtureGoldenTests: XCTestCase {
    func testAllPinnedFixturesMatchExtractionAndManifestContracts() async throws {
        #if targetEnvironment(simulator)
        XCTFail("Reader POC acceptance requires a connected physical iOS device")
        return
        #endif

        let expectationsURL = try XCTUnwrap(bundledURL(baseName: "fixture-expectations", extension: "json"))
        let expectations = try JSONDecoder().decode(GoldenEnvelope.self, from: Data(contentsOf: expectationsURL))
        XCTAssertEqual(expectations.schemaVersion, 1)
        XCTAssertEqual(expectations.fixtures.count, 10)

        let extractor = NativeMobiExtractor()
        let factory = MobiPublicationFactory(extractor: extractor)
        for expectation in expectations.fixtures {
            let fileURL = try XCTUnwrap(bundledURL(
                baseName: URL(fileURLWithPath: expectation.file).deletingPathExtension().lastPathComponent,
                extension: URL(fileURLWithPath: expectation.file).pathExtension
            ), "Missing bundled fixture \(expectation.file)")
            let book = try await extractor.extract(fileURL)
            let resourceSummary = book.resources.map { "\($0.href):\($0.mediaType)" }
            print(
                "FIXTURE_DIAGNOSTIC \(expectation.file) format=\(book.format.rawValue) "
                    + "readingOrder=\(book.readingOrder.map(\.href)) resources="
                    + "\(resourceSummary) toc=\(book.tableOfContents.flattened.map(\.href))"
            )
            XCTAssertEqual(book.format.rawValue, expectation.format, expectation.file)
            XCTAssertEqual(book.readingOrder.map(\.href), expectation.readingOrderHrefs, expectation.file)
            XCTAssertEqual(
                Dictionary(grouping: book.resources, by: \.mediaType).mapValues(\.count),
                expectation.resourceMediaTypeCounts,
                expectation.file
            )
            XCTAssertEqual(book.tableOfContents.flattened.map(\.href), expectation.tocHrefs, expectation.file)
            XCTAssertGreaterThanOrEqual(maximumDepth(book.tableOfContents), expectation.minimumTocDepth, expectation.file)

            let decodedMarkup = book.readingOrder.compactMap { String(data: $0.data, encoding: .utf8) }.joined(separator: "\n")
            for marker in expectation.markers {
                XCTAssertTrue(decodedMarkup.contains(marker), "\(expectation.file) is missing marker \(marker)")
            }
            if let minimumCjkCharacters = expectation.minimumCjkCharacters {
                XCTAssertGreaterThanOrEqual(cjkCharacterCount(decodedMarkup), minimumCjkCharacters, expectation.file)
            }

            let result = try await factory.build(book)
            XCTAssertEqual(result.publication.readingOrder.count, book.readingOrder.count, expectation.file)
            XCTAssertTrue(result.publication.metadata.conformsTo.contains(.epub), expectation.file)
            XCTAssertEqual(result.preflight.resourceCount, book.allResources.count, expectation.file)
        }
    }

    private func maximumDepth(_ navigation: [MobiNavigationItem]) -> Int {
        guard !navigation.isEmpty else { return 0 }
        return navigation.map { 1 + maximumDepth($0.children) }.max() ?? 0
    }

    private func bundledURL(baseName: String, extension fileExtension: String) -> URL? {
        Bundle.main.url(forResource: baseName, withExtension: fileExtension, subdirectory: "Fixtures")
            ?? Bundle.main.url(forResource: baseName, withExtension: fileExtension)
    }

    private func cjkCharacterCount(_ value: String) -> Int {
        value.unicodeScalars.count { scalar in
            (0x3400 ... 0x4DBF).contains(scalar.value)
                || (0x4E00 ... 0x9FFF).contains(scalar.value)
                || (0x20000 ... 0x2FA1F).contains(scalar.value)
        }
    }
}

private struct GoldenEnvelope: Decodable {
    let schemaVersion: Int
    let fixtures: [GoldenFixture]
}

private struct GoldenFixture: Decodable {
    let file: String
    let format: String
    let readingOrderHrefs: [String]
    let resourceMediaTypeCounts: [String: Int]
    let tocHrefs: [String]
    let minimumTocDepth: Int
    let minimumCjkCharacters: Int?
    let markers: [String]
}
