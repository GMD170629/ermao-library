import Foundation
import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

final class ReaderProgressContractTests: XCTestCase {
    private let goldenV1 = #"{"schema":"ermao.reader-progress","version":1,"sourceId":"volume-epub-42","location":{"kind":"reflow","resourceKey":"OPS/chapter-03.xhtml","progression":0.375,"totalProgression":0.625,"position":17,"textQuote":{"exact":"A portable reading position","prefix":"Before ","suffix":" after."},"engineLocator":{"href":"OPS/chapter-03.xhtml","type":"application/xhtml+xml","title":"Chapter 3","locations":{"fragments":["epubcfi(/6/8!/4/2/1:0)"],"progression":0.375,"totalProgression":0.625,"position":17},"text":{"highlight":"A portable reading position","before":"Before ","after":" after."}},"contentFingerprint":{"originalFileHash":"sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","parserVersion":"readium-swift:3.8.0","normalizationVersion":"epub-native-sanitized-v1"}},"updatedAtEpochMillis":1775988123456,"deviceId":"ios-installation-a"}"#

    override func setUp() {
        super.setUp()
        #if targetEnvironment(simulator)
        XCTFail("iOS Reader tests must run on a connected physical device, never Simulator.")
        #endif
    }

    func testGoldenV1DecodesResourceProgressionQuoteLocatorAndFingerprint() throws {
        let decoded = try IosReaderProgressContractDecoder.decode(goldenV1)

        XCTAssertEqual(decoded.sourceID, "volume-epub-42")
        XCTAssertEqual(decoded.resourceKey, "OPS/chapter-03.xhtml")
        XCTAssertEqual(decoded.progression, 0.375)
        XCTAssertEqual(decoded.totalProgression, 0.625)
        XCTAssertEqual(decoded.position, 17)
        XCTAssertEqual(decoded.quoteExact, "A portable reading position")
        XCTAssertEqual(decoded.quotePrefix, "Before ")
        XCTAssertEqual(decoded.quoteSuffix, " after.")
        XCTAssertEqual(decoded.fingerprint.parserVersion, "readium-swift:3.8.0")
        XCTAssertEqual(decoded.fingerprint.normalizationVersion, "epub-native-sanitized-v1")
        XCTAssertTrue(decoded.engineLocatorCanonicalJSON?.contains("epubcfi(/6/8!/4/2/1:0)") == true)
    }

    func testGoldenV1IsAcceptedBySharedReaderProgressJson() throws {
        let progress = ErmaoShared.ReaderProgressJson().decode(payload: goldenV1)
        let location = try XCTUnwrap(progress.location as? ErmaoShared.ReflowReaderLocation)

        XCTAssertEqual(progress.sourceId, "volume-epub-42")
        XCTAssertEqual(progress.updatedAtEpochMillis, 1_775_988_123_456)
        XCTAssertEqual(progress.deviceId, "ios-installation-a")
        XCTAssertEqual(location.resourceKey, "OPS/chapter-03.xhtml")
        XCTAssertEqual(location.progression?.doubleValue, 0.375)
        XCTAssertEqual(location.textQuote?.exact, "A portable reading position")
        XCTAssertEqual(
            location.contentFingerprint.originalFileHash,
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        )
        XCTAssertEqual(location.engineLocator?.engine, .readium)
        XCTAssertEqual(location.engineLocator?.platform, .ios)
        XCTAssertEqual(location.engineLocator?.version, "3.8.0")
        XCTAssertTrue(location.engineLocator?.payload.canonicalJson.contains("application/xhtml+xml") == true)
    }

