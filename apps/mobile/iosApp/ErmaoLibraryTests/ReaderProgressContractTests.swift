import Foundation
import XCTest
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@testable import ErmaoLibrary

final class ReaderProgressContractTests: XCTestCase {
    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    func testV4ExactLocatorRoundTripsAsObjectPayload() throws {
        let codec = ErmaoShared.PublicKt.createReaderProgressJson()
        let progress = try codec.decode(payload: exactProgressPayload())
        let encoded = try codec.encode(progress: progress)
        let decoded = try IosReaderProgressContractDecoder.decode(encoded)

        XCTAssertTrue(encoded.contains(#""version":5"#))
        XCTAssertTrue(encoded.contains(#""engine":"readium""#))
        XCTAssertTrue(encoded.contains(#""payload":{"href""#))
        XCTAssertFalse(encoded.contains(#""payload":"{"#))
        XCTAssertEqual(decoded.sourceID, "volume-epub-42")
        XCTAssertEqual(decoded.resourceKey, "OPS/chapter-03.xhtml")
        XCTAssertEqual(decoded.quoteExact, "A portable reading position")
        XCTAssertTrue(decoded.engineLocatorCanonicalJSON?.contains("\"cssSelector\":\"#paragraph-17\"") == true)
    }

    func testLegacyV1AndProgressionOnlyLocatorsAreRejected() {
        let codec = ErmaoShared.PublicKt.createReaderProgressJson()
        let legacy = exactProgressPayload().replacingOccurrences(of: #""version":5"#, with: #""version":1"#)
        let approximate = exactProgressPayload().replacingOccurrences(
            of: ##""locations":{"cssSelector":"#paragraph-17","progression":0.375}"##,
            with: #""locations":{"progression":0.375}"#
        ).replacingOccurrences(
            of: #",\"text\":{\"highlight\":\"A portable reading position\",\"before\":\"Before\",\"after\":\"after\"}"#
                .replacingOccurrences(of: "\\\"", with: "\""),
            with: ""
        )

        XCTAssertThrowsError(try codec.decode(payload: legacy))
        XCTAssertThrowsError(try codec.decode(payload: approximate))
        XCTAssertThrowsError(try IosReaderProgressContractDecoder.decode(legacy))
    }

    func testSwiftMapperRejectsProgressionOnlyLocatorBeforeKmpProgressConstruction() throws {
        let locator = try XCTUnwrap(
            try Locator(
                jsonString: #"{"href":"OPS/chapter.xhtml","type":"application/xhtml+xml","locations":{"progression":0.25,"totalProgression":0.5}}"#
            )
        )
        let fingerprint = try IosContentFingerprint(
            originalFileHash: "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            parserVersion: "readium:epub",
            normalizationVersion: "epub-v1"
        )

        XCTAssertThrowsError(
            try ReadiumSwiftLocatorMapper().sharedLocation(from: locator, fingerprint: fingerprint)
        )
    }

    func testExactBlockComparatorRequiresFingerprintResourceAndAnchor() throws {
        let progress = try ErmaoShared.PublicKt.createReaderProgressJson().decode(payload: exactProgressPayload())
        let location = try XCTUnwrap(progress.location as? ErmaoShared.ReflowReaderLocation)
        let expected = try XCTUnwrap(ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location))
        let same = try XCTUnwrap(ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location))
        let anotherResourceProgress = try ErmaoShared.PublicKt.createReaderProgressJson().decode(
            payload: exactProgressPayload().replacingOccurrences(
                of: "OPS/chapter-03.xhtml",
                with: "OPS/chapter-04.xhtml"
            )
        )
        let anotherResource = try XCTUnwrap(
            ErmaoShared.ReadiumLocatorEnvelope.companion.from(
                location: try XCTUnwrap(anotherResourceProgress.location as? ErmaoShared.ReflowReaderLocation)
            )
        )

        XCTAssertEqual(ErmaoShared.PublicKt.compareExactReadiumLocators(expected: expected, recaptured: same), .exact)
        XCTAssertNotEqual(
            ErmaoShared.PublicKt.compareExactReadiumLocators(expected: expected, recaptured: anotherResource),
            ErmaoShared.ExactBlockMatch.exact
        )
    }

    func testRestoreNeverFallsBackToPercentageOnFingerprintMismatch() throws {
        let local = try ErmaoShared.PublicKt.createReaderProgressJson().decode(payload: exactProgressPayload())
        let plan = ErmaoShared.PublicKt.planReaderProgressRestore(
            localProgress: local,
            remoteSnapshot: nil,
            openedSource: makeSource(
                hash: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            )
        )

        XCTAssertFalse(plan.usesLocalExact)
        XCTAssertNil(plan.localProgress)
        XCTAssertNil(plan.remoteSnapshot)
        XCTAssertTrue(plan.candidates.isEmpty)
    }

    private func makeSource(hash: String = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef") -> ErmaoShared.ReaderSource {
        ErmaoShared.LocalReaderSource(
            sourceId: "volume-epub-42",
            displayTitle: "Fixture",
            format: .epub,
            contentFingerprint: ErmaoShared.ContentFingerprint(
                originalFileHash: hash,
                parserVersion: "readium:epub",
                normalizationVersion: "epub-v1"
            ),
            workId: "work-42",
            volumeId: "volume-epub-42"
        )
    }

    private func exactProgressPayload(
        sourceID: String = "volume-epub-42",
        updatedAt: Int64 = 1_775_988_123_456,
        deviceID: String = "ios-installation-a"
    ) -> String {
        ##"{"schema":"ermao.reader-progress","version":5,"sourceId":"\##(sourceID)","location":{"kind":"reflow","resourceKey":"OPS/chapter-03.xhtml","progression":0.375,"totalProgression":0.625,"position":17,"textQuote":{"exact":"A portable reading position","prefix":"Before","suffix":"after"},"engineLocator":{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","payload":{"href":"OPS/chapter-03.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#paragraph-17","progression":0.375},"text":{"highlight":"A portable reading position","before":"Before","after":"after"}}},"contentFingerprint":{"originalFileHash":"sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","parserVersion":"readium:epub","normalizationVersion":"epub-v1"}},"updatedAtEpochMillis":\##(updatedAt),"deviceId":"\##(deviceID)","percent":62.5}"##
    }
}
