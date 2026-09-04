import XCTest
@testable import ErmaoLibrary
@preconcurrency import ErmaoShared
import ReadiumShared

final class ReaderProgressContractTests: XCTestCase {
    func testReadiumLocatorRoundTripPreservesEmptyHighlightNullAndExtensions() throws {
        let json = #"{"href":"OEBPS/Text/backcover.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":".cover","fragments":[],"position":190,"progression":1,"totalProgression":0.25,"vendor":{"nullable":null,"empty":""}},"text":{"highlight":""},"unknownExtension":{"preserve":true}}"#
        let readium = try Locator(jsonString: json)
        let opaque = try ReadiumSwiftLocatorMapper().opaqueLocator(from: readium)
        let restored = try XCTUnwrap(try ReadiumSwiftLocatorMapper().locator(from: opaque))

        XCTAssertEqual(try canonicalJSONObjectData(restored.jsonString()), try canonicalJSONObjectData(json))
        let root = try XCTUnwrap(try semanticJSONObject(opaque.canonicalJson) as? [String: Any])
        let text = try XCTUnwrap(root["text"] as? [String: Any])
        XCTAssertEqual(text["highlight"] as? String, "")
        let locations = try XCTUnwrap(root["locations"] as? [String: Any])
        let vendor = try XCTUnwrap(locations["vendor"] as? [String: Any])
        XCTAssertTrue(vendor["nullable"] is NSNull)
    }

    func testOpaqueLocatorAcceptsUnknownObjectWithoutExactnessProofFields() throws {
        let json = #"{"text":{"highlight":""},"nested":{"unknown":[null,"",{"x":true}]}}"#
        let opaque = try ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: json)

        XCTAssertEqual(try canonicalJSONObjectData(opaque.canonicalJson), try canonicalJSONObjectData(json))
    }

    func testPresentationNeverBecomesARestoreFallbackForAnUnsupportedLocator() throws {
        let opaque = try ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: #"{}"#)
        let presentation = ErmaoShared.ReaderPositionPresentation(
            displayPercent: 99,
            totalProgression: 0.99,
            currentHref: "OEBPS/Text/backcover.xhtml",
            chapter: nil,
            page: nil,
            playback: nil
        )
        let report = ErmaoShared.ReaderPositionReport(locator: opaque, presentation: presentation)

        XCTAssertNil(try? ReadiumSwiftLocatorMapper().locator(from: report.locator))
        XCTAssertEqual(report.presentation.displayPercent, 99)
    }

    func testOpaqueLocatorRejectsNonObjectAndOversizedPayloads() {
        XCTAssertThrowsError(
            try ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: #"[1,2,3]"#)
        )
        let oversized = #"{"payload":""# + String(repeating: "x", count: 65_536) + #""}"#
        XCTAssertThrowsError(
            try ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: oversized)
        )
    }

    func testPresentationDoesNotDeriveFromLocatorProgression() throws {
        let opaque = try ErmaoShared.PublicKt.createReaderOpaqueLocator(
            payloadJson: #"{"locations":{"totalProgression":0.25},"text":{"highlight":""}}"#
        )
        let presentation = ErmaoShared.ReaderPositionPresentation(
            displayPercent: 99,
            totalProgression: 0.99,
            currentHref: "OEBPS/Text/backcover.xhtml",
            chapter: ErmaoShared.ReaderChapterPresentation(
                href: "OEBPS/Text/backcover.xhtml",
                title: "封底",
                index: KotlinInt(int: 19)
            ),
            page: nil,
            playback: nil
        )
        let report = ErmaoShared.ReaderPositionReport(locator: opaque, presentation: presentation)

        XCTAssertEqual(report.presentation.displayPercent, 99)
        XCTAssertEqual(report.presentation.totalProgression, 0.99)
        let locatorRoot = try XCTUnwrap(try semanticJSONObject(report.locator.canonicalJson) as? [String: Any])
        let locations = try XCTUnwrap(locatorRoot["locations"] as? [String: Any])
        XCTAssertEqual((locations["totalProgression"] as? NSNumber)?.doubleValue, 0.25)
    }

    func testAndroidStylePdfLocatorCanBeConsumedWithoutFieldConversion() throws {
        let androidLocator = #"{"href":"document.pdf","type":"application/pdf","locations":{"position":190,"progression":1,"totalProgression":1},"vendor":{"android":null}}"#
        let opaque = try ErmaoShared.PublicKt.createReaderOpaqueLocator(payloadJson: androidLocator)
        let restored = try XCTUnwrap(try ReadiumSwiftLocatorMapper().locator(from: opaque))

        XCTAssertEqual(restored.locations.position, 190)
        XCTAssertEqual(
            try canonicalJSONObjectData(restored.jsonString()),
            try canonicalJSONObjectData(androidLocator)
        )
    }

    func testEveryCrossPlatformV5FixtureRoundTripsWithoutPositionConversion() throws {
        let bundle = Bundle(for: Self.self)
        let codec = ErmaoShared.PublicKt.createReaderPositionReportJson()
        let fixtures = [
            "reader-v5-reflowable-empty-highlight",
            "reader-v5-pdf",
            "reader-v5-comic",
            "reader-v5-audio",
        ]

        for fixture in fixtures {
            let url = try XCTUnwrap(
                bundle.url(forResource: fixture, withExtension: "json"),
                "Missing bundled contract fixture \(fixture)"
            )
            let document = try XCTUnwrap(
                try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
            )
            let position = try XCTUnwrap(document["position"] as? [String: Any])
            let positionData = try JSONSerialization.data(
                withJSONObject: position,
                options: [.sortedKeys]
            )
            let positionJSON = try XCTUnwrap(String(data: positionData, encoding: .utf8))

            let decoded = try codec.decode(payload: positionJSON)
            let encoded = codec.encode(position: decoded)

            XCTAssertEqual(
                try canonicalJSONObjectData(encoded),
                try canonicalJSONObjectData(positionJSON),
                "Reader v5 semantic drift in \(fixture)"
            )
        }
    }

    private func semanticJSONObject(_ json: String) throws -> Any {
        try JSONSerialization.jsonObject(with: Data(json.utf8), options: [.fragmentsAllowed])
    }

    private func canonicalJSONObjectData(_ json: String) throws -> Data {
        let value = try semanticJSONObject(json)
        return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    }
}