    func testSharedV4CodecRoundTripsVersionedReadiumLocator() throws {
        let progress = ErmaoShared.ReaderProgressJson().decode(payload: goldenV1)
        let encoded = ErmaoShared.ReaderProgressJson().encode(progress: progress)
        let decoded = try IosReaderProgressContractDecoder.decode(encoded)

        XCTAssertTrue(encoded.contains(#""version":4"#))
        XCTAssertTrue(encoded.contains(#""kind":"reflow""#))
        XCTAssertTrue(encoded.contains(#""engine":"readium""#))
        XCTAssertTrue(encoded.contains(#""platform":"ios""#))
        XCTAssertTrue(encoded.contains(#""payload":{"href""#))
        XCTAssertFalse(encoded.contains(#""payload":"{"#))
        XCTAssertEqual(decoded.engineLocatorCanonicalJSON?.contains("epubcfi(/6/8!/4/2/1:0)"), true)
    }

    func testPureV4AllowsAnEngineOnlyReflowAnchorWithObjectPayload() throws {
        let payload = #"{"schema":"ermao.reader-progress","version":4,"sourceId":"volume-engine-only","location":{"kind":"reflow","engineLocator":{"engine":"readium","platform":"ios","version":"3.8.0","payload":{"href":"OPS/chapter.xhtml","locations":{"position":9}}},"contentFingerprint":{"originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parserVersion":"readium-swift:3.8.0","normalizationVersion":"epub-native-sanitized-v1"}},"updatedAtEpochMillis":1775988123456,"deviceId":"ios-installation-a","percent":25.0}"#

        let decoded = try IosReaderProgressContractDecoder.decode(payload)

        XCTAssertNil(decoded.resourceKey)
        XCTAssertNil(decoded.progression)
        XCTAssertEqual(decoded.engineLocatorCanonicalJSON?.contains(#""position":9"#), true)
    }

    func testRestorePlanKeepsLocalExactOnTimestampTieAndSelectsNewerRemote() throws {
        let local = ErmaoShared.ReaderProgressJson().decode(payload: goldenV1)
        let source = makeSource(originalFileHash: try XCTUnwrap(
            (local.location as? ErmaoShared.ReflowReaderLocation)?.contentFingerprint.originalFileHash
        ))
        let tiedRemote = makeRemoteSnapshot(updatedAt: local.updatedAtEpochMillis)
        let newerRemote = makeRemoteSnapshot(updatedAt: local.updatedAtEpochMillis + 1)

        let tie = ErmaoShared.PublicKt.planReaderProgressRestore(
            localProgress: local,
            remoteSnapshot: tiedRemote,
            openedSource: source
        )
        let newer = ErmaoShared.PublicKt.planReaderProgressRestore(
            localProgress: local,
            remoteSnapshot: newerRemote,
            openedSource: source
        )

        XCTAssertTrue(tie.usesLocalExact)
        XCTAssertNotNil(tie.localProgress)
        XCTAssertNil(tie.remoteSnapshot)
        XCTAssertFalse(newer.usesLocalExact)
        XCTAssertNil(newer.localProgress)
        XCTAssertEqual(newer.remoteSnapshot?.updatedAtEpochMillis, local.updatedAtEpochMillis + 1)
    }

    func testFingerprintMismatchDegradesNewerLocalProgressToPercentOnly() {
        let local = ErmaoShared.ReaderProgressJson().decode(payload: goldenV1)
        let plan = ErmaoShared.PublicKt.planReaderProgressRestore(
            localProgress: local,
            remoteSnapshot: nil,
            openedSource: makeSource(
                originalFileHash: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            )
        )

        XCTAssertFalse(plan.usesLocalExact)
        XCTAssertEqual(plan.candidates.count, 1)
        XCTAssertTrue(plan.candidates.first is ErmaoShared.ReaderRestoreTotalProgression)
    }

    private func makeSource(originalFileHash: String) -> ErmaoShared.ReaderSource {
        ErmaoShared.LocalReaderSource(
            sourceId: "volume-epub-42",
            displayTitle: "Fixture",
            format: .epub,
            contentFingerprint: ErmaoShared.ContentFingerprint(
                originalFileHash: originalFileHash,
                parserVersion: "readium-swift:3.8.0",
                normalizationVersion: "epub-native-sanitized-v1"
            ),
            workId: "work-42",
            volumeId: "volume-epub-42"
        )
    }

    private func makeRemoteSnapshot(updatedAt: Int64) -> ErmaoShared.ReaderProgressSnapshotV4 {
        ErmaoShared.ReaderProgressSnapshotV4(
            sourceId: "volume-epub-42",
            percent: 75,
            updatedAtEpochMillis: updatedAt,
            clientId: "remote-client",
            serverContentFingerprint: ErmaoShared.ReaderServerContentFingerprint(value: "server-version-a"),
            anchor: nil
        )
    }
}
